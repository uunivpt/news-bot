"""Article chart acceptance checks using local routes and a reviewed dataset.

No production writes, accounts, subscriptions or third-party requests.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server
from app.news_numbers import news_number
from api import index as api


def run(base, output):
    output.mkdir(parents=True, exist_ok=True)
    row = {'id': 17484337260322, 'title': 'Article data acceptance fixture', 'category': 'india',
           'summary': 'A fixture for reading verified historical data.',
           'article': 'This local fixture checks the article renderer. Original article text stays readable.',
           'published_at': '2026-10-11T05:03:28.576032Z', 'source_type': 'rss',
           'source_name': 'Fixture newsroom', 'url': 'https://example.org/report'}
    canonical = '/india/' + news_number(row)
    with api.app.test_request_context('/'):
        document = api._article_html(row)
    from app.article_visuals import for_article, number
    data = for_article(row['id'])
    latest, previous = data['points'][-1], data['points'][-2]
    change = latest['value'] - previous['value']
    expected_change = format(change, '+.3f') if 1e-6 <= abs(change) < .005 else number(change, True)
    expected_cards = [number(latest['value']) + '%', number(previous['value']) + '%', expected_change]
    latest_year = latest['label']
    checks, errors = [], []

    def require(condition, message):
        if not condition:raise AssertionError(message)

    def intercept(route):
        if not route.request.url.startswith(base + '/'):
            route.abort()
        elif urlsplit(route.request.url).path == canonical:
            route.fulfill(content_type='text/html', body=document)
        elif urlsplit(route.request.url).path == '/api/news/' + str(row['id']):
            route.fulfill(json=row)
        else:route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        context = browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block', has_touch=True)
        context.route('**/*', intercept)
        context.add_init_script("localStorage.setItem('ph-consent-v1', 'essential')")
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + canonical, wait_until='networkidle')
        require(page.locator('.article-data-metric').count() == 3, 'Metric cards missing')
        require(page.locator('.article-data-metric strong').all_text_contents() == expected_cards, 'Cards changed the values or units')
        require(page.locator('.data-bar').count() == 6, 'Source observations were dropped')
        require(page.locator('.data-negative').count() == sum(p['value'] < 0 for p in data['points']), 'Negative growth is not distinguished')
        require('2026-10-11' in page.locator('time.article-published').get_attribute('datetime'), 'Data retrieval replaced the article publication date')
        require(page.get_by_role('link', name='Read the original report', exact=True).get_attribute('href') == row['url'], 'Article source changed')
        page.locator('.article-data-table summary').click()
        require(str(latest['value']) in page.locator('.article-data-table').inner_text(), 'Exact source precision was lost')
        page.locator('.article-data-table summary').click()
        checks.append('canonical metrics, negative values, exact-value table and original publication/source')

        last = page.locator('.data-bar').last
        last.focus()
        require(page.locator('.article-data-tooltip').is_visible(), 'Keyboard focus did not reveal the value')
        require(latest_year in page.locator('.article-data-tooltip').inner_text(), 'Tooltip has the wrong observation')
        page.keyboard.press('Escape')
        require(not page.locator('.article-data-tooltip').is_visible(), 'Escape did not dismiss the tooltip')
        require(last.evaluate('(node) => node === document.activeElement'), 'Dismissal moved keyboard focus')
        page.locator('.data-bar').first.tap()
        require(page.locator('.article-data-tooltip').is_visible(), 'Touch did not reveal the value')
        page.keyboard.press('Tab')
        require(page.locator('.data-bar').nth(1).evaluate('(node) => node === document.activeElement'), 'Chart observations are not keyboard reachable')
        checks.append('hover/touch and keyboard values, Tab order and Escape dismissal')

        for width in (320, 390, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            for theme in ('light', 'dark'):
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Article overflow: ' + str(width))
                page.locator('.article-data').scroll_into_view_if_needed()
                page.locator('.data-bar').first.focus()
                page.locator('.article-data').screenshot(path=str(output / f'article-data-{width}-{theme}.png'),
                    style='#hd,.skip-link{visibility:hidden!important}')
                if width < 600:
                    require(page.locator('.article-data-chart').evaluate('(node) => node.scrollWidth > node.clientWidth'), 'Mobile labels were compressed instead of using chart scrolling')
                    page.locator('.data-bar').last.focus()
                    tooltip = page.locator('.article-data-tooltip')
                    require(tooltip.is_visible(), 'Last observation tooltip missing after horizontal scrolling')
                    page.wait_for_function("year => document.querySelector('.article-data-tooltip').textContent.includes(year)", arg=latest_year)
                    require(tooltip.bounding_box()['x'] >= page.locator('.article-data-chart').bounding_box()['x'], 'Mobile tooltip scrolled out of view')
        page.emulate_media(media='print')
        require(page.locator('.article-data-source').is_visible(), 'Print hides source attribution')
        require(not page.locator('.article-data-tooltip').is_visible(), 'Print includes the floating tooltip')
        page.emulate_media(media='screen')
        checks.append('320/390/1440px layouts, both themes and print source/values')

        plain = browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 900})
        plain.route('**/*', intercept)
        reader = plain.new_page()
        reader.goto(base + canonical)
        require(reader.locator('.data-bar').count() == 6, 'No-JavaScript chart missing')
        reader.locator('.article-data-table summary').click()
        require(reader.locator('.article-data-table table').is_visible(), 'No-JavaScript data table unusable')
        plain.close()
        checks.append('no-JavaScript chart and data table remain readable')

        page.goto(base + '/#/article/' + str(row['id']), wait_until='networkidle')
        page.wait_for_selector('.article-data')
        require(page.locator('.article-data-metric strong').first.inner_text() == expected_cards[0], 'SPA article lost the chart')
        require('Original article text' in page.locator('.body').inner_text(), 'SPA body was replaced by the chart')
        page.evaluate("location.hash='/settings'")
        page.wait_for_selector('#prefs')
        require(page.locator('.article-data').count() == 0, 'Leaving the story retained its chart')
        pending = []
        page.route(base + '/api/article-visuals/' + str(row['id']), lambda route: pending.append(route))
        page.evaluate("identity => location.hash='/article/'+identity", str(row['id']))
        page.wait_for_selector('.body')
        for _ in range(40):
            if pending:break
            page.wait_for_timeout(50)
        require(bool(pending), 'Delayed chart request was not exercised')
        page.evaluate("location.hash='/settings'")
        page.wait_for_selector('#prefs')
        from app.article_visuals import render,for_article
        pending[0].fulfill(json={'html': render(for_article(row['id']))})
        page.wait_for_timeout(100)
        require(page.locator('.article-data').count() == 0, 'A late chart response inserted data into another page')
        require(not errors, 'Browser errors: ' + '; '.join(errors))
        checks.append('legacy SPA article renders the same reviewed dataset and navigation clears it')
        context.close();browser.close()
    report = {'checks': checks, 'browser_errors': errors, 'scope': 'Local article/template fixtures and the reviewed World Bank dataset; no production writes.'}
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    for check in checks:print('PASS ' + check)
    print(f'{len(checks)} article data browser checks passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8064')
    parser.add_argument('--output', type=Path, default=Path('artifacts/article-data'))
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {'localhost', '127.0.0.1'}:
        raise SystemExit('Use an isolated local fixture server.')
    with fixture_server(args.base_url):run(args.base_url.rstrip('/'), args.output)
