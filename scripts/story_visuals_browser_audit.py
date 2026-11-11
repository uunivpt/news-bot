"""Per-article charts from explicit report data, using isolated article fixtures."""
import argparse,csv,io,json,sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server
from app.news_numbers import news_number
from api import index as api


def run(output):
 output.mkdir(parents=True,exist_ok=True);base='http://127.0.0.1:8069'
 texts=[('regional sales','Chennai recorded liquor sales worth ₹95.85 crore, while the Tiruchi zone clocked ₹98.97 crore, followed by Madurai at ₹88.38 crore'),('vote share','Vote share: Party A: 55%; Party B: 45%.'),('growth trend','Year | GDP growth (%)\n2022 | 7.6001234%\n2023 | 7.2%\n2024 | 7.1%'),('air quality','The AQI was 344 in Delhi, according to the bulletin.'),('ordinary report','The council announced a new policy on 10 November 2026.'),
        ('qualified vote shares','Vote share: Party A: at least 55%; Party B: at most 45%.'),
        ('AQI range','The AQI was 300–400 in Delhi, according to the bulletin.'),
        ('rainfall ranges','Rainfall: Mumbai: 100 mm to 120 mm; Pune: 80 mm to 90 mm.'),
        ('market index name','The Nifty 50 index rose in early trade.'),
        ('market percentage change','Nifty was 0.5% higher in early trade.'),
        ('explicit market level','Nifty 50 was 24,100.500012 points.'),
        ('AQI sentence','The AQI was 344.'),
        ('index component count','Sensex 30 stocks were discussed.'),
        ('relative point change','Sensex was 200 points lower in early trade.')]
 rows={str(900001+i):{'id':900001+i,'title':'Isolated test: '+title,'article':text,'summary':'Source-linked fixture for article visual acceptance.','source_name':'Fixture source','url':'https://example.org/report','category':'india','status':'published','source_type':'rss','published_at':'2026-11-10T00:00:00Z'}for i,(title,text)in enumerate(texts)}
 documents={}
 for row in rows.values():
  with api.app.test_request_context('/'):
   documents['/india/'+news_number(row)]=api._article_html(row)
 def public_article(identity):return (rows[str(identity)],200) if str(identity)in rows else ({'error':'not found'},404)
 def intercept(route):
  path=urlsplit(route.request.url).path
  if not route.request.url.startswith(base+'/'):route.abort()
  elif path in documents:route.fulfill(content_type='text/html',body=documents[path])
  elif path.startswith('/api/news/') and path.rsplit('/',1)[-1]in rows:route.fulfill(json=rows[path.rsplit('/',1)[-1]])
  else:route.continue_()
 with fixture_server(base),patch.object(api,'article',side_effect=public_article),sync_playwright()as p:
  browser=p.chromium.launch(args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1440,'height':1000},service_workers='block',has_touch=True,reduced_motion='reduce')
  context.route('**/*',intercept);context.add_init_script("localStorage.setItem('ph-consent-v1','essential')")
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  selectors=['.data-bar','.story-slice','.story-point','.article-data-metric',None,None,None,None,
             None,'.article-data-metric','.article-data-metric','.article-data-metric',None,None]
  expected_counts=[3,2,3,1,0,0,0,0,0,1,1,1,0,0]
  paths=list(documents);downloads={}
  for i,selector in enumerate(selectors):
   page.goto(base+paths[i],wait_until='networkidle')
   if selector:
    assert page.locator('.story-numbers '+selector).count()==expected_counts[i]
    assert 'World Bank' not in page.locator('.story-numbers').inner_text()
    assert page.locator('.story-numbers a').first.get_attribute('href')=='https://example.org/report'
    with page.expect_download() as event:
     page.locator('.story-numbers a[download]').click()
    download=event.value;assert download.suggested_filename.endswith('.csv')
    content=Path(download.path()).read_text(encoding='utf-8-sig');downloads[i]=content
    values=list(csv.DictReader(io.StringIO(content)))
    assert len(values)==expected_counts[i]
    assert all(row['source_url']=='https://example.org/report' and row['article_published_at']=='2026-11-10T00:00:00Z' for row in values)
    if i==2:assert values[0]['value']=='7.6001234'
    if i in [9,10,11]:
     expected={9:('0.5','%'),10:('24,100.500012','points'),11:('344','AQI')}[i]
     assert [(r['value'],r['unit'])for r in values]==[expected]
    for width in [320,390,1440]:
     page.set_viewport_size({'width':width,'height':1000})
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(i,width)
     page.locator('.story-numbers').screenshot(path=str(output/f'chart-{i}-{width}.png'))
    if i<3:
     mark=page.locator('.story-numbers '+selector).first;mark.focus()
     assert page.locator('.article-data-tooltip').is_visible()
     page.keyboard.press('Escape');assert page.locator('.article-data-tooltip').is_hidden()
     mark.dispatch_event('pointerdown');assert page.locator('.article-data-tooltip').is_visible()
     page.locator('.article-data-table summary').click();assert page.locator('.article-data-table table').is_visible()
    page.evaluate("document.documentElement.dataset.theme='dark'")
    page.locator('.story-numbers').screenshot(path=str(output/f'chart-{i}-dark.png'))
   else:
    assert page.locator('.article-data').count()==0
    assert texts[i][1] in page.locator('.body').inner_text()
    assert page.get_by_role('link',name='Read the original report',exact=True).get_attribute('href')=='https://example.org/report'
    assert page.locator('time.article-published').get_attribute('datetime').startswith('2026-11-10')
  for identity in ['900006','900007','900008','900009','900013','900014']:
   page.goto(base+'/#/article/'+identity,wait_until='networkidle')
   page.wait_for_selector('.reader-tools')
   # Let the same-origin visual request finish before checking the SPA result.
   page.wait_for_function("async id => (await (await fetch('/api/article-visuals/'+id)).json()).html === ''",arg=identity)
   assert page.locator('.story-numbers').count()==0
   assert rows[identity]['article'] in page.locator('.body').inner_text()
  for identity,value,unit in [('900010','0.5','%'),('900011','24,100.500012','points'),('900012','344','AQI')]:
   page.goto(base+'/#/article/'+identity,wait_until='networkidle');page.wait_for_selector('.story-numbers a[download]')
   assert page.locator('.article-data-metric').count()==1
   with page.expect_download() as event:page.locator('.story-numbers a[download]').click()
   exported=list(csv.DictReader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
   assert [(r['value'],r['unit'])for r in exported]==[(value,unit)]
  page.goto(base+'/#/article/900002',wait_until='networkidle');page.wait_for_selector('.story-slice')
  assert page.locator('.story-slice').count()==2
  with page.expect_download() as event:page.locator('.story-numbers a[download]').click()
  assert Path(event.value.path()).read_text(encoding='utf-8-sig')==downloads[1]
  page.evaluate("location.hash='/settings'");page.wait_for_selector('#prefs');assert page.locator('.story-numbers').count()==0
  page.goto(base+'/',wait_until='networkidle');assert page.locator('.ph-data-home').count()==0
  plain=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':900});plain.route('**/*',intercept)
  reader=plain.new_page();reader.goto(base+paths[1]);assert reader.locator('.story-slice').count()==2
  with reader.expect_download() as event:reader.locator('.story-numbers a[download]').click()
  assert Path(event.value.path()).read_text(encoding='utf-8-sig')==downloads[1]
  reader.locator('.article-data-table summary').click();assert reader.locator('table').is_visible()
  reader.goto(base+paths[5]);assert reader.locator('.article-data').count()==0
  assert texts[5][1] in reader.locator('.body').inner_text()
  reader.goto(base+paths[8]);assert reader.locator('.article-data').count()==0
  reader.goto(base+paths[10]);assert reader.locator('.article-data-metric').count()==1
  with reader.expect_download() as event:reader.locator('.story-numbers a[download]').click()
  assert '24,100.500012' in Path(event.value.path()).read_text(encoding='utf-8-sig');plain.close()
  assert not errors,errors;browser.close()
 report={'passed':True,'checks':['article-specific regional comparison','complete-share pie','yearly line trend','AQI metric card','no data means no chart','320/390/1440px layouts','dark mode','keyboard, Escape and touch','source and exact tables','canonical no-JS reading','SPA article and cleanup','no unrelated homepage dashboard','ranges and qualified values omitted from canonical and SPA figures','original uncertainty, publication date and attribution preserved','CSV downloads preserve values, units, source and publication; canonical/SPA/no-JS agree','index names/counts and relative changes never become levels; exact levels and percentages retain units/precision across canonical/SPA/no-JS and CSV'],'browser_errors':errors}
 (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('artifacts/story-visuals'));args=parser.parse_args();run(args.output)
