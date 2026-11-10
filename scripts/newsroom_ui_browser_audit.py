"""Exercise the Watermelon-derived news UI against isolated local fixtures.

Run from the repository root:
  python scripts/newsroom_ui_browser_audit.py --output artifacts/newsroom-ui

The existing temporary SQLite fixture serves application assets. Feed responses
and newsletter requests are intercepted in the browser; no production requests,
subscriptions, credentials or writes are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server


def run(base: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    now = datetime.now(timezone.utc)
    feed = [
        {
            'id': 880000 + index,
            'news_number': 880000 + index,
            'title': f'Newsroom fixture {index + 1}: India policy and public affairs update',
            'summary': 'A deterministic source-linked briefing for testing the story cards and navigation.',
            'category': ['india', 'politics', 'world'][index % 3],
            'source_name': ['Fixture News Desk', 'Fixture World Wire'][index % 2],
            'published_at': (now - timedelta(minutes=index + 1)).isoformat(),
            'url': 'https://example.com/original-report',
        }
        for index in range(48)
    ]
    newsletter = {'available': True, 'posts': 0}

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    def check(name, callback):
        start = time.monotonic()
        try:
            callback()
        except Exception as error:
            failure = {
                'check': name, 'error': str(error), 'browser_errors': errors,
                'page_state': page.evaluate("""() => ({
                    active: document.activeElement?.outerHTML.slice(0, 1000),
                    search: document.querySelector('#sp')?.outerHTML.slice(0, 1000),
                    searchVisibility: getComputedStyle(document.querySelector('#sp')).visibility,
                    inputVisibility: getComputedStyle(document.querySelector('#si')).visibility,
                    hasFocus: document.hasFocus(), hidden: document.hidden,
                    scrollY, bodyClass: document.body.className
                })""")
            }
            # Hosted runners do not retain the output directory after failure.
            # Capture state before screenshots finish CSS animations.
            print('FAIL ' + json.dumps(failure), flush=True)
            (output / 'failure.json').write_text(json.dumps(failure, indent=2))
            page.screenshot(path=str(output / 'failure.png'), animations='disabled')
            raise
        checks.append({'check': name, 'status': 'passed', 'seconds': round(time.monotonic() - start, 3)})
        print('PASS ' + name, flush=True)

    def intercept(route):
        url = urlsplit(route.request.url)
        if not route.request.url.startswith(base + '/'):
            route.abort()
        elif url.path == '/__newsroom_static_fixture':
            route.fulfill(content_type='text/html', body=(Path(__file__).resolve().parents[1] / 'public' / 'index.html').read_text())
        elif url.path in {'/api/news', '/news-data.json'}:
            route.fulfill(json=feed, headers={'X-News-Mode': 'live'})
        elif url.path in {'/api/hindi-feed', '/hindi-news.json', '/api/trending'}:
            route.fulfill(json=[])
        elif url.path == '/api/news/version':
            route.fulfill(json={'version': 'newsroom-ui-fixture-v1'})
        elif url.path == '/api/newsletter':
            if route.request.method == 'POST':
                newsletter['posts'] += 1
                route.fulfill(json={'message': 'Fixture confirmation link sent.'})
            else:
                route.fulfill(json={'available': newsletter['available'], 'message': 'Fixture subscriptions unavailable.'})
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(viewport={'width': 1440, 'height': 1050}, service_workers='block')
        context.route('**/*', intercept)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def home():
            response = page.goto(base + '/', wait_until='networkidle')
            require(response.status == 200, 'Homepage did not load')
            page.wait_for_selector('.ph14-home')
            consent = page.locator('[data-consent-choice="essential"]')
            if consent.count() and consent.first.is_visible():
                consent.first.click()

        check('homepage loads the story UI without Reading Room statistics', home)
        require(page.locator('.ph-ui-dashboard, .ph-ui-stats, #ph-ui-overview-tab, #ph-ui-desks-tab').count() == 0, 'Reading Room still appears publicly')

        def delivery_paths():
            for path in ('/india/', '/__newsroom_static_fixture'):
                response = page.goto(base + path, wait_until='networkidle')
                require(response.status == 200, path + ' did not load')
                page.wait_for_selector('.ph14-home')
                require(page.evaluate("typeof window.PHNewsroomUI?.bind === 'function'"), path + ' omits the newsroom controller')
                require(page.evaluate("Array.from(document.styleSheets).some(sheet => sheet.href && new URL(sheet.href).pathname === '/assets/newsroom-ui.css')"), path + ' omits newsroom styles')
                if path == '/india/':
                    require(page.locator('.ph14-cats a[aria-current="page"]').inner_text() == 'India', 'Server category route lost the active news desk')
                    require(page.locator('.ph14-kicker').inner_text().lower() == 'india', 'Server category route mixed the lead story desk')
                else:
                    require(page.evaluate("Array.from(document.styleSheets).some(sheet => sheet.href && new URL(sheet.href).pathname === '/assets/home-critical.css')"), 'Static homepage fixture did not load its bundled stylesheet')
            home()
        check('server-rendered categories and the static homepage both load the newsroom assets', delivery_paths)

        def density():
            compact = page.locator('[data-news-density="compact"]')
            compact.click()
            require(compact.get_attribute('aria-pressed') == 'true', 'Compact control state did not update')
            require(page.locator('.ph14-feed').get_attribute('data-density') == 'compact', 'Feed density did not update')
            page.evaluate('render(true)')
            require(page.locator('[data-news-density="compact"]').get_attribute('aria-pressed') == 'true', 'A feed refresh lost density preference')
            require(page.locator('.ph14-feed').get_attribute('data-density') == 'compact', 'A feed refresh reset compact rows')
            page.locator('[data-news-density="comfortable"]').click()
            require(page.locator('.ph14-feed').get_attribute('data-density') == 'comfortable', 'Comfortable density did not restore')
        check('density controls update the feed and survive a background rerender', density)

        def load_more():
            # Home intentionally includes only English India and World stories;
            # Politics-only fixtures are excluded, unlike the old mixed feed.
            visible = [row for row in feed if row['category'] in {'india', 'world'}]
            expected_rows = len(visible) - 4  # lead plus three brief cards
            before = page.locator('.ph14-row').count()
            require(before == min(expected_rows, 20), 'Initial home pagination count is incorrect')
            require(page.locator('.ph14-more').count() == 1, 'Fixture should expose the load-more control')
            while page.locator('.ph14-more').count():
                more = page.locator('.ph14-more')
                more.focus()
                page.keyboard.press('Enter')
                next_count = min(before + 20, expected_rows)
                require(page.locator('.ph14-row').count() == next_count,
                        'Load more did not append the next page')
                require(page.locator('.ph14-row').nth(before).evaluate(
                    '(node) => node === document.activeElement'),
                    'Loading rows lost keyboard continuation')
                before = next_count
            require(page.locator('.ph14-row').count() == expected_rows,
                    'Final page dropped reports or included non-Home categories')
        check('loading more reports appends every row and continues keyboard focus', load_more)

        def search():
            # Delay visibility deterministically: the old 50 ms focus timer
            # could run while a newly opened dialog was still hidden.
            transition = page.add_style_tag(content='#sp {transition: opacity .3s, visibility .2s step-end}')
            try:
                page.keyboard.press('Control+k')
                page.wait_for_selector('#sp.open')
                page.wait_for_function("() => document.querySelector('#si') === document.activeElement")
                page.keyboard.press('Escape')
                page.wait_for_selector('#sp.open', state='hidden')
                trigger = page.locator('[data-news-search]')
                require(trigger.count() > 0, 'Homepage search trigger missing')
                trigger.first.click()
                page.wait_for_selector('#sp.open')
                page.wait_for_function("() => document.querySelector('#si') === document.activeElement")
                page.keyboard.press('Escape')
                page.wait_for_selector('#sp.open', state='hidden')
                # Closing before the delayed focus must preserve its opener.
                page.evaluate("document.querySelector('#sbtn').focus(); openS(); closeS()")
                page.wait_for_timeout(300)
                require(page.locator('#sbtn').evaluate('(node) => node === document.activeElement'), 'A closed dialog stole focus')
            finally:
                transition.evaluate('(node) => node.remove()')
        check('Ctrl+K and the homepage search control open the existing search dialog', search)

        def newsletter_form():
            form = page.locator('#homeNl')
            form.locator('input[type="email"]').fill('fixture@example.com')
            form.locator('input[name="privacy"]').check()
            form.locator('input[name="adult"]').check()
            form.locator('button[type="submit"]').click()
            page.wait_for_function("() => document.querySelector('#homeNlMsg').textContent.includes('Fixture confirmation')")
            require(newsletter['posts'] == 1, 'Expected one intercepted subscription request')
            require(form.locator('input[type="email"]').input_value() == '', 'Successful subscription did not reset the form')
            newsletter['available'] = False
            page.evaluate('render(true)')
            page.wait_for_function("() => document.querySelector('#homeNl button[type=submit]').disabled")
            require('unavailable' in page.locator('#homeNlMsg').inner_text().lower(), 'Unavailable newsletter state lacks a visible explanation')
        check('newsletter keeps confirmation feedback and its unavailable state', newsletter_form)

        def responsive():
            for width in (320, 390, 768, 1000, 1440):
                page.set_viewport_size({'width': width, 'height': 1050})
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Homepage overflows at {width}px')
                require(page.locator('.ph-ui-dashboard').count() == 0, 'Removed Reading Room appeared on responsive layout')
                if width == 1000:
                    require(page.locator('.ph14-side').evaluate('(node) => getComputedStyle(node).display') == 'block', 'Tablet lead sidebar retained the stacked mobile grid')
                if width in (390, 1440):
                    page.evaluate('scrollTo(0, 0)')
                    page.screenshot(path=str(output / f'newsroom-home-{width}.png'), animations='disabled')
            page.evaluate("document.documentElement.dataset.theme = 'dark'")
            page.evaluate('scrollTo(0, 0)')
            page.screenshot(path=str(output / 'newsroom-home-dark-1440.png'), animations='disabled')
            page.evaluate("document.documentElement.dataset.theme = 'light'")
        check('mobile, tablet and desktop layouts fit the viewport in both themes', responsive)

        def reduced_motion():
            reduced = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce', service_workers='block')
            reduced.route('**/*', intercept)
            reader = reduced.new_page()
            reader.on('pageerror', lambda error: errors.append(str(error)))
            try:
                reader.goto(base + '/', wait_until='networkidle')
                reader.wait_for_selector('.ph14-home')
                require(reader.locator('.ph-ui-home').evaluate('(node) => !node.classList.contains("ph-ui-motion-ready")'), 'Reduced motion enabled scroll reveal')
                require(reader.locator('.ph-ui-reveal').evaluate_all('(nodes) => nodes.every(node => getComputedStyle(node).opacity === "1")'), 'Reduced-motion content is hidden')
                require(reader.locator('.ph-ui-dashboard').count() == 0, 'Removed Reading Room returned in reduced-motion mode')
            finally:
                reduced.close()
        check('reduced motion keeps all story content visible', reduced_motion)

        require(not errors, 'Browser errors: ' + '; '.join(errors))
        context.close()
        browser.close()
    (output / 'report.json').write_text(json.dumps({
        'base_url': base, 'checks': checks, 'browser_errors': errors,
        'scope': 'Isolated local fixture server, deterministic intercepted feeds and newsletter responses; no production requests or subscriptions.'
    }, indent=2))
    print(f'{len(checks)} browser checks passed; report: {output / "report.json"}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8012')
    parser.add_argument('--output', type=Path, default=Path('artifacts/newsroom-ui'))
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {'localhost', '127.0.0.1'}:
        raise SystemExit('Run browser fixtures only against a local development server.')
    with fixture_server(args.base_url):
        run(args.base_url.rstrip('/'), args.output)
