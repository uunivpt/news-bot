"""Isolated browser acceptance for events, Marathi studio, evidence and scopes."""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash
from api import index as api
from app.models import NewsItem
from app.seo_indexing import canonical_path
from scripts.browser_audit import fixture_server


def run(output):
    output.mkdir(parents=True,exist_ok=True);checks=[];base='http://127.0.0.1:8050';password='isolated-editorial-browser-password'
    with fixture_server(base),sync_playwright() as playwright:
        db=api.db()
        try:
            db.conn.execute('INSERT INTO admin_users(username,password_hash,role,created_at) VALUES (?,?,?,?)',('pushkarthawari',generate_password_hash(password),'owner','2026-11-02T00:00:00Z'))
            ids=[]
            for index,publisher in enumerate(('TV9 Marathi fixture','ABP Majha fixture','The Hindu fixture')):
                db.insert(NewsItem(publisher,'rss','मराठी studiofixture पाणी पुरवठ्याचे नवीन वेळापत्रक 12 गावांसाठी जाहीर '+str(index),f'https://example.org/studio-fixture/{index}',summary='स्थानिक प्रशासनाने 12 गावांसाठी पाणी पुरवठ्याचे नवीन वेळापत्रक जाहीर केले. रहिवाशांसाठी अधिकृत माहिती उपलब्ध आहे.',category='maharashtra',published_at='2026-11-02T03:00:00Z',public_source=True))
                ids.append(db.conn.execute('SELECT id FROM news_items WHERE url=?',(f'https://example.org/studio-fixture/{index}',)).fetchone()['id'])
            db.conn.commit()
        finally:db.close()
        browser=playwright.chromium.launch(args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort());page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)));page.on('dialog',lambda dialog:(_ for _ in ()).throw(AssertionError('Unexpected confirmation: '+dialog.message)))
        def check(name,callback):
            start=time.monotonic();callback();checks.append({'name':name,'ok':True,'seconds':round(time.monotonic()-start,2)});print('PASS '+name,flush=True)
        def nav(view):
            if page.locator('#menuToggle').is_visible():page.locator('#menuToggle').click()
            page.locator('.nav [data-view='+view+']').click();page.wait_for_selector('#'+view+'.active')
        def open_story(sid):
            nav('studio');page.locator('#studioId').fill(str(sid));page.locator('#studioOpenForm button').click();page.wait_for_function('(id)=>document.querySelector("#studioMessage").textContent.includes("Story #"+id+" ·")',arg=sid)
        def login():
            page.goto(base+'/admin/');page.locator('#username').fill('pushkarthawari');page.locator('#password').fill(password);page.locator('#loginForm [type=submit]').click();page.wait_for_selector('#overviewMetrics .metric')
            assert page.locator('.nav [data-view=events]').is_visible()
        check('primary owner can access all editorial desks',login)
        def group_sources():
            nav('events');page.locator('#eventSearch').fill('studiofixture');page.locator('#eventSearchForm button').click();page.wait_for_function('()=>document.querySelectorAll("[data-event-source]").length===3')
            for sid in ids:page.locator(f'[data-event-source="{sid}"]').check()
            page.locator('#eventTitle').fill('पाणी पुरवठा — fixture event');page.locator('#eventCreate').click();page.wait_for_function('()=>document.querySelector("#eventGroups").textContent.includes("fixture event")')
            page.locator('#eventGroups summary').first.click();assert page.locator('#eventGroups').inner_text().count('Original source')==3
        check('confirmed event compares three actual publisher reports',group_sources)
        def studio_outline():
            page.locator(f'#eventGroups [data-studio="{ids[0]}"]').click();page.wait_for_selector('#studioContent:not(.hidden)')
            assert page.locator('[data-studio-source]').count()==3
            page.locator('#studioOutline').click();page.wait_for_function('()=>document.querySelector("#studioArticle").value.includes("स्रोताधारित")')
            assert 'मूळ स्रोत' in page.locator('#studioPreview').inner_text()
            page.locator('#studioHeadline').fill('महाराष्ट्रातील पाणी पुरवठ्याची संपादकीय माहिती')
            page.locator('#studioArticle').fill('मूळ स्रोतांनुसार उपलब्ध वेळापत्रकाची संपादकीय नोंद. '*30)
            page.locator('#studioSave').click();page.wait_for_function('()=>document.querySelector("#notice").textContent.startsWith("Draft saved;")')
            assert 'studiofixture' in page.locator('#studioSourceList').inner_text()
        check('Marathi draft saves with preview and preserved source headlines',studio_outline)
        def evidence():
            page.locator('#claimStatement').fill('वेळापत्रक 12 गावांना लागू आहे.');page.locator('#claimCreate').click();page.wait_for_selector('[data-evidence-form]',state='attached')
            page.locator('#studioClaims summary').click();form=page.locator('[data-evidence-form]')
            form.locator('[name=publisher]').fill('TV9 Marathi fixture');form.locator('[name=source_url]').fill('https://example.org/official-evidence');form.locator('[name=excerpt]').fill('मूळ वृत्तात 12 गावांचा उल्लेख आहे.');form.locator('[name=assessment]').select_option('supported');form.locator('[type=submit]').click()
            page.wait_for_function('()=>document.querySelector("#studioClaims").textContent.includes("Editor assessment: supported")')
            page.locator('#studioArticle').fill('पुराव्याची पुनर्पडताळणी आवश्यक असलेला बदललेला मसुदा. '*30);page.locator('#studioSave').click()
            page.wait_for_function('()=>document.querySelector("#studioClaims").textContent.includes("Needs review after article edits")')
        check('evidence remains attributed and becomes stale after copy changes',evidence)
        def publish():
            page.locator('#studioVerify').click();page.wait_for_function('()=>document.querySelector("#studioState").textContent==="published"')
            assert page.locator('#studioSave').is_disabled()
        check('Verify publishes directly without evidence prompts or confirmations',publish)
        def public_update():
            page.locator('#updateKind').select_option('correction');page.locator('#updateLabel').fill('पाणी पुरवठ्याविषयी सुधारित नोंद');page.locator('#updateBody').fill('नवीन अधिकृत निवेदनानुसार वेळापत्रकातील माहिती स्पष्ट करण्यात आली.');page.locator('#updateSource').fill('https://example.org/official-update')
            page.locator('#updateSave').click();page.wait_for_selector('[data-publish-update]');page.locator('[data-publish-update]').click();page.wait_for_function('()=>document.querySelector("#studioUpdates").textContent.includes("Published ")')
            db=api.db()
            try:row=dict(db.get_by_id(ids[0]));path=canonical_path(row)
            finally:db.close()
            reader=context.new_page();reader.goto(base+path);assert 'Correction —' in reader.locator('body').inner_text();assert 'IST' in reader.locator('body').inner_text();assert 'सुधारित नोंद' in reader.locator('body').inner_text();reader.close()
        check('published correction reaches reader article with timestamp and source',public_update)
        def readiness():
            nav('readiness');page.wait_for_selector('#readinessMetrics .metric');assert 'Google decides' in page.locator('#readinessNotice').inner_text();assert page.locator('#readinessArticles [data-studio]').count()>0
            fake={'checks':[{'path':'/ads.txt','status':'accessible','http_status':200,'checked_at':'2026-11-02T00:00:00Z','publisher_id_present':True}],'scope':'Synthetic HTTP fixture, not a live production claim'}
            with patch('app.ads_readiness.live_probe',return_value=fake):
                page.locator('#readinessProbe').click();page.wait_for_function('()=>document.querySelector("#readinessLive").textContent.includes("HTTP 200")')
        check('readiness distinguishes measured findings from approval and HTTP scope',readiness)
        def custom_scope():
            nav('team');page.wait_for_selector('#hireRole option[value=editor]',state='attached');page.locator('#hireUsername').fill('studio_staff');page.locator('#hireRole').select_option('editor');page.locator('#hireSubmit').click();page.wait_for_selector('#staffCredentials[open]');generated=page.locator('#staffPassword').input_value();page.locator('#staffCredentialsClose').click()
            page.locator('[data-policy-user=studio_staff]').click();page.wait_for_selector('#policyDialog[open]');page.locator('[data-policy-desk=maharashtra]').check();page.locator('#policyOwnOnly').check();page.locator('#policySave').click();page.wait_for_function('()=>!document.querySelector("#policyDialog").open')
            open_story(ids[1]);page.locator('#studioAssignee').fill('studio_staff');page.locator('#studioAssign').click();page.wait_for_function('()=>document.querySelector("#studioAssignment").textContent.includes("studio_staff")')
            staff_context=browser.new_context(service_workers='block');staff_context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort());staff=staff_context.new_page()
            try:
                staff.goto(base+'/admin/');staff.locator('#username').fill('studio_staff');staff.locator('#password').fill(generated);staff.locator('#loginForm [type=submit]').click();staff.wait_for_selector('#overviewMetrics .metric')
                data=staff.evaluate("async()=> (await fetch('/api/admin/workspace')).json()")
                assert data['stats']['total']==1 and data['stories'][0]['id']==ids[1]
                assert staff.locator('.nav [data-view=team]').is_hidden();assert staff.locator('.nav [data-view=readiness]').is_hidden()
                result=staff.evaluate("async id=>{const r=await fetch('/api/admin/studio/'+id);return r.status;}",ids[0]);assert result==403
            finally:staff_context.close()
        check('owner chooses exact powers, desk and assigned-only staff access',custom_scope)
        def responsive():
            for view in ('events','studio','readiness','team'):
                for width in (390,1440):
                    page.set_viewport_size({'width':width,'height':900});nav(view)
                    if view=='events':page.wait_for_selector('#eventSourceList .source-report')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(view,width)
            page.screenshot(path=str(output/'editorial-desktop.png'))
        check('editorial screens fit mobile and desktop without page overflow',responsive)
        def logout():
            if page.locator('#menuToggle').is_visible():page.locator('#menuToggle').click()
            page.locator('#logout').click();page.wait_for_selector('#login:not(.hidden)')
            assert page.locator('#studioSourceList').inner_text()=='';assert page.locator('#studioClaims').inner_text()==''
        check('logout clears editorial sources, manuscript and evidence',logout)
        assert not errors,errors
        (output/'report.json').write_text(json.dumps({'scope':'Isolated synthetic browser fixtures','checks':checks},indent=2))
        browser.close()
    print(str(len(checks))+' editorial browser checks passed',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);run(parser.parse_args().output)
