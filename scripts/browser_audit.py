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
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
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
        if admin_fixture:
            # The homepage's newest report can come from an independent Hindi
            # feed with an absolute canonical redirect to the production host.
            # Reader controls must be exercised on a stable local article,
            # without sending an isolated fixture browser to production.
            catalog = page.request.get(base + '/api/news?category=india&limit=20')
            require(catalog.status == 200, 'Fixture India feed unavailable')
            canonical = None
            for row in catalog.json():
                number = row.get('news_number') or row.get('id')
                if not number:
                    continue
                candidate = '/india/' + str(number)
                if page.request.get(base + candidate, max_redirects=0).status == 200:
                    canonical = candidate
                    break
            require(canonical is not None, 'No locally readable canonical news article for reader controls')
            article_href = canonical

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

        def search_keyboard_filters():
            page.locator('#sbtn').click()
            page.wait_for_function("() => document.activeElement === document.querySelector('#si')")
            page.locator('#si').fill('')
            page.wait_for_function("() => document.querySelectorAll('#sres .sr').length === 0")
            page.locator('[data-search-cat="hindi"]').focus()
            page.keyboard.press('Tab')
            require(page.locator('#searchSource').evaluate('(node) => node === document.activeElement'), 'Tab skips publisher filter')
            page.keyboard.press('Tab')
            require(page.locator('#searchPeriod').evaluate('(node) => node === document.activeElement'), 'Tab skips publication-date filter')
            page.keyboard.press('Tab')
            require(page.locator('#si').evaluate('(node) => node === document.activeElement'), 'Search focus escapes the last filter')
            page.keyboard.press('Shift+Tab')
            require(page.locator('#searchPeriod').evaluate('(node) => node === document.activeElement'), 'Reverse Tab skips the last filter')
            page.keyboard.press('Escape')
            require(page.locator('#sbtn').evaluate('(node) => node === document.activeElement'), 'Closing search loses its trigger focus')
        check('keyboard search reaches publisher/date filters and wraps within the dialog', search_keyboard_filters)

        def search_new_tab():
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(base + '/', wait_until='networkidle')
                page.locator('#sbtn').click()
                page.locator('#si').fill('India')
                page.wait_for_function("() => !document.querySelector('#sc').textContent.includes('Searching') && document.querySelectorAll('#sres .sr').length > 0")
                original_url = page.url
                count = page.locator('#sres .sr').count()
                period = page.locator('#searchPeriod').input_value()
                source = page.locator('#searchSource').input_value()
                result = page.locator('#sres .sr').first
                href = result.get_attribute('href')
                with context.expect_page() as opened:
                    result.click(modifiers=['Control'])
                article = opened.value
                article.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    article.wait_for_url(base + href, wait_until='domcontentloaded')
                    require(article.locator('.art h1').is_visible(), 'Ctrl+click did not open a readable article')
                    require(page.url == original_url, 'Ctrl+click navigated the original tab')
                    require(page.locator('#sp').get_attribute('aria-hidden') == 'false', 'Ctrl+click closed the original search')
                    require(page.locator('#si').input_value() == 'India', 'Ctrl+click lost the search query')
                    require(page.locator('#searchPeriod').input_value() == period and page.locator('#searchSource').input_value() == source, 'Ctrl+click changed search filters')
                    require(page.locator('#sres .sr').count() == count, 'Ctrl+click changed search results')
                finally:
                    article.close()
                # Cancel native navigation after the app handler so OS-specific
                # modifiers can be checked without opening windows/downloads.
                for modifier in ('metaKey', 'shiftKey', 'altKey'):
                    result.evaluate("""(link,modifier) => {
                        document.addEventListener('click',event=>event.preventDefault(),{once:true});
                        link.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,button:0,[modifier]:true}));
                    }""", modifier)
                    require(page.locator('#sp').get_attribute('aria-hidden') == 'false', modifier + ' closed the original search')
                for activation in ('click', 'Enter'):
                    page.evaluate("document.addEventListener('click',event=>event.preventDefault(),{once:true})")
                    if activation == 'click':
                        result.click()
                    else:
                        result.focus()
                        page.keyboard.press('Enter')
                    require(page.locator('#sp').get_attribute('aria-hidden') == 'true', activation + ' no longer closes search')
                    if activation == 'click':
                        page.locator('#sbtn').click()
                        page.wait_for_function("() => !document.querySelector('#sc').textContent.includes('Searching') && document.querySelectorAll('#sres .sr').length > 0")
            finally:
                page.close()
        check('opening search results in another tab preserves the original search', search_new_tab)

        def search_pagination_focus():
            rows = [{'id': 990000 + index, 'title': f'focusfixture report {index + 1}',
                     'category': 'india', 'source_name': 'Pagination fixture',
                     'published_at': datetime.now(timezone.utc).isoformat()}
                    for index in range(52)]
            pending, hold = [], False
            pattern = base + '/api/search?*'

            def respond(route):
                offset = int(parse_qs(urlsplit(route.request.url).query).get('offset', ['0'])[0])
                if hold and offset:
                    pending.append(route)
                else:
                    route.fulfill(json=rows[offset:offset + 50], headers={'X-Search-Total': '52'})

            page.route(pattern, respond)
            try:
                page.locator('#sbtn').click()
                page.locator('#si').fill('focusfixture')
                page.wait_for_function("() => document.querySelectorAll('#sres .sr').length === 50 && !document.querySelector('#sc').textContent.includes('Searching')")
                page.locator('#searchMore').focus()
                page.keyboard.press('Enter')
                page.wait_for_function("() => document.querySelectorAll('#sres .sr').length === 52")
                require(page.locator('#sres .sr').nth(50).evaluate('(node) => node === document.activeElement'), 'Loading more search results lost keyboard continuation')
                page.keyboard.press('Tab')
                require(page.locator('#sres .sr').nth(51).evaluate('(node) => node === document.activeElement'), 'Tab skipped the next new result')
                page.keyboard.press('Tab')
                require(page.locator('#si').evaluate('(node) => node === document.activeElement'), 'Final search result did not wrap to the query')
                page.keyboard.press('Escape')
                page.locator('#sp').wait_for(state='hidden')
                page.locator('#sbtn').click()
                page.locator('#si').fill('focusfixture')
                page.wait_for_function("() => document.querySelectorAll('#sres .sr').length === 50")
                hold = True
                page.locator('#searchMore').focus()
                page.keyboard.press('Enter')
                deadline = time.monotonic() + 5
                while not pending and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                require(len(pending) == 1, 'Pagination request was not held')
                page.locator('#si').focus()
                pending.pop().fulfill(json=rows[50:], headers={'X-Search-Total': '52'})
                page.wait_for_function("() => document.querySelectorAll('#sres .sr').length === 52")
                require(page.locator('#si').evaluate('(node) => node === document.activeElement'), 'Pagination stole focus after the reader moved it')
                page.keyboard.press('Escape')
            finally:
                for route in pending:
                    route.abort()
                page.unroute(pattern, respond)
        check('keyboard search pagination continues at new results and respects moved focus', search_pagination_focus)

        def startup_keeps_reader_controls():
            # Release the independent startup feeds one at a time so both the
            # early English paint and the final combined paint happen mid-use.
            for control in ('search', 'drawer'):
                cold = browser.new_context(viewport={'width': 390, 'height': 844},
                                           reduced_motion='reduce', service_workers='block')
                cold.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                held = {}
                cold.route('**/api/news?category=all&limit=120', lambda route: held.update(english=route))
                cold.route('**/api/hindi-feed', lambda route: held.update(hindi=route))
                try:
                    cold_page = cold.new_page()
                    cold_page.on('pageerror', lambda error: errors.append(str(error)))
                    cold_page.goto(base + '/', wait_until='domcontentloaded')
                    consent = cold_page.locator('#privacyConsent [data-consent-choice="essential"]')
                    consent.wait_for(state='visible')
                    consent.click()
                    cold_page.locator('#sbtn' if control == 'search' else '#bg').click()
                    if control == 'search':
                        cold_page.locator('#si').fill('India')
                        cold_page.locator('#searchPeriod').select_option('week')
                        cold_page.wait_for_function("() => document.querySelectorAll('#sres .sr').length > 0 && !document.querySelector('#sc').textContent.includes('Searching')")
                    focused = cold_page.evaluate('document.activeElement.id')
                    selected_source = ''
                    require(set(held) == {'english', 'hindi'}, 'Startup feeds were not held')
                    for feed in ('english', 'hindi'):
                        held.pop(feed).continue_()
                        if feed == 'english':
                            cold_page.locator('.ph14-lead').wait_for()
                        else:
                            cold_page.wait_for_function('() => lastRefreshAt > 0')
                        root = cold_page.locator('#sp' if control == 'search' else '#dr')
                        require(root.get_attribute('aria-hidden') == 'false', f'{feed} startup paint closed {control}')
                        require(cold_page.evaluate('document.activeElement.id') == focused, f'{feed} startup paint moved {control} focus')
                        if control == 'search':
                            require(cold_page.locator('#si').input_value() == 'India', 'Startup paint lost search query')
                            require(cold_page.locator('#searchPeriod').input_value() == 'week', 'Startup paint lost date filter')
                            require(cold_page.locator('#sres .sr').count() > 0, 'Startup paint lost search results')
                            publishers = cold_page.locator('#searchSource option').evaluate_all('(nodes) => nodes.map(node => node.value)')
                            loaded_sources = cold_page.evaluate('() => [...new Set(S.items.map(item => item.source).filter(Boolean))]')
                            require(all(source in publishers for source in loaded_sources), f'{feed} publishers missing from open search')
                            require(len(publishers) == len(set(publishers)), 'Publisher options duplicated')
                            require(cold_page.locator('#searchSource').input_value() == selected_source, 'Feed arrival reset publisher selection')
                            if feed == 'english':
                                # Archive results can include publishers absent from
                                # the bounded startup feed. Select a loaded publisher.
                                selected_source = next((source for source in loaded_sources if 'india' in source.lower()), '')
                                require(bool(selected_source), 'No loaded India publisher for startup filter check')
                                cold_page.locator('#searchSource').select_option(selected_source)
                                cold_page.wait_for_function("() => document.querySelectorAll('#sres .sr').length > 0 && !document.querySelector('#sc').textContent.includes('Searching')")
                                cold_page.locator('#searchSource').focus()
                                focused = 'searchSource'
                    cold_page.keyboard.press('Escape')
                    trigger = '#sbtn' if control == 'search' else '#bg'
                    require(cold_page.locator(trigger).evaluate('(node) => node === document.activeElement'), 'Startup paint lost trigger focus restoration')
                finally:
                    for route in held.values():
                        route.abort()
                    cold.close()
        check('independent startup feeds preserve active search and drawer controls', startup_keeps_reader_controls)

        if admin_fixture:
            def topical_politics_search():
                from api import index as api
                now = datetime.now(timezone.utc).isoformat()
                reports = [{'id': 88111 + index, 'title': title, 'category': category,
                            'summary': 'Source-linked fixture for a topical search regression.',
                            'source_name': 'Search fixture', 'url': f'https://example.org/search-fixture/{index}',
                            'published_at': now, 'status': 'published', 'public_source': True}
                           for index, (title, category) in enumerate([
                               ('politicsfixture Parliament debate report', 'india'),
                               ('politicsfixture hospital opening report', 'india'),
                               ('politicsfixture Congress meets in Europe', 'world')])]
                with patch.object(api.public_archive, '_load', return_value=tuple(reports)):
                    home()
                    page.locator('#sbtn').click()
                    page.locator('#si').fill('politicsfixture')
                    page.locator('[data-search-cat="politics"]').click()
                    page.wait_for_function("expected => document.querySelector('#sres h3')?.textContent === expected && !document.querySelector('#sc').textContent.includes('Searching')", arg=reports[0]['title'])
                    require(page.locator('#sres .sr').count() == 1, 'Politics search included another desk')
                    href = page.locator('#sres .sr').get_attribute('href')
                    require(href == api.article_path(reports[0]) and href.startswith('/india/'), 'Search changed the canonical desk')
                    result = page.evaluate("async () => (await fetch('/api/search?q=politicsfixture&category=politics')).json()")
                    require(len(result) == 1 and result[0]['category'] == 'india', 'Search rewrote the source category')
                    page.locator('#sres .sr').click()
                    require(page.locator('.art h1').inner_text() == reports[0]['title'], 'Search opened another report')
                    require(page.get_by_role('link', name='Read the original report', exact=True).get_attribute('href') == reports[0]['url'], 'Search lost source attribution')
                home()
            check('Politics search includes India reports and preserves canonical article links', topical_politics_search)

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

        def normal_motion_navigation():
            normal = browser.new_context(viewport={'width': 390, 'height': 844},
                                         reduced_motion='no-preference', service_workers='block')
            normal.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            normal_errors = []
            try:
                reader = normal.new_page()
                reader.on('pageerror', lambda error: normal_errors.append(str(error)))
                reader.goto(base + '/', wait_until='domcontentloaded')
                reader.locator('#privacyConsent [data-consent-choice="essential"]').click()
                reader.wait_for_load_state('networkidle')
                reader.locator('.ph-briefing-entry').click()
                reader.wait_for_load_state('networkidle')
                reader.locator('[name="desk"]').select_option('politics')
                reader.locator('[name="period"]').select_option('week')
                reader.get_by_role('button', name='Update briefing').click()
                reader.wait_for_load_state('networkidle')
                link = reader.locator('.briefing-story h2 a').first
                title = link.inner_text()
                link.click()
                reader.wait_for_load_state('networkidle')
                require(reader.locator('h1').inner_text() == title, 'Normal navigation opened the wrong report')
                require(bool(reader.locator('.body').inner_text().strip()), 'Normal navigation lost article text')
                require(reader.locator('.art').evaluate('(node) => getComputedStyle(node).animationName') != 'none', 'Normal page-entry animation was disabled')
                require(not normal_errors, 'Normal navigation browser errors: ' + repr(normal_errors))
            finally:
                normal.close()
        check('normal-motion homepage, briefing form and article navigation has no browser errors', normal_motion_navigation)

        def article():
            visit(article_href)
            page.wait_for_selector('[data-reader-save]')
            require(bool(page.locator('.body').inner_text().strip()), 'Article body is empty')
            page.locator('[data-reader-save]').click()
            require('Allow preferences' in page.locator('#readerNotice').inner_text(), 'Save ignored consent')
            require(page.evaluate("localStorage.getItem('ph-reading-list-v1')") is None, 'Saved without consent')
            page.locator('select[data-reader-size]').select_option('larger')
            require(page.locator('.art').get_attribute('data-reader-size') == 'larger', 'Text size failed')
            page.emulate_media(media='print')
            require(not page.locator('.reader-tools').is_visible(), 'Print includes controls')
            page.emulate_media(media='screen')
        check('article content, consent-aware save, text size and print layout', article)

        def remembered_reading_size():
            key = 'ph-reader-size-v1'
            isolated = browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
            isolated.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            reader = isolated.new_page()
            reader.on('pageerror', lambda error: errors.append(str(error)))
            try:
                reader.goto(base + '/cookies.html', wait_until='networkidle')
                reader.locator('[data-consent-choice="preferences"]').click()
                reader.goto(base + article_href, wait_until='networkidle')
                reader.locator('select[data-reader-size]').select_option('larger')
                reader.reload(wait_until='networkidle')
                reader.wait_for_selector('select[data-reader-size]')
                require(reader.locator('select[data-reader-size]').input_value() == 'larger', 'Allowed reading size was forgotten after reload')
                require(reader.locator('.art').get_attribute('data-reader-size') == 'larger', 'Remembered size was not applied')
                detail = reader.request.get(base + '/api/news/' + article_href.rstrip('/').split('/')[-1]).json()
                reader.locator('select[data-reader-size]').select_option('large')
                reader.goto(base + '/#/article/' + str(detail['id']), wait_until='networkidle')
                reader.wait_for_selector('select[data-reader-size]')
                require(reader.locator('select[data-reader-size]').input_value() == 'large', 'In-app article lost reading preference')
                reader.goto(base + '/cookies.html', wait_until='networkidle')
                reader.locator('[data-consent-choice="essential"]').click()
                require(reader.evaluate('key => localStorage.getItem(key)', key) is None, 'Cookie choice retained optional reading preference')
                reader.goto(base + article_href, wait_until='networkidle')
                reader.locator('select[data-reader-size]').select_option('larger')
                require(reader.locator('.art').get_attribute('data-reader-size') == 'larger', 'Essential-only reader cannot resize current article')
                require(reader.evaluate('key => localStorage.getItem(key)', key) is None, 'Reading size saved without permission')
                reader.reload(wait_until='networkidle')
                reader.wait_for_selector('select[data-reader-size]')
                require(reader.locator('select[data-reader-size]').input_value() == 'normal', 'Essential-only reload restored optional preference')
                reader.goto(base + '/cookies.html', wait_until='networkidle')
                reader.locator('[data-consent-choice="preferences"]').click()
                reader.evaluate('key => localStorage.setItem(key,"invalid-size")', key)
                reader.goto(base + article_href, wait_until='networkidle')
                reader.wait_for_selector('select[data-reader-size]')
                require(reader.locator('select[data-reader-size]').input_value() == 'normal', 'Invalid stored reading size was applied')
                reader.evaluate("""key => { const set=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k===key)throw new DOMException('Fixture denied','SecurityError');return set.call(this,k,v)}; }""", key)
                reader.locator('select[data-reader-size]').select_option('large')
                require(reader.locator('.art').get_attribute('data-reader-size') == 'large', 'Storage denial blocked current reading size')
                require("couldn't remember" in reader.locator('#readerNotice').inner_text(), 'Storage denial has no reading-size feedback')
                reader.reload(wait_until='networkidle')
                reader.locator('select[data-reader-size]').select_option('normal')
                require(reader.evaluate('key => localStorage.getItem(key)', key) == 'normal', 'Standard size was not saved after storage recovered')
                reader.reload(wait_until='networkidle')
                reader.wait_for_selector('select[data-reader-size]')
                require(reader.locator('select[data-reader-size]').input_value() == 'normal', 'Standard reading size did not persist')
                reader.locator('select[data-reader-size]').select_option('larger')
                reader.goto(base + '/#/settings', wait_until='networkidle')
                reader.wait_for_selector('#prefs')
                reader.locator('[data-consent-choice="essential"]').click()
                require(reader.evaluate('key => localStorage.getItem(key)', key) is None, 'Settings retained optional reading preference')
            finally:
                isolated.close()
        check('reading size persists with permission and respects withdrawal and storage failures', remembered_reading_size)

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

        def saved_storage_failures():
            seed = [{'url': '/india/123456789012', 'title': 'Browser storage fixture', 'savedAt': 1}]
            for action in ('remove', 'clear', 'consent'):
                blocked = browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
                blocked.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                script = """(() => {if(location.origin!==ORIGIN)return;
                    const set=Storage.prototype.setItem, remove=Storage.prototype.removeItem, key='ph-reading-list-v1';
                    if(ACTION!=='consent'){set.call(localStorage,'ph-consent-v1','preferences');set.call(localStorage,key,JSON.stringify(SEED));}
                    window.allowFixtureStorage=false;
                    Storage.prototype.setItem=function(k,v){if(!window.allowFixtureStorage&&[key,'ph-consent-v1'].includes(k))throw new DOMException('Storage fixture denied','SecurityError');return set.call(this,k,v)};
                    Storage.prototype.removeItem=function(k){if(!window.allowFixtureStorage&&k===key)throw new DOMException('Storage fixture denied','SecurityError');return remove.call(this,k)};
                })();""".replace('ORIGIN', json.dumps(base)).replace('ACTION', json.dumps(action)).replace('SEED', json.dumps(seed))
                blocked.add_init_script(script)
                try:
                    reader = blocked.new_page()
                    reader.on('pageerror', lambda error: errors.append(str(error)))
                    reader.goto(base + '/saved.html', wait_until='networkidle')
                    button = reader.locator('[data-reader-' + action + ']')
                    button.click()
                    notice = reader.locator('#readerNotice')
                    require(notice.count() == 1 and notice.is_visible(), action + ' storage failure has no visible feedback')
                    require(notice.get_attribute('role') == 'status' and "couldn't" in notice.inner_text(), action + ' failure is not announced')
                    require(button.evaluate('(node) => node === document.activeElement'), action + ' failure lost retry focus')
                    if action == 'consent':
                        require(reader.evaluate("localStorage.getItem('ph-consent-v1')") is None, 'Failed preference write changed consent')
                        require(reader.locator('#savedConsent').is_visible(), 'Failed preference write hid the choice')
                    else:
                        require(reader.locator('.saved-story').count() == 1, 'Failed storage mutation lost a saved story')
                    reader.evaluate('window.allowFixtureStorage=true')
                    button.click()
                    require("couldn't" not in notice.inner_text(), action + ' retry left a stale error')
                    if action == 'consent':
                        require(reader.evaluate("localStorage.getItem('ph-consent-v1')") == 'preferences', 'Preference retry failed')
                        require(not reader.locator('#savedConsent').is_visible(), 'Preference retry did not update choices')
                    else:
                        require(reader.locator('.saved-story').count() == 0, action + ' retry failed')
                        require(reader.locator('#savedCount').evaluate('(node) => node === document.activeElement'), action + ' success lost status focus')
                finally:
                    blocked.close()
        check('saved-list storage failures show feedback, preserve data and allow retry', saved_storage_failures)

        def sharing():
            page.locator('.article-share').click()
            page.wait_for_selector('.ph-share-panel')
            require(page.locator('.ph-share-choice').count() == 12, 'Share platforms missing')
            require(page.locator('.ph-share-choice').first.get_attribute('href').startswith('https://wa.me/'), 'Share URL invalid')
            page.keyboard.press('Escape')
            require(page.locator('.ph-share-panel').count() == 0, 'Share did not close')
        check('article share sheet and keyboard dismissal', sharing)

        def share_clipboard_keyboard():
            page.evaluate("""() => {
                Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(new DOMException('Clipboard fixture denied','NotAllowedError'))}});
                window.fixtureCopyResult=false;window.fixtureCopyValues=[];
                document.execCommand=command=>{if(command==='copy')window.fixtureCopyValues.push(document.activeElement.value);return window.fixtureCopyResult};
            }""")
            for copied in (False, True):
                page.evaluate('value => window.fixtureCopyResult=value', copied)
                page.locator('.article-share').click()
                copy = page.locator('[data-ph-copy]')
                copy.focus()
                page.keyboard.press('Enter')
                message = 'Link copied.' if copied else 'Please copy the URL from your browser.'
                page.wait_for_function('expected => document.querySelector("[data-ph-message]").textContent === expected', arg=message)
                require(copy.evaluate('(node) => node === document.activeElement'), 'Clipboard fallback lost Copy link focus')
                require(page.evaluate('window.fixtureCopyValues.at(-1)') == page.url, 'Clipboard fallback selected the wrong URL')
                require(page.locator('textarea').count() == 0, 'Clipboard fallback left a temporary control')
                page.keyboard.press('Tab')
                require(page.locator('[data-ph-more]').evaluate('(node) => node === document.activeElement'), 'Tab skipped More apps')
                page.keyboard.press('Tab')
                require(page.locator('[data-ph-close]').evaluate('(node) => node === document.activeElement'), 'Share dialog did not wrap focus')
                page.locator('.article-share').focus()
                page.keyboard.press('Tab')
                require(page.locator('[data-ph-close]').evaluate('(node) => node === document.activeElement'), 'Tab escaped share dialog')
                page.locator('.article-share').focus()
                page.keyboard.press('Shift+Tab')
                require(page.locator('[data-ph-more]').evaluate('(node) => node === document.activeElement'), 'Reverse Tab escaped share dialog')
                page.keyboard.press('Escape')
                require(page.locator('.article-share').evaluate('(node) => node === document.activeElement'), 'Share close lost its trigger focus')
        check('clipboard fallback preserves share-dialog keyboard focus and URL', share_clipboard_keyboard)

        def share_pending_actions():
            reports = page.request.get(base + '/api/news?category=india&limit=20').json()
            other = next(row for row in reports if row['title'] != page.locator('.art h1').inner_text())
            story = {'title': other['title'], 'url': '/india/' + str(other.get('news_number') or other['id'])}
            page.evaluate("""() => {
                window.fixtureCopyCalls=0;window.fixtureLegacyCalls=0;
                Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>{
                    window.fixtureCopyCalls++;
                    return new Promise((resolve,reject)=>{window.finishFixtureCopy=resolve;window.rejectFixtureCopy=()=>reject(new DOMException('Permission denied','NotAllowedError'))});
                }}});
                Object.defineProperty(navigator,'share',{configurable:true,value:()=>new Promise((resolve,reject)=>{window.rejectFixtureShare=()=>reject(new Error('Share unavailable'))})});
                document.execCommand=()=>{window.fixtureLegacyCalls++;return true};
            }""")
            for action in ('copy_success', 'copy_denied', 'more_unavailable'):
                before = page.evaluate('window.fixtureCopyCalls')
                page.locator('.article-share').click()
                page.locator('[data-ph-more]' if action == 'more_unavailable' else '[data-ph-copy]').click()
                page.keyboard.press('Escape')
                page.evaluate('story => window.PoliticsHubShare.open(story.title,story.url,document.querySelector(".article-share"))', story)
                settle = {'copy_success': 'finishFixtureCopy', 'copy_denied': 'rejectFixtureCopy', 'more_unavailable': 'rejectFixtureShare'}[action]
                page.evaluate('async settle => { window[settle](); await new Promise(resolve=>setTimeout(resolve,0)); }', settle)
                require(page.locator('[data-ph-message]').inner_text() == '', 'Old share action changed the new story status')
                require(page.evaluate('window.fixtureLegacyCalls') == 0, 'Old share action copied a stale link through fallback')
                require(page.evaluate('window.fixtureCopyCalls') == before + (action != 'more_unavailable'), 'Closed native share started a stale clipboard request')
                require(page.locator('[data-ph-close]').evaluate('(node) => node === document.activeElement'), 'Old share action stole new dialog focus')
                page.locator('[data-ph-copy]').click()
                page.evaluate('async () => { window.finishFixtureCopy(); await new Promise(resolve=>setTimeout(resolve,0)); }')
                require(page.locator('[data-ph-message]').inner_text() == 'Link copied.', 'Current dialog lost copy feedback')
                page.keyboard.press('Escape')
            page.locator('.article-share').click()
            page.locator('[data-ph-more]').click()
            page.evaluate('async () => { window.rejectFixtureShare(); await new Promise(resolve=>setTimeout(resolve,0)); window.rejectFixtureCopy(); await new Promise(resolve=>setTimeout(resolve,0)); }')
            require(page.evaluate('window.fixtureLegacyCalls') == 1, 'Current native-share failure lost its clipboard fallback')
            require(page.locator('[data-ph-message]').inner_text() == 'Link copied. Open another app to paste it.', 'Current native-share failure lost feedback')
            require(page.locator('[data-ph-more]').evaluate('(node) => node === document.activeElement'), 'Current native-share fallback lost focus')
            page.keyboard.press('Escape')
        check('pending share actions cannot update or copy for a replacement dialog', share_pending_actions)

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

        def measurement_consent():
            requests = []
            page.on('request', lambda request: requests.append(request.url) if 'googletagmanager.com/gtag/js' in request.url else None)
            page.route('https://www.googletagmanager.com/**', lambda route: route.fulfill(
                status=200, content_type='application/javascript', body='/* intercepted measurement fixture */'))
            visit('/nana-patekar-tribute.html')
            require(page.locator('script[src*="/assets/measurement.js"]').count() == 0, 'Withheld notice enables measurement')
            require(page.locator('script[src*="pagead2.googlesyndication.com"]').count() == 0, 'Withheld notice enables advertising')
            # The withheld report is intentionally ad-free. Exercise the real
            # consent module on a local test document without changing eligibility.
            page.route(base + '/__audit_measurement__', lambda route: route.fulfill(
                status=200, content_type='text/html',
                body='<!doctype html><html lang="en"><head><script src="/assets/measurement.js?v=consent1" defer></script></head><body>Consent module fixture</body></html>'))
            visit('/__audit_measurement__')
            page.wait_for_function('() => !!window.googlefc?.callbackQueue?.length')
            require(not requests, 'Measurement requested before consent data')
            page.evaluate("""() => {
              const fc=window.googlefc;
              fc.ConsentModePurposeStatusEnum={CONSENT_MODE_PURPOSE_STATUS_GRANTED:1,
                CONSENT_MODE_PURPOSE_STATUS_DENIED:2,CONSENT_MODE_PURPOSE_STATUS_NOT_APPLICABLE:3};
              window.auditConsent=2;
              fc.getGoogleConsentModeValues=()=>({analyticsStoragePurposeConsentStatus:window.auditConsent,
                adStoragePurposeConsentStatus:window.auditConsent,adUserDataPurposeConsentStatus:window.auditConsent,
                adPersonalizationPurposeConsentStatus:window.auditConsent});
              window.auditConsentCallback=fc.callbackQueue.find(x=>x.CONSENT_MODE_DATA_READY).CONSENT_MODE_DATA_READY;
              window.auditConsentCallback();
            }""")
            require(not requests, 'Denied consent enabled measurement')
            with page.expect_request('https://www.googletagmanager.com/**'):
                page.evaluate('() => { window.auditConsent=1; window.auditConsentCallback(); }')
            page.evaluate('() => { window.auditConsentCallback(); window.auditConsent=2; window.auditConsentCallback(); }')
            require(len(requests)==1, 'Consent callbacks duplicated the measurement loader')
            require(page.evaluate("window['ga-disable-G-2HVZQST08G']===true"), 'Consent withdrawal did not disable Analytics')
        check('measurement waits for consent and handles grant, repeat callbacks and withdrawal', measurement_consent)

        if admin_fixture:
            def devanagari_feed():
                from api import index as api
                now = datetime.now(timezone.utc)
                titles = ['धनतेरस 2026 Live: शुभ संयोग में धनतेरस आज, जानें खरीदारी का शुभ मुहूर्त और किन बातों का रखें ध्यान', 'विद्यालयों में प्रवेश की प्रक्रिया का विवरण']
                rows = [{'id': 88001 + index, 'title': title, 'category': 'hindi',
                         'summary': 'मूळ प्रकाशकाच्या वृत्ताचा संक्षिप्त संदर्भ.',
                         'source_name': 'Browser RSS fixture', 'source_type': 'rss', 'url': f'https://example.org/hindi/{index}',
                         'published_at': (now - timedelta(minutes=index)).isoformat(),
                         'status': 'published', 'public_source': True} for index, title in enumerate(titles)]
                with patch.object(api, '_hindi_rows', return_value=rows):
                    visit('/hindi/')
                    page.wait_for_function("titles => document.querySelector('.ph14-lead h1')?.textContent === titles[0] && document.querySelector('#app').textContent.includes(titles[1])", arg=titles)
                    require(page.locator('.ph14-lead h1').inner_text() == titles[0], 'Devanagari-only lead was dropped')
                    require(titles[1] in page.locator('#app').inner_text(), 'Second Hindi report was dropped')
                    result = page.evaluate("async () => (await fetch('/api/hindi-feed')).json()")
                    require([row['id'] for row in result] == [88001, 88002], 'Hindi API discarded valid reports')
                    require([row['url'] for row in result] == [row['url'] for row in rows], 'Original source links changed')
                    page.screenshot(path=str(output / 'hindi-deva-mobile.png'), animations='disabled')
                    visit(api.article_path(rows[0]))
                    require(page.locator('html').get_attribute('lang') == 'hi', 'Canonical Hindi article declares English')
                    require(page.locator('.art h1').inner_text() == titles[0], 'Hindi article title changed')
                    require(page.get_by_role('link', name='Read the original report', exact=True).get_attribute('href') == rows[0]['url'], 'Hindi article source changed')
                    visit('/#/article/88001')
                    page.wait_for_function("expected => document.documentElement.lang === 'hi' && document.querySelector('.art h1')?.textContent === expected", arg=titles[0])
                    english = page.evaluate("async () => (await (await fetch('/api/news?category=india&limit=1')).json())[0]")
                    require(bool(english), 'English control story is missing')
                    page.evaluate("id => location.hash='/article/'+id", english['id'])
                    page.wait_for_function("expected => document.documentElement.lang === 'en' && document.querySelector('.art h1')?.textContent === expected", arg=english['title'])
                    page.evaluate("location.hash='/article/88001'")
                    page.wait_for_function("() => document.documentElement.lang === 'hi'")
                    page.evaluate("location.hash='/settings'")
                    page.wait_for_function("() => document.documentElement.lang === 'en' && document.querySelector('.set h1')?.textContent === 'Settings'")
                    page.evaluate("location.hash='/article/88001'")
                    page.wait_for_function("() => document.documentElement.lang === 'hi'")
                    page.evaluate("location.hash='/article/999999999999999'")
                    page.wait_for_function("() => document.documentElement.lang === 'en' && document.querySelector('.msg h3')?.textContent === \"We couldn't load this story\"")
                    plain = browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 844})
                    plain.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                    try:
                        plain_page = plain.new_page()
                        plain_page.goto(base + '/hindi/', wait_until='domcontentloaded')
                        require(plain_page.locator('.card').count() == 2, 'Server-rendered Hindi reports were dropped')
                        require(plain_page.locator('html').get_attribute('lang') == 'hi', 'No-JavaScript Hindi desk declares English')
                        plain_page.goto(base + api.article_path(rows[0]), wait_until='domcontentloaded')
                        require(plain_page.locator('html').get_attribute('lang') == 'hi', 'No-JavaScript Hindi article declares English')
                        metadata = json.loads(plain_page.locator('script[type="application/ld+json"]').inner_text())
                        require(metadata['inLanguage'] == 'hi', 'Hindi article metadata declares a different language')
                    finally:
                        plain.close()
            check('Devanagari headlines, Hindi reading language and English route transitions', devanagari_feed)

        def directory():
            visit('/sources.html')
            page.locator('[data-source-kind="official"]').click()
            require(page.locator('[data-source-type="publisher"]:visible').count() == 0, 'Source filter failed')
            require(page.locator('[data-source-type="official"]:visible').count() == 7, 'Official references missing')
            page.screenshot(path=str(output / 'sources-mobile.png'), animations='disabled')
            page.locator('[data-source-kind="all"]').click()
            require(page.locator('.source-reference:visible').count() == 12, 'Reset source filter failed')
            page.locator('#sourceSearch').fill('BBC')
            require(page.locator('.source-reference:visible').count() == 1, 'Source keyword search failed')
            page.locator('[data-source-kind="official"]').click()
            require(page.locator('.source-reference:visible').count() == 0, 'Source search and type filters did not combine')
            require(page.locator('#sourceEmpty').is_visible(), 'Empty directory state missing')
            page.locator('#sourceReset').click()
            require(page.locator('.source-reference:visible').count() == 12, 'Source reset did not restore references')
            require(page.locator('#sourceSearch').input_value() == '', 'Source search did not reset')
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
            require(page.locator('.mh-editorial-intro').is_visible(), 'Maharashtra editorial source context missing')
            require('महाराष्ट्र बातम्या' in page.locator('#mhAboutTitle').inner_text(), 'Marathi editorial context missing')
            require(page.locator('#mhSources a').count()==2, 'Publisher sources not visible')
            original=page.locator('.mh-card-actions a').first.get_attribute('href')
            page.locator('.mh-lang [data-language="en"]').click()
            page.wait_for_function("() => document.documentElement.lang==='en' && !document.querySelector('#mhTranslationNote').hidden")
            require(page.locator('.mh-card-actions a').first.get_attribute('href')==original,'Language changed the original publisher')
            require('original Marathi' in page.locator('#mhTranslationNote').inner_text(),'Unavailable translation was not disclosed')
            require(page.locator('#mhAboutTitle').inner_text()=='Maharashtra news: sources and languages',
                    'English switch did not translate the editorial context')
            failed[0]=True
            page.locator('#mhRefresh').click()
            page.wait_for_function("() => document.querySelector('#mhStatus').textContent.includes('previously loaded')")
            require(page.locator('.mh-lead').count()==1,'A failed refresh erased previously loaded headlines')
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                        f'Maharashtra page overflow at {width}px')
            # Later admin acceptance steps expect a mobile viewport and visible menu.
            page.set_viewport_size({'width':390,'height':844})
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
            # Activation removes obsolete shell caches. Inspect that cache
            # rather than creating a cache for an old hardcoded worker version.
            shell_caches = offline_page.evaluate("async () => (await caches.keys()).filter(name => name.startsWith('politicshub-shell-'))")
            require(len(shell_caches) == 1, f'Expected one active shell cache, found {shell_caches!r}')
            print('Active service-worker shell cache: ' + shell_caches[0], flush=True)
            offline_page.evaluate("""async () => {
                for(let i=0;i<90;i++)await fetch('/assets/site.css?audit='+i);
            }""")
            offline_page.wait_for_function("""async name => {
                const cache=await caches.open(name);
                const keys=await cache.keys();
                return keys.length<=80 && keys.some(key=>key.url.endsWith('?audit=89'));
            }""", arg=shell_caches[0])
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
