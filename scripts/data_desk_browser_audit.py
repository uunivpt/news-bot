"""Public Data Desk acceptance with local fixtures and reviewed, bundled observations."""
import argparse,csv,io,json,sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.browser_audit import fixture_server
from scripts.chart_export_checks import chart_export


def run(base,output):
 output.mkdir(parents=True,exist_ok=True)
 from app.article_visuals import catalog, number
 datasets=catalog()
 expected_values=[number(d['points'][-1]['value'])+d['unit'] for d in datasets]
 with fixture_server(base),sync_playwright() as p:
  browser=p.chromium.launch(args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1440,'height':1000},service_workers='block',has_touch=True,reduced_motion='reduce')
  context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else r.abort())
  context.add_init_script("localStorage.setItem('ph-consent-v1','essential')")
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base+'/',wait_until='networkidle')
  assert page.locator('.ph-data-home').count()==0
  page.goto(base+'/data/',wait_until='networkidle')
  page.wait_for_selector('.data-desk .data-bar')
  assert urlsplit(page.url).path=='/data/'
  assert page.locator('.data-desk .data-bar').count()==18
  assert page.locator('.data-desk .data-index strong').all_text_contents()==expected_values
  assert page.locator('link[rel=canonical]').get_attribute('href')=='https://www.politicshub.in/data/'
  for index,data in enumerate(datasets):
   chart_export(page,page.locator('.article-data').nth(index),[data['title'],data['source']['url'],data['source']['data_url'],data['source']['license'],data['source']['license_url'],data['source']['updated_on'],data['source']['retrieved_on'],data['note']],output/f'indicator-{index}.svg')
   with page.expect_download() as event:page.locator('.article-data a[download]').nth(index).click()
   values=list(csv.DictReader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
   assert [row['value'] for row in values]==[str(point['value']) for point in data['points']]
   assert all(row['licence_url']==data['source']['license_url'] and row['source_url']==data['source']['url'] for row in values)
  bar=page.locator('.data-bar').first
  bar.focus();assert page.locator('.article-data-tooltip').first.is_visible()
  page.keyboard.press('Escape');assert page.locator('.article-data-tooltip').first.is_hidden()
  bar.dispatch_event('pointerdown');assert page.locator('.article-data-tooltip').first.is_visible()
  for width in [320,390,768,1440]:
   page.set_viewport_size({'width':width,'height':1000})
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
   if width in [390,1440]:
    page.evaluate('document.activeElement.blur();scrollTo(0,0)')
    page.screenshot(path=str(output/f'data-desk-{width}.png'),full_page=True)
  page.locator('.data-desk-nav a').nth(1).click()
  assert page.url.endswith('#india-consumer-price-inflation-2019-2024')
  page.locator('.article-data-table summary').nth(1).click()
  assert str(datasets[1]['points'][-1]['value']) in page.locator('.article-data-table table').nth(1).inner_text()
  page.evaluate("document.documentElement.dataset.theme='dark'")
  page.locator('.article-data').nth(1).screenshot(path=str(output/'data-desk-dark.png'))
  plain=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':900})
  plain.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else r.abort())
  reader=plain.new_page();reader.goto(base+'/data/')
  assert reader.locator('.data-bar').count()==18
  assert reader.get_by_role('button',name='Download chart (SVG)',exact=True).count()==0
  with reader.expect_download() as event:reader.locator('.article-data a[download]').first.click()
  assert len(list(csv.DictReader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig')))))==6
  reader.locator('.article-data-table summary').first.click();assert reader.locator('table').first.is_visible()
  plain.close()
  assert not errors,errors
  browser.close()
 report={'passed':True,'checks':['standalone historical desk remains available without a homepage dashboard','three exact indicator series','keyboard, Escape and touch tooltip','320/390/768/1440 layouts','anchor navigation and precise tables','dark mode','no-JavaScript charts','all three CSV downloads retain exact observations and provenance; no-JS download works'],'chart_export':'all three static SVG downloads retain source URLs, licence, update/check dates and methodology; CSV/no-JS unchanged','browser_errors':errors}
 (output/'report.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('artifacts/data-desk'));args=parser.parse_args()
 run('http://127.0.0.1:8067',args.output)
