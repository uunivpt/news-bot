"""Real HTTPS browser→gateway→phone→anonymous website publication acceptance.

Two isolated processes, synthetic credentials/data, no GitHub SSH or production
writes. HTTPS certificate checks are bypassed ONLY inside this test fixture.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
PHONE='http://127.0.0.1:8056';WEB='https://127.0.0.1:8057'
KEY='isolated-signed-publication-fixture-key-1234567890'
PASSWORD='isolated-publication-owner-password'

WRAPPER=r'''
import os,sys,ssl
from pathlib import Path
sys.path.insert(0,sys.argv[1])
role,path,cert,key=sys.argv[2:6]
os.environ['ADMIN_USERS_JSON']='{}'
os.environ['DATABASE_URL']='';os.environ['DATABASE_3URL']=''
os.environ['POLITICSHUB_ADMIN_BRIDGE_SECRET']='isolated-signed-publication-fixture-key-1234567890'
os.environ['VERCEL']='1' if role=='web' else ''
os.environ['POLITICSHUB_LOCAL_ADMIN']='1' if role=='phone' else ''
from api import index as api
from app.database import NewsDatabase
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from app import remote_admin_bridge as bridge,live_publication as live
if role=='phone':
 db=NewsDatabase(path);api._ensure_admin_users(db)
 db.conn.execute("INSERT INTO admin_users(username,password_hash,role,created_at) VALUES (?,?,?,?)",('pushkarthawari',generate_password_hash('isolated-publication-owner-password'),'owner','2026-11-02T00:00:00Z'));db.conn.commit();db.close()
 api.db=lambda:NewsDatabase(path)
 from scripts.termux_local_admin import configure_private_app
 app=configure_private_app()
 make_server('127.0.0.1',8056,app,threaded=True).serve_forever()
else:
 bridge.bridge_config=lambda:('http://127.0.0.1:8056','isolated-signed-publication-fixture-key-1234567890')
 live.PUBLIC_ORIGIN='https://127.0.0.1:8057'
 from urllib.request import build_opener,HTTPSHandler
 live.build_opener=lambda *handlers:build_opener(HTTPSHandler(context=ssl._create_unverified_context()),*handlers)
 # Keep the test independent of remote feeds and live production content.
 fallback=[{'id':12345,'title':'Existing source story on the public website','summary':'Existing source summary','source_name':'Fixture RSS','url':'https://example.org/rss-existing','published_at':'2026-11-02T00:00:00Z','category':'india','status':'published','public_source':True}]
 api.read_json_rows=lambda path:fallback if str(path).endswith('/news-data.json') else []
 api.remote_rows=lambda cache,lock,local,urls,**kwargs:local
 api._hindi_rows=lambda:[]
 api._official_exam_rows=lambda:[]
 make_server('127.0.0.1',8057,api.app,threaded=True,ssl_context=(cert,key)).serve_forever()
'''


def port_ready(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.3):return True
    except OSError:return False


def run(output):
    output.mkdir(parents=True,exist_ok=True);checks=[]
    with tempfile.TemporaryDirectory() as folder:
        temp=Path(folder);wrapper=temp/'server.py';wrapper.write_text(WRAPPER);cert=temp/'cert.pem';key=temp/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1'],check=True,capture_output=True)
        logs=[];processes=[]
        try:
            for role in ('phone','web'):
                log=(output/(role+'.log')).open('wb');logs.append(log)
                processes.append(subprocess.Popen([sys.executable,str(wrapper),str(ROOT),role,str(temp/'phone.db'),str(cert),str(key)],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT))
            for _ in range(100):
                if all(port_ready(p) for p in (8056,8057)):break
                if any(p.poll() is not None for p in processes):raise RuntimeError('Fixture server failed; inspect logs')
                time.sleep(.1)
            else:raise RuntimeError('Fixture servers did not start')
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(args=['--no-sandbox']);context=browser.new_context(ignore_https_errors=True,service_workers='block',viewport={'width':1440,'height':1000})
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(WEB+'/') else route.abort())
                admin=context.new_page();reader=context.new_page();errors=[]
                admin.on('pageerror',lambda error:errors.append(str(error)));reader.on('pageerror',lambda error:errors.append(str(error)))
                def check(name,callback):
                    started=time.monotonic();callback();checks.append({'name':name,'ok':True,'seconds':round(time.monotonic()-started,2)});print('PASS '+name,flush=True)
                def login():
                    reader.goto(WEB+'/');reader.wait_for_selector('.ph14-lead')
                    admin.goto(WEB+'/admin/');admin.locator('#username').fill('pushkarthawari');admin.locator('#password').fill(PASSWORD);admin.locator('#loginForm [type=submit]').click();admin.wait_for_selector('#overviewMetrics .metric')
                    admin.locator('.nav [data-view=news]').click();admin.wait_for_selector('#news.active')
                    assert admin.locator('#publishManual').is_enabled()
                check('public admin login works through the signed phone gateway',login)
                def fill(title,url):
                    admin.locator('#newTitle').fill(title);admin.locator('#newSourceUrl').fill(url)
                    admin.locator('#newSummary').fill('The local administration issued a detailed public notice describing revised services and the official information available to residents.')
                    admin.locator('#newArticle').fill('The administration published an official notice describing the revised arrangements for residents. The source explains the service schedule and provides contact details. '*8)
                first='An original newly uploaded report appears on the website immediately'
                def direct():
                    fill(first,'https://example.org/original-report');admin.locator('#publishManual').click()
                    admin.wait_for_function('()=>document.querySelector("#manualMessage").textContent.includes("Story published on the website")')
                    assert admin.locator('#notice a').count()>0
                    reader.wait_for_function('(title)=>document.querySelector(".ph14-lead h1")?.textContent===title',arg=first,timeout=15000)
                    assert admin.locator('#manualMessage').inner_text().count('not configured')==0
                    response=reader.request.get(WEB+'/api/news?limit=1');assert response.status==200
                    row=response.json()[0];assert row['editorial_featured'] is True and row['title']==first
                    reader.goto(WEB+__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(admin.locator('#notice a').get_attribute('href')).path)
                    assert first in reader.locator('h1').inner_text();assert 'official notice' in reader.locator('body').inner_text()
                    reader.goto(WEB+'/');reader.wait_for_selector('.ph14-lead')
                check('Publish now confirms anonymous website visibility and updates the open homepage',direct)
                second='A saved draft becomes the main website story with one Verify click'
                def draft_verify():
                    fill(second,'https://example.org/draft-report');admin.locator('#saveManual').click()
                    admin.wait_for_function('()=>document.querySelector("#manualMessage").textContent.includes("saved for human review")')
                    admin.locator('#search').fill(second);admin.wait_for_function('()=>document.querySelectorAll("#newsList .story").length===1 && !document.querySelector("#newsList").hasAttribute("aria-busy")')
                    admin.locator('#newsList [data-news=approve]').click()
                    admin.wait_for_function('()=>document.querySelector("#notice").textContent.includes("Story published on the website")')
                    reader.wait_for_function('(title)=>document.querySelector(".ph14-lead h1")?.textContent===title',arg=second,timeout=15000)
                    assert not admin.locator('#confirmDialog').is_visible()
                check('Verify and publish makes the draft the main website story without another question',draft_verify)
                def promote_existing():
                    admin.locator('#search').fill(first)
                    admin.wait_for_function('(title)=>document.querySelectorAll("#newsList .story").length===1 && document.querySelector("#newsList .story h3")?.textContent===title',arg=first)
                    admin.locator('#newsList [data-news=approve]').click()
                    admin.wait_for_function('()=>document.querySelector("#notice").textContent.includes("Story published on the website")')
                    reader.wait_for_function('(title)=>document.querySelector(".ph14-lead h1")?.textContent===title',arg=first,timeout=15000)
                    data=admin.evaluate("async()=> (await fetch('/api/admin/workspace')).json()")
                    assert sum(row['title']==first for row in data['stories'])==1
                check('Already phone-published news can be made the main website story without a duplicate',promote_existing)
                def reload_receipt():
                    data=admin.evaluate("async()=> (await fetch('/api/admin/workspace')).json()")
                    row=next(r for r in data['stories'] if r['title']==second)
                    receipt=admin.evaluate("async id=>(await fetch('/api/admin/story/'+id+'/delivery')).json()",row['id'])
                    actual=receipt.get('public_delivery',receipt);assert actual['state']=='synced' and actual['channel']=='phone_bridge'
                    public=reader.request.get(WEB+'/api/news?limit=5').json()
                    assert first in [r['title'] for r in public] and second in [r['title'] for r in public]
                    assert all('fact_check_notes' not in r and 'password_hash' not in r for r in public)
                    assert 'no-store' in reader.request.get(WEB+'/api/news?limit=1').headers['cache-control']
                check('confirmed delivery survives admin refresh without SSH and exposes only public fields',reload_receipt)
                assert not errors,errors
                reader.screenshot(path=str(output/'instant-main-news.png'))
                browser.close()
            (output/'report.json').write_text(json.dumps({'scope':'Two isolated HTTP/HTTPS servers; no production news changed','checks':checks},indent=2))
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()
    print(str(len(checks))+' instant publication browser checks passed',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);run(parser.parse_args().output)
