import unittest
from unittest.mock import patch
from app.news_search import relevance,terms
from app.news_numbers import news_number
from app.official_exams import parse_notices
from app.library import counts
from api import index as api

class FullSearchTests(unittest.TestCase):
 def test_reordered_words_and_partial_headline_rank_above_one_word_matches(self):
  best={'id':1,'title':'Tom Hardy wears Vans to charity event','url':'https://example.org/1'}
  weak={'id':2,'title':'Charity donates food','url':'https://example.org/2'}
  self.assertGreater(relevance(best,'charity hardy vans'),relevance(weak,'charity hardy vans'))
  self.assertGreater(relevance(best,'charit hard'),0)
  self.assertEqual(relevance({'id':3,'title':'Sooryavanshi wins'},'vans'),0)
 def test_unicode_numbers_and_article_body_are_searchable(self):
  row={'id':55,'title':'महाराष्ट्र परीक्षा वेळापत्रक','bot_article':'शिष्यवृत्ती निकाल जाहीर','url':'https://example.org/55'}
  self.assertGreater(relevance(row,'निकाल शिष्यवृत्ती'),0)
  self.assertGreater(relevance(row,news_number(row)),0)
  self.assertFalse(terms('the and for'))
 def test_offline_api_searches_archived_body_and_preserves_pagination(self):
  rows=[{'id':100+i,'title':'Official scholarship examination announcement','url':f'https://example.org/{i}','summary':'A factual source-linked summary. '*4,'bot_article':'Maharashtra scholarship qualification details. '*20,'status':'published','source_type':'rss','source_name':'Example','public_source':True,'category':'india','published_at':'2026-10-01T00:00:00Z'} for i in range(61)]
  from app import public_archive
  with patch.object(public_archive,'_load',return_value=tuple(rows)),patch.object(api,'db',side_effect=RuntimeError('offline')),patch.object(api,'_snapshot_rows',return_value=[]),patch.object(api,'_hindi_rows',return_value=[]),patch.object(api,'_official_exam_rows',return_value=[]):
   c=api.app.test_client();first=c.get('/api/search?q=qualification%20scholarship&limit=50');second=c.get('/api/search?q=qualification%20scholarship&limit=50&offset=50')
   self.assertEqual(first.headers['X-Search-Total'],'61')
   self.assertEqual(len(first.json),50);self.assertEqual(len(second.json),11)
   self.assertFalse({r['id'] for r in first.json}&{r['id'] for r in second.json})
 def test_counts_deduplicate_current_archive_and_separate_official_notices(self):
  a={'id':1,'url':'https://example.org/a'};b={'id':2,'url':'https://example.org/b'};exam={'id':3,'url':'https://official.gov.in/notice.pdf','source_type':'official_exam'}
  result=counts([a,b,exam],[a],[],[exam])
  self.assertEqual(result['website_total'],3);self.assertEqual(result['news_articles'],2)
  self.assertEqual(result['archive_only'],1);self.assertEqual(result['homepage_feed'],1)
  self.assertEqual(result['official_exam_notices'],1);self.assertIsNone(result['google_indexed'])

class OfficialExamTests(unittest.TestCase):
 source={'id':'test','name':'Official Exam Board','url':'https://board.gov.in/','allowed_hosts':['board.gov.in'],'region':'maharashtra'}
 def test_only_official_notice_links_and_explicit_publication_dates(self):
  html='''<table><tr><td>02/11/2026</td><td>Scholarship examination application notice</td><td><a href="/notice.pdf">English</a></td></tr><tr><td>Exam result announcement for candidates</td><td><a href="https://fake.example/result.pdf">Download</a></td></tr><tr><td>Examination application deadline 31/12/2026</td><td><a href="/undated.pdf">Read</a></td></tr><tr><td>Quotation tender for examination room furniture</td><td><a href="/tender.pdf">Read</a></td></tr></table>'''
  rows=parse_notices(html,self.source)
  self.assertEqual(len(rows),2);self.assertTrue(rows[0]['published_at'].startswith('2026-11-02'))
  self.assertIsNone(rows[1]['published_at']);self.assertEqual(rows[0]['source_type'],'official_exam')
  self.assertEqual(rows[0]['url'],'https://board.gov.in/notice.pdf')
 def test_javascript_links_and_login_pages_are_not_fabricated_notices(self):
  self.assertEqual(parse_notices('<a href="javascript:alert(1)">Examination result announced</a><a href="https://board.gov.in/login">Examination application login</a>',self.source),[])

class ExamRefreshTests(unittest.TestCase):
 def test_failed_official_source_keeps_previous_notice_without_freshness_claim(self):
  import tempfile,json
  from pathlib import Path
  from scripts import refresh_official_exams as refresh
  from app.news_numbers import news_number
  row={'id':8000000000000001,'title':'Official examination result notice','url':'https://board.gov.in/result.pdf','source_name':'Official Board','source_type':'official_exam','public_source':True,'status':'published','exam_authority':'board','category':'india','published_at':'2026-10-01T00:00:00Z'}
  with tempfile.TemporaryDirectory() as directory:
   file=Path(directory)/'exams.json';file.write_text(json.dumps({'items':[row],'sources':[{'id':'board','last_success_at':'2026-10-01T00:00:00Z'}]}))
   with patch.object(refresh,'OUTPUT',file),patch.object(refresh,'PACKAGED_OUTPUT',Path(directory)/'packaged.json'),patch.object(refresh,'sources',return_value=[{'id':'board','name':'Official Board','enabled':True}]),patch.object(refresh,'fetch_notices',side_effect=TimeoutError()),patch.object(refresh,'retain_public_records'):
    refresh.main()
   result=json.loads(file.read_text());self.assertEqual(result['items'][0]['url'],row['url'])
   self.assertEqual(result['sources'][0]['status'],'unavailable')
   self.assertTrue(result['sources'][0]['stale'])
   self.assertEqual(result['sources'][0]['last_success_at'],'2026-10-01T00:00:00Z')
   self.assertEqual(result['items'][0]['news_number'],news_number(row))

class ExamPackagingTests(unittest.TestCase):
 def test_api_uses_packaged_notice_data_when_public_files_live_only_on_cdn(self):
  import tempfile,json
  from pathlib import Path
  from app import public_archive
  row={'id':8000000000000001,'title':'Official examination notice','url':'https://board.gov.in/notice.pdf','status':'published','public_source':True,'source_type':'official_exam'}
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'data').mkdir();(root/'data/official-exams.json').write_text(json.dumps({'items':[row],'sources':[{'id':'board'}]}))
   with patch.object(api.app,'_static_folder',str(root/'cdn-only-public')),patch.object(public_archive,'ARCHIVE_PATH',root/'data/public-archive.json.gz'):
    response=api.app.test_client().get('/api/exams')
    self.assertEqual(response.status_code,200)
    self.assertEqual(response.json['items'][0]['id'],row['id'])
    self.assertEqual(api._official_exam_rows()[0]['id'],row['id'])
