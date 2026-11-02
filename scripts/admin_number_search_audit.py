"""Browser regression for public-number lookup with an older editor backend.

Uses the existing isolated fixture owner and real bundled public archive.
No production login or database writes.
"""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server


def main():
    base='http://127.0.0.1:8046'
    with fixture_server(base),sync_playwright() as playwright:
        browser=playwright.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(service_workers='block')
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
        # Simulate the deployed older phone: public archive article exists,
        # but its private draft and the new numeric queue search do not.
        context.route('**/api/admin/story/17484337268349',lambda route:route.fulfill(status=404,json={'error':'story not found'}))
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/admin/')
        page.locator('#username').fill('audit_owner')
        page.locator('#password').fill('temporary-fixture-password')
        page.locator('#loginForm [type="submit"]').click()
        page.wait_for_selector('#overviewMetrics .metric')
        page.locator('.nav [data-view="news"]').click()
        page.locator('#status').select_option('pending')
        page.locator('#search').fill('617958005290')
        page.wait_for_function("() => document.querySelector('#newsList').textContent.includes('617958005290') && !document.querySelector('#newsList').hasAttribute('aria-busy')")
        assert 'Tom Hardy' in page.locator('#newsList').inner_text()
        assert page.locator('#newsList .story').count()==1
        page.get_by_role('button',name='Inspect saved article',exact=True).click()
        assert 'news no. 617958005290' in page.locator('#inspectorBody').inner_text().lower()
        assert page.locator('#editStoryForm').count()==0
        page.locator('#loadArticle').click()
        page.wait_for_function("() => document.querySelector('#inspectorArticle').textContent.length>40 && document.querySelector('#inspectorArticle').textContent!=='Loading article…'")
        assert 'not found' not in page.locator('#inspectorArticle').inner_text().lower()
        assert not errors,errors
        page.screenshot(path='/tmp/admin-number-search.png')
        browser.close()
        print('PASS real archive number renders despite pending filter and missing private draft; inspector loads saved text')


if __name__=='__main__':main()
