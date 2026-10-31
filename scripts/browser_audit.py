"""Browser acceptance checks against a running local, seeded PoliticsHub app.

Install development tools with `pip install playwright` and
`python -m playwright install chromium`. Run the Flask app locally, then:
  python scripts/browser_audit.py --output artifacts/browser

Third-party ads/fonts are blocked for repeatable application checks. Maharashtra
publisher responses are fixtures; Python tests exercise the feed adapter itself.
This script neither submits newsletter subscriptions nor signs into production.
"""
import argparse
import json
import time
import os
import sys
import tempfile
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@contextmanager
def fixture_server(base):
    from api import index as api
    from app.database import NewsDatabase
    from werkzeug.serving import make_server
    with tempfile.TemporaryDirectory(prefix='politicshub-browser-') as temp, \
         patch.dict(os.environ, {'DATABASE_3URL':'', 'DATABASE_URL':'', 'VERCEL':'','ADMIN_USERS_JSON':'{}'}):
        path = str(Path(temp) / 'browser.db')
        database = NewsDatabase(path)
        api._bootstrap_news_snapshot(database)
        from werkzeug.security import generate_password_hash
        api._ensure_admin_users(database)
        database.conn.execute("INSERT OR IGNORE INTO admin_users(username,password_hash,role,created_at) VALUES (?,?,?,?)",
                              ('audit_owner',generate_password_hash('temporary-fixture-password'),'owner','2026-10-30T00:00:00Z'))
        database.conn.commit()
        database.close()
        with patch.object(api, 'db', side_effect=lambda: NewsDatabase(path)):
            server = make_server('127.0.0.1', urlsplit(base).port or 8000, api.app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


def run(base, output,admin_fixture=False):
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(name, callback):
        start = time.monotonic()
        callback()
        checks.append({'check': name, 'status': 'passed', 'seconds': round(time.monotonic() - start, 3)})
        print('PASS ' + name, flush=True)

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(viewport={'width': 390, 'height': 844},
                                      reduced_motion='reduce', service_workers='block')
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def visit(path):
            response = page.goto(base + path, wait_until='domcontentloaded')
            require(response.status == 200, f'{path}: HTTP {response.status}')
            consent = page.locator('[data-consent-choice="essential"]')
            if consent.count() and consent.first.is_visible():
                consent.first.click()

        def home():
            visit('/')
            page.wait_for_selector('.ph14-lead')

        check('homepage loads published stories', home)
        article_href = page.locator('.ph14-lead').get_attribute('href')

        def responsive():
            for width in (320, 360, 390, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Homepage overflow at {width}px')
                if width in (390, 1440):
                    page.screenshot(path=str(output / f'home-{width}.png'), animations='disabled')
            for path in ('/briefing/', '/sources.html', '/saved.html', '/about.html', '/newsletter.html', '/india/', '/world/', '/hindi/', '/archive/'):
                for width in (390, 1440):
                    page.set_viewport_size({'width': width, 'height': 900})
                    visit(path)
                    page.wait_for_timeout(100)
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{path} overflow at {width}px')
        check('responsive layouts at mobile, tablet and desktop widths', responsive)

        def drawer():
            page.set_viewport_size({'width': 390, 'height': 844})
            home()
            page.locator('#bg').click()
            require(page.locator('#dr').get_attribute('aria-hidden') == 'false', 'Drawer did not open')
            page.keyboard.press('Shift+Tab')
            require(page.locator('#dr').evaluate('(node) => node.contains(document.activeElement)'), 'Focus escaped drawer')
            page.keyboard.press('Escape')
            require(page.locator('#bg').get_attribute('aria-expanded') == 'false', 'Drawer did not close')
        check('drawer opens, contains keyboard focus and closes', drawer)

        def search():
            page.keyboard.press('/')
            page.wait_for_selector('#sp.open')
            page.locator('#si').fill('India')
            page.wait_for_function("() => !document.querySelector('#sc').textContent.includes('Searching') && document.querySelectorAll('#sres .sr').length > 0")
            require(page.locator('#searchSource').count() == 1, 'Publisher filter missing')
            page.locator('#searchPeriod').select_option('week')
            page.wait_for_function("() => !document.querySelector('#sc').textContent.includes('Searching')")
            page.locator('#si').fill('I')
            page.wait_for_function("() => document.querySelector('#sc').textContent.includes('2 characters')")
            require(page.locator('#sres .sr').count() == 0, 'Short search left stale results')
            page.keyboard.press('Escape')
            require(page.locator('#sp').get_attribute('aria-hidden') == 'true', 'Search did not close')
        check('search, date/publisher controls and short-query recovery', search)

        def ticker():
            page.locator('#pz').click()
            require(page.locator('#pz').get_attribute('aria-pressed') == 'true', 'Ticker pause failed')
            page.locator('#pz').click()
            require(page.locator('#pz').get_attribute('aria-pressed') == 'false', 'Ticker resume failed')
        check('ticker pause and resume', ticker)

        def pagination():
            before = page.locator('.ph14-row').count()
            if page.locator('.ph14-more').count():
                page.locator('.ph14-more').click()
                require(page.locator('.ph14-row').count() > before, 'Load more did not add reports')
        check('homepage load-more adds reports', pagination)

        def briefing():
            home()
            page.locator('.ph-briefing-entry').click()
            require(page.locator('h1').inner_text() == 'Quick Briefing', 'Briefing entry failed')
            count = page.locator('.briefing-story').count()
            require(0 < count <= 6, 'Briefing should show one to six recent reports')
            require(page.locator('.briefing-story time[datetime]').count() == count, 'Publication dates missing')
            require(page.locator('.briefing-story a[target="_blank"]').count() == count, 'Original source links missing')
            require(all('<p ' not in text and '<strong>' not in text for text in page.locator('.briefing-summary').all_text_contents()), 'Publisher markup leaked into snippets')
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Briefing overflow at {width}px')
                if width == 390:
                    page.screenshot(path=str(output / 'briefing-mobile.png'), animations='disabled')
            page.screenshot(path=str(output / 'briefing-desktop.png'), animations='disabled')
            page.locator('[name="desk"]').select_option('world')
            page.locator('[name="period"]').select_option('week')
            page.get_by_role('button', name='Update briefing').click()
            require(page.locator('[name="desk"]').input_value() == 'world', 'Desk filter lost')
            require(page.locator('[name="period"]').input_value() == 'week', 'Period filter lost')
            require(all(value.lower() == 'world' for value in page.locator('.briefing-meta .lbl').all_text_contents()), 'Desk filter leaked other desks')
            no_js = browser.new_context(java_script_enabled=False)
            no_js.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            try:
                plain = no_js.new_page()
                plain.goto(base + '/briefing/', wait_until='domcontentloaded')
                require(plain.locator('.briefing-story').count() == count, 'Briefing requires JavaScript')
            finally:
                no_js.close()
            page.set_viewport_size({'width': 390, 'height': 844})
            home()
        check('quick briefing entry, dates, source links, filters and no-JavaScript reading', briefing)

        def article():
            visit(article_href)
            page.wait_for_selector('[data-reader-save]')
            require(bool(page.locator('.body').inner_text().strip()), 'Article body is empty')
            page.locator('[data-reader-save]').click()
            require('Allow preferences' in page.locator('#readerNotice').inner_text(), 'Save ignored consent')
            require(page.evaluate("localStorage.getItem('ph-reading-list-v1')") is None, 'Saved without consent')
            page.locator('[data-reader-size]').select_option('larger')
            require(page.locator('.art').get_attribute('data-reader-size') == 'larger', 'Text size failed')
            page.emulate_media(media='print')
            require(not page.locator('.reader-tools').is_visible(), 'Print includes controls')
            page.emulate_media(media='screen')
        check('article content, consent-aware save, text size and print layout', article)

        def saved():
            visit('/saved.html')
            page.wait_for_selector('[data-reader-consent]')
            page.locator('[data-reader-consent]').click()
            visit(article_href)
            page.wait_for_selector('[data-reader-save]')
            page.locator('[data-reader-save]').click()
            require(page.locator('[data-reader-save]').get_attribute('aria-pressed') == 'true', 'Save failed')
            visit('/saved.html')
            page.wait_for_selector('.saved-story')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('.saved-story')
            require(page.locator('.saved-story').count() == 1, 'Saved story did not survive navigation/reload')
            page.locator('[data-reader-remove]').click()
            require(page.locator('.saved-story').count() == 0, 'Remove failed')
            visit(article_href)
            page.wait_for_selector('[data-reader-save]')
            page.locator('[data-reader-save]').click()
        check('reading list persists, deduplicates and removes stories', saved)

        def sharing():
            page.locator('.article-share').click()
            page.wait_for_selector('.ph-share-panel')
            require(page.locator('.ph-share-choice').count() == 12, 'Share platforms missing')
            require(page.locator('.ph-share-choice').first.get_attribute('href').startswith('https://wa.me/'), 'Share URL invalid')
            page.keyboard.press('Escape')
            require(page.locator('.ph-share-panel').count() == 0, 'Share did not close')
        check('article share sheet and keyboard dismissal', sharing)

        def settings():
            visit('/#/settings')
            page.wait_for_selector('[data-th="dark"]')
            page.locator('[data-th="dark"]').click()
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('[data-th="dark"]')
            require(page.locator('html').get_attribute('data-theme') == 'dark', 'Theme did not persist')
            page.locator('[data-th="light"]').click()
            require(page.locator('.set h1').inner_text() == 'Settings', 'Cached settings route failed at startup')
        check('cached settings startup and persistent appearance', settings)

        def body_regression():
            page.route('**/api/news/987654321', lambda route: route.fulfill(json={
                'id': 987654321, 'title': 'A complete source-linked integration article', 'category': 'india',
                'article': 'The full article body is a string and must render intact.', 'source_name': 'Browser fixture'}))
            page.evaluate("location.hash='/article/987654321'")
            page.wait_for_function("() => document.querySelector('#app .body')?.textContent.includes('must render intact')")
        check('JSON article string is rendered as full text', body_regression)

        def stale_article():
            pending = []
            page.route('**/api/news/987654322', lambda route: pending.append(route))
            page.evaluate("location.hash='/article/987654322'")
            page.wait_for_function("() => document.querySelector('#app').textContent.includes('Loading this story')")
            page.evaluate("location.hash='/settings'")
            page.wait_for_selector('.set h1')
            if pending:
                try:
                    pending[0].fulfill(json={'id': 987654322, 'title': 'Late response', 'article': 'Late response'})
                except Exception:
                    pass  # The browser may already have cancelled the interception.
            require(page.locator('.set h1').inner_text() == 'Settings', 'Late article replaced settings')
        check('late article request cannot replace a newer route', stale_article)

        def hindi():
            page.evaluate("location.hash='/c/hindi'")
            page.wait_for_function("() => document.documentElement.lang === 'hi'")
        check('Hindi desk sets document language', hindi)

        def directory():
            visit('/sources.html')
            page.locator('[data-source-kind="official"]').click()
            require(page.locator('[data-source-type="publisher"]:visible').count() == 0, 'Source filter failed')
            require(page.locator('[data-source-type="official"]:visible').count() == 7, 'Official references missing')
            page.screenshot(path=str(output / 'sources-mobile.png'), animations='disabled')
            page.locator('[data-source-kind="all"]').click()
            require(page.locator('.source-reference:visible').count() == 12, 'Reset source filter failed')
        check('source directory filtering and reset', directory)

        def maharashtra():
            failed=[False]
            def feed(route):
                if failed[0]:
                    route.fulfill(status=503,json={'error':'temporary fixture failure'})
                    return
                language='en' if 'lang=en' in route.request.url else 'mr'
                route.fulfill(json={'language':language,'status':'ok','refresh_minutes':20,
                    'last_checked':'2026-10-30T12:00:00Z',
                    'translation_status':'unavailable' if language=='en' else 'original',
                    'sources':{'TV9 Marathi':{'available':True},'ABP माझा':{'available':True}},
                    'items':[{'title':'पुण्यात सार्वजनिक वाहतुकीबाबत महत्त्वाची माहिती',
                              'url':'https://www.tv9marathi.com/maharashtra/audit-report',
                              'source_name':'TV9 Marathi','published_at':'2026-10-30T12:00:00Z'}]})
            page.route('**/api/maharashtra?*',feed)
            visit('/maharashtra/')
            page.wait_for_selector('.mh-lead')
            original=page.locator('.mh-card-actions a').first.get_attribute('href')
            page.locator('.mh-lang [data-language="en"]').click()
            page.wait_for_function("() => document.documentElement.lang==='en' && !document.querySelector('#mhTranslationNote').hidden")
            require(page.locator('.mh-card-actions a').first.get_attribute('href')==original,'Language changed the original publisher')
            require('original Marathi' in page.locator('#mhTranslationNote').inner_text(),'Unavailable translation was not disclosed')
            failed[0]=True
            page.locator('#mhRefresh').click()
            page.wait_for_function("() => document.querySelector('#mhStatus').textContent.includes('previously loaded')")
            require(page.locator('.mh-lead').count()==1,'A failed refresh erased previously loaded headlines')
            require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Maharashtra page overflows')
        check('Maharashtra language, attribution and failed-refresh recovery',maharashtra)

        def revoke():
            visit('/cookies.html')
            page.locator('[data-consent-choice="essential"]').click()
            require(page.evaluate("localStorage.getItem('ph-reading-list-v1')") is None, 'Revocation did not clear reading list')
            visit('/saved.html')
            page.wait_for_selector('.reader-empty')
        check('withdrawing preferences clears saved stories', revoke)

        if admin_fixture:
            def admin():
                visit('/admin/')
                page.locator('#username').fill('audit_owner')
                page.locator('#password').fill('temporary-fixture-password')
                page.locator('#loginForm [type="submit"]').click()
                page.wait_for_selector('#shell:not(.hidden)')
                page.wait_for_selector('#overviewMetrics .metric')
                page.locator('#menuToggle').click()
                page.locator('.nav [data-view="settings"]').click()
                page.wait_for_selector('#settings.active')
                page.wait_for_function("() => document.querySelector('#websiteEnabled').checked")
                page.locator('#saveSettings').click()
                page.wait_for_function("() => document.querySelector('#notice').textContent.includes('saved')")
                page.locator('#menuToggle').click()
                page.locator('.nav [data-view="news"]').click()
                page.wait_for_selector('#newsList .story')
                for width in (390,768,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Admin overflow at {width}px')
                page.locator('#search').fill('council')
                page.wait_for_timeout(350)
                page.locator('#search').fill('India')
                page.wait_for_timeout(500)
                page.locator('#logout').click()
                page.wait_for_selector('#login:not(.hidden)')
                require(page.request.get(base+'/api/admin/dashboard').status==401,'Logout did not revoke admin access')
            check('admin login, settings, newsroom responsiveness and logout',admin)
        require(not errors, 'Browser errors: ' + repr(errors))
        context.close()

        def without_javascript():
            plain=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':844})
            plain.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            plain_page=plain.new_page()
            plain_page.goto(base+'/india/',wait_until='domcontentloaded')
            card=plain_page.locator('.card').first
            require(card.count()==1,'Server-rendered cards are missing')
            require(card.evaluate('(node)=>Number(getComputedStyle(node).opacity)')==1,'Server-rendered cards require JavaScript to become visible')
            plain.close()
        check('server-rendered reports remain readable without JavaScript',without_javascript)

        offline = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        offline.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        offline_page = offline.new_page()

        def offline_fallback():
            offline_page.goto(base, wait_until='domcontentloaded')
            offline_page.evaluate('navigator.serviceWorker.ready')
            offline_page.wait_for_function('() => !!navigator.serviceWorker.controller')
            offline.set_offline(True)
            offline_page.goto(base + '/never-visited-offline-report', wait_until='domcontentloaded')
            require('offline' in offline_page.title().lower(), 'Uncached article did not show offline page')
            require('Connection interrupted' in offline_page.locator('h1').inner_text(), 'Offline message missing')
            offline.set_offline(False)
        check('uncached offline navigation has an honest offline page', offline_fallback)

        def bounded_cache():
            offline_page.goto(base,wait_until='domcontentloaded')
            offline_page.evaluate("""async () => {
                for(let i=0;i<90;i++)await fetch('/assets/site.css?audit='+i);
            }""")
            offline_page.wait_for_function("""async () => {
                const cache=await caches.open('politicshub-shell-v19');
                const keys=await cache.keys();
                return keys.length<=80 && keys.some(key=>key.url.endsWith('?audit=89'));
            }""")
        check('service-worker cache remains bounded after 90 distinct assets',bounded_cache)
        offline.close()
        browser.close()
    report = {'base_url': base, 'checks': checks, 'browser_errors': errors,
              'scope': 'Local seeded app. Ads/fonts blocked. No production writes or newsletter sends.'}
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(f'{len(checks)} browser checks passed; report: {output / "report.json"}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path, default=Path('artifacts/browser'))
    parser.add_argument('--serve-fixture', action='store_true', help='Start an isolated temporary SQLite-backed test server')
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {'localhost', '127.0.0.1'}:
        raise SystemExit('Run browser fixtures only against a local development server.')
    with fixture_server(args.base_url) if args.serve_fixture else nullcontext():
        run(args.base_url.rstrip('/'), args.output,args.serve_fixture)
