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
            page.locator('[data-bulk="approve"]').click()
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
            directory=page.locator('#sourceTable').inner_text()
            assert 'TV9' in directory and 'ABP' in directory and 'The Hindu' in directory
            assert 'Entire database' in page.locator('#sourceScope').inner_text()
            # Phase 3 metrics are sourced from actual phone DB rows; fixtures
            # contain no collector attempts or delivery queue history.
            assert page.locator('#sourceTriageMetrics .metric').count()==4
            assert 'Awaiting first check' in page.locator('#sourceTriageMetrics').inner_text()
            assert 'not verified' in page.locator('#sourceTriageNotice').inner_text()
            assert 'No collection checks recorded' in page.locator('#sourceIncidents').inner_text()
            assert 'Unavailable' in page.locator('#sourceOperationsMetrics').inner_text()
            assert 'collection' in page.locator('#sourceOperationsNote').inner_text().lower()
            # Phase 4 starts with no invented source fetch history. Private
            # delivery/corrections tables may not exist in this phone fixture.
            assert page.locator('#phase4Metrics .metric').count()==4
            assert 'Unavailable' in page.locator('#phase4Metrics').inner_text()
            assert page.locator('#phase4Trend tbody tr').count()==14
            assert 'Not recorded' in page.locator('#phase4Trend').inner_text()
            assert 'Previously completed checks cannot be recreated' in page.locator('#phase4TrendNote').inner_text()
            page.screenshot(path=str(output/'phase4-source-alerts-desktop.png'))
            page.screenshot(path=str(output/'source-operations-desktop.png'))
            page.locator('#sourceSearch').fill('TV9')
            assert page.locator('#sourceTable tbody tr').count()>=1
            assert all('TV9' in text for text in page.locator('#sourceTable tbody tr').all_inner_texts())
            page.locator('#sourceSearch').fill('ABP')
            assert 'ABP' in page.locator('#sourceTable').inner_text()
            page.locator('#sourceSearch').fill('')
            page.locator('[data-source-filter]').first.click()
            page.wait_for_selector('#news.active')
            page.wait_for_function("() => document.querySelector('#source').value !== 'all' && !document.querySelector('#newsList').hasAttribute('aria-busy')")
            page.locator('#resetFilters').click()
        check('complete publisher inventory search and full-database drill-down',sources)
        def editing():
            page.wait_for_function("() => !document.querySelector('#newsList').hasAttribute('aria-busy')")
            page.locator('#newsList [data-inspect]').first.click()
            page.locator('.story-editor summary').click()
            page.locator('#editTitle').fill('Local fixture editorial headline')
            page.locator('#editSummary').fill('Reviewed local fixture summary with source attribution.')
            page.locator('#editStoryForm [type="submit"]').click()
            page.wait_for_function("() => !document.querySelector('#inspector').open && document.querySelector('#newsList').textContent.includes('Local fixture editorial headline')")
        check('headline and summary edits persist through the server',editing)
        def stale_refresh():
            before=page.locator('#newsList .story').count()
            page.route('**/api/admin/workspace', lambda route:route.fulfill(
                status=503,content_type='application/json',body='{"error":"Synthetic temporary phone interruption"}'))
            page.locator('#refresh').click()
            page.wait_for_function("() => document.querySelector('#connectionBadge').textContent==='Refresh failed' && !document.querySelector('#refresh').disabled")
            assert page.locator('#newsList .story').count()==before
            assert 'out of date' in page.locator('#workspaceBanner').inner_text()
            page.unroute('**/api/admin/workspace')
            page.locator('#newsRefresh').click()
            page.wait_for_function("() => document.querySelector('#connectionBadge').textContent==='Live database' && !document.querySelector('#newsList').hasAttribute('aria-busy')")
        check('temporary refresh failure retains readable data and recovers',stale_refresh)
        def verify_and_publish():
            from app.models import NewsItem
            database=api.db()
            try:
                url='https://example.org/single-action-publication-fixture'
                database.insert(NewsItem(source_name='Fixture News',source_type='rss',
                    title='Local review fixture explains new district water supply arrangements',
                    url=url,category='india',published_at=NewsItem.now_iso(),public_source=True,
                    summary='The district notice explains its updated water supply arrangements and the official support channels for residents.'))
                row=database.conn.execute('SELECT id FROM news_items WHERE url=?',(url,)).fetchone()
                sid=row['id']
                database.update(sid,status='pending',bot_article='The district notice explains revised public water arrangements and identifies the published timetable. '*8)
            finally:
                database.close()
            page.locator('#resetFilters').click()
            page.locator('#status').select_option('pending')
            button=page.locator(f'[data-news="approve"][data-id="{sid}"]')
            button.wait_for(state='visible')
            assert button.inner_text()=='Verify & publish'
            dialogs=[]
            def reject_dialog(dialog):
                dialogs.append(dialog.type)
                dialog.dismiss()
            page.on('dialog',reject_dialog)
            requests=[]
            def record_request(request):
                if request.method=='POST' and request.url.endswith('/'+str(sid)+'/approve'):
                    requests.append(request)
            page.on('request',record_request)
            button.click()
            page.wait_for_function("() => !mutationBusy && document.querySelector('#notice').textContent.toLowerCase().includes('publish')")
            assert not dialogs,dialogs
            assert len(requests)==1
            assert not page.locator('#confirmDialog').is_visible()
            database=api.db()
            try:
                saved=database.get_by_id(sid)
                assert saved['status']=='published'
                assert saved['approved_at']
            finally:
                database.close()
            page.remove_listener('dialog',reject_dialog)
            page.remove_listener('request',record_request)
            page.locator('#resetFilters').click()
            page.wait_for_function("() => document.querySelectorAll('#newsList .story').length===25 && !document.querySelector('#newsList').hasAttribute('aria-busy')")
        check('one Verify click publishes and persists without any question',verify_and_publish)
        def bulk_verify_and_publish():
            from app.models import NewsItem
            database=api.db()
            ids=[]
            try:
                for index in range(2):
                    url='https://example.org/bulk-publication-fixture-'+str(index)
                    database.insert(NewsItem(source_name='Fixture News',source_type='rss',
                        title='Selected review fixture explains district transport notice number '+str(index),
                        url=url,category='india',published_at=NewsItem.now_iso(),public_source=True,
                        summary='The district transport notice identifies the affected routes and explains where residents can read the published schedules.'))
                    sid=database.conn.execute('SELECT id FROM news_items WHERE url=?',(url,)).fetchone()['id']
                    database.update(sid,status='pending',bot_article='The district transport notice identifies updated routes and schedules for residents. '*10)
                    ids.append(sid)
            finally:
                database.close()
            page.locator('#status').select_option('pending')
            for sid in ids:
                page.locator(f'[data-select="{sid}"]').wait_for(state='visible')
                page.locator(f'[data-select="{sid}"]').check()
            dialogs=[]
            def reject_dialog(dialog):
                dialogs.append(dialog.type)
                dialog.dismiss()
            page.on('dialog',reject_dialog)
            page.locator('[data-bulk="approve"]').click()
            page.wait_for_function("() => !mutationBusy && document.querySelector('#notice').textContent.includes('2 stories published')")
            assert not dialogs,dialogs
            database=api.db()
            try:
                assert all(database.get_by_id(sid)['status']=='published' for sid in ids)
            finally:
                database.close()
            page.remove_listener('dialog',reject_dialog)
            page.locator('#resetFilters').click()
            page.wait_for_function("() => document.querySelectorAll('#newsList .story').length===25 && !document.querySelector('#newsList').hasAttribute('aria-busy')")
        check('explicit selected Verify publishes each story without more questions',bulk_verify_and_publish)
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
            event.value.save_as(output/'diagnostics.pdf')
            data=(output/'diagnostics.pdf').read_bytes()
            assert data.startswith(b'%PDF-') and len(data)>2000
            assert b'csrf_token' not in data and b'password_hash' not in data
        check('keyboard navigation and sanitized diagnostic download',palette)
        def responsive():
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                nav('news')
                page.wait_for_selector('#newsList .story')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if width==390:page.screenshot(path=str(output/'newsroom-mobile.png'))
                nav('sources')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if width==390:page.screenshot(path=str(output/'sources-mobile.png'))
            page.set_viewport_size({'width':390,'height':844})
            nav('news')
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
            assert page.evaluate("visibleRows.length === 0 && rows.length === 0 && document.body.style.overflow === ''")
        check('logout clears authenticated workspace access',signout)
        def owner_hiring():
            database=api.db()
            try:
                database.conn.execute("INSERT INTO admin_users(username,password_hash,role,created_at) VALUES (?,?,?,?)",('pushkarthawari',generate_password_hash(password),'owner','2026-11-02T00:00:00Z'))
                database.conn.commit()
            finally: database.close()
            page.locator('#username').fill('pushkarthawari');page.locator('#password').fill(password)
            page.locator('#loginForm [type="submit"]').click()
            page.wait_for_function("() => document.querySelector('#userName').textContent==='pushkarthawari'")
            nav('team');page.wait_for_selector('#hireRole option[value="viewer"]',state='attached')
            page.locator('#hireUsername').fill('browser_staff');page.locator('#hireRole').select_option('viewer')
            assert 'Read newsroom' in page.locator('#hirePowers').inner_text()
            page.locator('#hireSubmit').click();page.wait_for_selector('#staffCredentials[open]')
            generated=page.locator('#staffPassword').input_value();assert len(generated)>=20
            page.locator('#staffCredentialsClose').click();assert page.locator('#staffPassword').input_value()==''
            staff_context=browser.new_context(service_workers='block')
            staff_context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            staff_page=staff_context.new_page()
            def staff_get(path):
                return staff_page.evaluate("async path => { const r=await fetch(path,{credentials:'same-origin'}); return {status:r.status,body:await r.json()}; }",path)
            try:
                staff_page.goto(base+'/admin/')
                staff_page.locator('#username').fill('browser_staff');staff_page.locator('#password').fill(generated)
                staff_page.locator('#loginForm [type=submit]').click();staff_page.wait_for_selector('#overviewMetrics .metric')
                assert staff_get('/api/admin/users')['status']==403
                assert staff_page.locator('.nav [data-view=team]').is_hidden()
                staff_page.locator('.nav [data-view=news]').click()
                staff_page.wait_for_selector('#newsList .story')
                assert staff_page.locator('#manualComposer').is_hidden()
                assert staff_page.locator('[data-bulk=approve]').is_disabled()
                assert staff_get('/api/admin/workspace')['body']['capabilities']['publish'] is False
                page.locator('[data-staff-role="browser_staff"]').select_option('publisher')
                page.locator('[data-staff="role"][data-user="browser_staff"]').click()
                page.wait_for_function("() => document.querySelector('#notice').textContent==='Staff access updated'")
                assert staff_get('/api/admin/workspace')['body']['capabilities']['publish'] is True
                with page.expect_response(lambda response:response.url.endswith('/api/admin/users/browser_staff') and response.request.method=='POST') as disabled_response:
                    page.locator('[data-staff="disable"][data-user="browser_staff"]').click()
                assert disabled_response.value.status==200
                page.wait_for_function("() => document.querySelector('[data-staff=disable][data-user=browser_staff]').disabled")
                assert staff_get('/api/admin/workspace')['status']==401
            finally: staff_context.close()
            assert page.locator('#teamMembers').inner_text().count('Protected owner')==1
            page.screenshot(path=str(output/'team-owner.png'))
            if page.locator('#menuToggle').is_visible():page.locator('#menuToggle').click()
            page.locator('#logout').click();page.wait_for_selector('#login:not(.hidden)')
        check('main owner hires staff, assigns powers and revokes live access',owner_hiring)
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
