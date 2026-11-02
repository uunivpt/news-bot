"""Isolated browser checks for full archive search, counts and official exams."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server


def main():
 base='http://127.0.0.1:8048'
 with fixture_server(base),sync_playwright() as p:
  browser=p.chromium.launch(args=['--no-sandbox']);context=browser.new_context(service_workers='block',reduced_motion='reduce')
  context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
  page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto(base+'/');page.wait_for_selector('#app .ph14-hero')
  assert 'Tom Hardy Wears Vans Sneakers to Charity Event' not in page.locator('#app').inner_text()
  page.locator('#sbtn').click();page.locator('#si').fill('charity hardy vans')
  page.wait_for_function("() => document.querySelector('#sres').textContent.includes('Tom Hardy')")
  page.locator('#sres a').first.click();page.wait_for_url('**/india/617958005290')
  assert '617958005290' in page.locator('main').inner_text()
  page.goto(base+'/exams/');page.wait_for_selector('#examNotices article')
  page.locator('#examRegion').select_option('maharashtra')
  assert page.locator('#examNotices article').count()>0
  assert 'Common Entrance Test Cell' in page.locator('#examNotices').inner_text()
  for href in page.locator('#examNotices a').evaluate_all('(nodes)=>nodes.map(n=>n.href)'):
   assert href.startswith('https://cetcell.mahacet.org/')
  page.locator('#examQuery').fill('unmatchable-exam-query')
  assert page.locator('#examNotices article').count()==0
  assert page.locator('#examSources article').count()==11
  page.goto(base+'/library/');page.wait_for_function("() => document.querySelector('#libraryCounts').textContent.includes('Total public')")
  counts=page.request.get(base+'/api/library').json();assert counts['news_articles']>=16707
  assert counts['official_exam_notices']>=186;assert counts['google_indexed'] is None
  assert not errors,errors
  page.screenshot(path='/tmp/politicshub-library.png')
  print(json.dumps({'result':'passed','checks':['archived headline absent from home','reordered keyword search','clean archived article URL','Maharashtra official notices','official source links','empty notice search','11 official authorities','honest library counts'],'counts':counts}))
  browser.close()

if __name__=='__main__':main()
