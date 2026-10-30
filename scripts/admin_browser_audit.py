"""Isolated acceptance checks for owner and database-outage Admin Room flows.

Uses temporary SQLite and synthetic login credentials; never contacts production.
Run: python scripts/admin_browser_audit.py --output /tmp/admin-browser
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server
from api import index as api
from app.database import DatabaseUnavailable


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    checks=[]
    base='http://127.0.0.1:8040'
    password='temporary-fixture-password'
    with fixture_server(base),sync_playwright() as playwright:
        browser=playwright.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000},service_workers='block',reduced_motion='reduce',accept_downloads=True)
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def check(name,callback):
            started=time.monotonic()
            callback()
            checks.append({'name':name,'ok':True,'seconds':round(time.monotonic()-started,2)})
            print('PASS '+name,flush=True)
        def nav(view):
            if page.locator('#menuToggle').is_visible():page.locator('#menuToggle').click()
            page.locator('.nav [data-view="'+view+'"]').click()
            page.wait_for_selector('#'+view+'.active')
        def login():
            page.goto(base+'/admin/',wait_until='domcontentloaded')
            page.screenshot(path=str(output/'login-desktop.png'))
            page.locator('#username').fill('audit_owner')
            page.locator('#password').fill(password)
            page.locator('#loginForm [type="submit"]').click()
            page.wait_for_selector('#overviewMetrics .metric')
            assert page.locator('#connectionBadge').inner_text()=='Live database'
            assert page.locator('#overviewMetrics .metric').count()==4
            page.screenshot(path=str(output/'overview-desktop.png'))
        check('database owner login and truthful overview',login)
        def pagination():
            nav('news')
            page.wait_for_selector('#newsList .story')
            ids=page.locator('[data-select]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.select)')
            assert len(ids)==25
            page.locator('#nextPage').click()
            page.wait_for_function("() => document.querySelector('#pageInfo').textContent.includes('Page 2')")
            assert not set(ids)&set(page.locator('[data-select]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.select)'))
            page.locator('#prevPage').click()
            page.wait_for_function("() => document.querySelector('#pageInfo').textContent.includes('Page 1')")
        check('full database queue pagination has no repeated page records',pagination)
        def search():
            page.locator('#search').fill('unmatchable-fixture-query-812')
            page.wait_for_function("() => document.querySelector('#newsCount').textContent.includes('0 matching')")
            page.locator('#search').fill('council')
            page.wait_for_timeout(50)
            page.locator('#search').fill('India')
            page.wait_for_function("() => document.querySelector('#search').value==='India' && document.querySelectorAll('#newsList .story').length>0 && !document.querySelector('#newsList').hasAttribute('aria-busy')")
            page.locator('#resetFilters').click()
            page.wait_for_function("() => document.querySelectorAll('#newsList .story').length===25 && !document.querySelector('#newsList').hasAttribute('aria-busy')")
        check('server search handles empty results and rapid query replacement',search)
        def inspector():
            page.locator('#newsList [data-inspect]').first.click()
            page.wait_for_selector('#inspector[open]')
            assert page.locator('#inspectorTitle').inner_text().strip()
            page.locator('#loadArticle').click()
            page.wait_for_function("() => document.querySelector('#inspectorArticle').textContent.length>0 && document.querySelector('#inspectorArticle').textContent!=='Loading article…'")
            assert 'Request failed' not in page.locator('#inspectorArticle').inner_text()
            page.keyboard.press('Escape')
        check('story inspector loads real source-linked article text',inspector)
        def bulk_limit():
            page.locator('#selectAll').check()
            assert '25 selected' in page.locator('#selectedCount').inner_text()
            page.locator('[data-bulk="publish"]').click()
            assert 'at most 10' in page.locator('#notice').inner_text()
            assert not page.locator('#confirmDialog').is_visible()
            page.locator('#clearSelection').click()
            page.locator('[data-select]').first.check()
            page.locator('[data-bulk="reject"]').click()
            page.wait_for_selector('#confirmDialog[open]')
            page.locator('#confirmCancel').click()
            assert page.locator('#newsList .story').count()==25
            page.locator('#clearSelection').click()
        check('bulk action bound and cancel prevent unintended mutations',bulk_limit)
        def export():
            with page.expect_download() as event:page.locator('#exportNews').click()
            download=event.value
            download.save_as(output/'stories.csv')
            text=(output/'stories.csv').read_text(encoding='utf-8-sig')
            assert 'source_name' in text and len(text.splitlines())>=26
            assert page.evaluate('(value) => csvCell(value).charCodeAt(1) === 39',' =HYPERLINK("https://example.org")')
        check('CSV export contains page data and escapes formula cells',export)
        def sources():
            nav('sources')
            assert page.locator('#sourceTable tbody tr').count()>0
            page.locator('[data-source-filter]').first.click()
            page.wait_for_selector('#news.active')
            page.wait_for_function("() => document.querySelector('#source').value !== 'all' && !document.querySelector('#newsList').hasAttribute('aria-busy')")
            page.locator('#resetFilters').click()
        check('source coverage drill-down filters the newsroom',sources)
        def editing():
            page.wait_for_function("() => !document.querySelector('#newsList').hasAttribute('aria-busy')")
            page.locator('#newsList [data-inspect]').first.click()
            page.locator('.story-editor summary').click()
            page.locator('#editTitle').fill('Local fixture editorial headline')
            page.locator('#editSummary').fill('Reviewed local fixture summary with source attribution.')
            page.locator('#editStoryForm [type="submit"]').click()
            page.wait_for_function("() => !document.querySelector('#inspector').open && document.querySelector('#newsList').textContent.includes('Local fixture editorial headline')")
        check('headline and summary edits persist through the server',editing)
        def telemetry():
            nav('operations')
            page.wait_for_selector('#opsTotals .metric')
            assert page.locator('#agents .agent').count()==10
            nav('upgrade')
            page.wait_for_selector('#upgradeMetrics .metric')
            assert page.locator('#upgradeContent').is_visible()
        check('owner agent and QA views render recorded backend telemetry',telemetry)
        def palette():
            page.keyboard.press('Control+k')
            page.locator('#commandInput').fill('system')
            page.keyboard.press('Enter')
            page.wait_for_selector('#system.active')
            assert page.locator('#systemChecks .metric').count()==4
            with page.expect_download() as event:page.locator('#downloadDiagnostics').click()
            event.value.save_as(output/'diagnostics.json')
            data=json.loads((output/'diagnostics.json').read_text())
            assert data['mode']=='live'
            assert 'csrf_token' not in str(data) and 'audit_owner' not in str(data)
        check('keyboard navigation and sanitized diagnostic download',palette)
        def responsive():
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                nav('news')
                page.wait_for_selector('#newsList .story')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if width==390:page.screenshot(path=str(output/'newsroom-mobile.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#menuToggle').click()
            page.keyboard.press('Escape')
            assert page.locator('#menuToggle').get_attribute('aria-expanded')=='false'
            page.locator('#themeToggle').click()
            assert page.locator('html').get_attribute('data-admin-theme')=='dark'
            page.screenshot(path=str(output/'newsroom-dark-mobile.png'))
            page.locator('#themeToggle').click()
        check('320–1440px layout, mobile menu and theme controls',responsive)
        def settings():
            nav('settings')
            page.wait_for_function("() => !document.querySelector('#saveSettings').disabled")
            original=page.locator('#websiteEnabled').is_checked()
            page.locator('#websiteEnabled').set_checked(not original)
            page.locator('#saveSettings').click()
            page.wait_for_function("() => document.querySelector('#notice').textContent==='Controls saved'")
            result=page.evaluate("async () => (await fetch('/api/admin/settings',{credentials:'same-origin'})).json()")
            assert result['website_enabled']==('false' if original else 'true')
            page.locator('#trainNotes').fill('Use original source attribution for every report.')
            page.locator('#trainBtn').click()
            page.wait_for_function("() => document.querySelector('#notice').textContent==='Knowledge event recorded'")
            nav('activity')
            page.wait_for_selector('.activity-item')
        check('owner settings and knowledge changes persist in audit history',settings)
        def signout():
            page.locator('#menuToggle').click()
            page.locator('#logout').click()
            page.wait_for_selector('#login:not(.hidden)')
            assert page.request.get(base+'/api/admin/workspace').status==401
        check('logout clears authenticated workspace access',signout)
        verifier=generate_password_hash(password)
        with patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps({'audit_owner':verifier})}),patch.object(api,'db',side_effect=DatabaseUnavailable('Synthetic quota outage')):
            def outage_login():
                page.locator('#username').fill('audit_owner')
                page.locator('#password').fill(password)
                page.locator('#loginForm [type="submit"]').click()
                page.wait_for_selector('#shell:not(.hidden)')
                page.wait_for_function("() => document.querySelector('#connectionBadge').textContent==='Snapshot mode'")
                assert 'Read-only' in page.locator('#workspaceBanner').inner_text()
                nav('news')
                page.wait_for_selector('#newsList .story')
                assert page.locator('#factBtn').is_disabled()
                page.screenshot(path=str(output/'recovery-mobile.png'))
            check('quota outage still opens a verified read-only newsroom',outage_login)
            def restrictions():
                nav('settings')
                assert page.locator('#saveSettings').is_disabled()
                response=page.evaluate("async () => { const r=await fetch('/api/news/1/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); return {status:r.status,body:await r.json()}; }")
                assert response['status']==403 and response['body']['code']=='recovery_read_only'
                nav('operations')
                assert page.locator('#opsUnavailable').is_visible()
                assert page.locator('#opsContent').is_hidden()
                nav('upgrade')
                assert page.locator('#upgradeUnavailable').is_visible()
                nav('activity')
                assert 'needs the database' in page.locator('#activityList').inner_text()
            check('recovery blocks mutations and shows honest telemetry states',restrictions)
            def recovery_search():
                nav('news')
                page.locator('#search').fill('India')
                page.wait_for_timeout(350)
                assert page.locator('#newsList .story').count()>0
                with page.expect_download() as event:page.locator('#exportNews').click()
                assert event.value.suggested_filename.endswith('.csv')
                page.locator('#newsList [data-inspect]').first.click()
                page.locator('#loadArticle').click()
                page.wait_for_function("() => document.querySelector('#inspectorArticle').textContent.length>20")
                page.keyboard.press('Escape')
            check('recovery supports local search, export and article inspection',recovery_search)
        def restored():
            page.locator('#refresh').click()
            page.wait_for_function("() => document.querySelector('#workspaceBanner').textContent.includes('Database restored')")
            nav('settings')
            assert page.locator('#saveSettings').is_disabled()
        check('restored database requires reauthentication before writes',restored)
        assert not errors,errors
        checks.append({'name':'no uncaught browser errors','ok':True})
        context.close();browser.close()
    (output/'report.json').write_text(json.dumps({'scope':'Temporary local database and synthetic outage; no production writes','checks':checks},indent=2))
    print(str(len(checks))+' Admin Room checks passed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('/tmp/politicshub-admin-browser'))
    run(parser.parse_args().output)
