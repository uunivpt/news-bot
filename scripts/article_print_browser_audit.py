"""Generate and inspect actual branded PDFs with isolated article fixtures.

Requires Playwright Chromium and poppler-utils (pdfinfo/pdftotext). No production
writes, external fonts, newsletter actions or login attempts.
"""
import argparse,json,re,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server
from app.news_numbers import news_number
from api import index as api


def inspect_pdf(path):
 info=subprocess.check_output(['pdfinfo',str(path)],text=True)
 pages=int(re.search(r'^Pages:\s+(\d+)',info,re.M)[1])
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True)
 raw=subprocess.check_output(['pdftotext','-bbox',str(path),'-'],text=True)
 root=ET.fromstring(raw);positions=[]
 for page in root.iter('{http://www.w3.org/1999/xhtml}page'):
  words=[{'text':w.text or '',**{k:float(w.attrib[k])for k in ['xMin','yMin','xMax','yMax']}}for w in page.iter('{http://www.w3.org/1999/xhtml}word')]
  positions.append(words)
 return {'pages':pages,'text':text,'positions':positions}


def run(output):
 output.mkdir(parents=True,exist_ok=True);base='http://127.0.0.1:8071'
 short={'id':700101,'title':'Regional festive sales reach ₹441 crore amid payment glitches','summary':'Chennai recorded liquor sales worth ₹95.85 crore, while the Tiruchi zone clocked ₹98.97 crore, followed by Madurai at ₹88.38 crore.','article':'Chennai recorded liquor sales worth ₹95.85 crore, while the Tiruchi zone clocked ₹98.97 crore, followed by Madurai at ₹88.38 crore.','category':'india','source_name':'Fixture publisher','url':'https://example.org/original-report','source_type':'rss','status':'published','published_at':'2026-11-01T04:00:00Z','image_url':'/print-photo.svg'}
 paragraph='Residents can review the original council notice for the district timetable, approved routes, named locations and official contact details. The report explains the decision and provides source context without adding any unverified figures. '
 long={**short,'id':700102,'title':'A detailed district report with source context and a readable multi-page edition','summary':'The district notice explains the revised timetable and the official references available to residents.','article':'\n\n'.join(f'Section {i+1}. '+paragraph*3 for i in range(22)),'image_url':''}
 marathi={**short,'id':700103,'title':'महाराष्ट्रातील जिल्हा परिषदेचा नवीन निर्णय जाहीर','summary':'नागरिकांसाठी अधिकृत माहिती आणि मूळ स्रोताची लिंक उपलब्ध आहे.','article':'नागरिकांसाठी अधिकृत माहिती आणि मूळ स्रोताची लिंक उपलब्ध आहे. स्थानिक प्रशासनाने सुधारित वेळापत्रक जाहीर केले आहे.','image_url':''}
 rows={str(r['id']):r for r in [short,long,marathi]};documents={}
 for row in rows.values():
  with api.app.test_request_context('/'):
   document=api._article_html(row)
   if row['image_url'] and 'class="ahero"' not in document and "class='ahero'" not in document:
    document=document.replace('<section class="article-data', '<div class="ahero"><img src="/print-photo.svg" alt="Report photo fixture"></div><section class="article-data',1)
   documents['/india/'+news_number(row)]=document
 photo='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="240"><rect width="640" height="240" fill="#dae2dc"/><text x="35" y="130" font-size="32">Report photo fixture</text></svg>'
 def intercept(route):
  path=urlsplit(route.request.url).path
  if not route.request.url.startswith(base+'/'):route.abort()
  elif path in documents:route.fulfill(content_type='text/html',body=documents[path])
  elif path=='/print-photo.svg':route.fulfill(content_type='image/svg+xml',body=photo)
  elif path.startswith('/api/news/') and path.rsplit('/',1)[-1]in rows:route.fulfill(json=rows[path.rsplit('/',1)[-1]])
  else:route.continue_()
 checks=[];reports={}
 with fixture_server(base),patch.object(api,'article',side_effect=lambda identity:(rows[str(identity)],200)if str(identity)in rows else ({'error':'not found'},404)),sync_playwright()as p:
  browser=p.chromium.launch(args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1280,'height':1000},service_workers='block',timezone_id='America/Los_Angeles')
  context.route('**/*',intercept);context.add_init_script("localStorage.setItem('ph-consent-v1','essential')")
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  for name,row in [('short',short),('long',long),('marathi',marathi)]:
   page.goto(base+'/india/'+news_number(row),wait_until='networkidle')
   page.wait_for_selector('[data-reader-print]')
   assert page.locator('.article-print-masthead').count()==1
   assert not page.locator('.article-print-masthead').is_visible()
   original=page.locator('article.art').evaluate('e=>Array.from(e.children).map(c=>c.className)')
   if name=='short':page.evaluate("document.documentElement.dataset.theme='dark';document.querySelector('.art').dataset.readerSize='larger'")
   path=output/(name+'.pdf')
   page.pdf(path=str(path),display_header_footer=True,prefer_css_page_size=True,print_background=False)
   assert page.locator('article.art').evaluate('e=>Array.from(e.children).map(c=>c.className)')==original
   report=inspect_pdf(path);text=report['text']
   assert 'PoliticsHub.in' in text and 'What matters, clearly.' in text
   assert 'printed / saved' in text.lower() and 'IST' in text
   assert '01 Nov 2026, 09:30 AM IST' in text
   assert 'Page 1 of '+str(report['pages']) in text
   assert row['title']+' — PoliticsHub.in' not in ' '.join(text.split()),'Browser default title header was not replaced'
   assert 'Print edition' not in text,'Clock was not refreshed by beforeprint'
   reports[name]={'pages':report['pages']}
   if name=='short':
    assert report['pages']==1,report['pages']
    assert '95.85' in text and '98.97' in text and '88.38' in text
    assert text.index('Chennai recorded')<text.index('The figures behind this story'),'Article body must precede its chart'
    assert 'Report photo fixture' in text
    title_word=next(w for w in report['positions'][0]if w['text']=='Regional')
    assert title_word['yMin']<150,title_word
   if name=='marathi':assert 'महाराष्ट्रातील' in text
   if name=='short':
    page.pdf(path=str(output/'letter.pdf'),format='Letter',display_header_footer=True,prefer_css_page_size=False)
    assert inspect_pdf(output/'letter.pdf')['pages']==1
   if name=='long':
    assert 3<=report['pages']<=7,report['pages']
    for words in report['positions'][:-1]:
     body_words=[w for w in words if 60<w['yMin']<780]
     assert len(body_words)>100,'Unexpected empty or mostly blank intermediate page'
     assert max(w['yMax']for w in body_words)>650,'Excessive unused space on an intermediate page'
   checks.append(name+' actual PDF, branding, IST clock and restored screen order')
  # The same template must work on the SPA and with JavaScript disabled.
  page.goto(base+'/#/article/'+str(short['id']),wait_until='networkidle');page.wait_for_selector('.story-numbers');page.wait_for_selector('.article-print-masthead',state='attached')
  page.pdf(path=str(output/'spa.pdf'),display_header_footer=True,prefer_css_page_size=True)
  assert inspect_pdf(output/'spa.pdf')['pages']==1
  assert page.locator('.article-print-masthead').count()==1
  plain=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':900});plain.route('**/*',intercept)
  reader=plain.new_page();reader.goto(base+'/india/'+news_number(short),wait_until='networkidle')
  reader.pdf(path=str(output/'no-js.pdf'),display_header_footer=True,prefer_css_page_size=True)
  text=inspect_pdf(output/'no-js.pdf')['text'];assert 'PoliticsHub.in' in text and 'source publication' in text.lower()
  plain.close();assert not errors,errors;browser.close()
 report={'passed':True,'checks':checks+['SPA print','no-JavaScript branded fallback','default browser headers replaced','source publication preserved','A4 and Letter short editions'],'pdfs':reports,'browser_errors':errors}
 (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('artifacts/article-print'));args=parser.parse_args();run(args.output)
