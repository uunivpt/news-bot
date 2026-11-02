import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from api import index as api
from app.database import DatabaseUnavailable

class PublicSnapshotRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.client=api.app.test_client()
  self.tmp=tempfile.TemporaryDirectory()
  api._snapshot_remote_cache.update(until=0.0,payload=[])
 def tearDown(self):
  self.tmp.cleanup()
  api._snapshot_remote_cache.update(until=0.0,payload=[])
 def test_serverless_snapshot_serves_news_and_articles(self):
  feed=[{'id':1,'title':'India news source report','summary':'Public source information','bot_article':'Published original source story','published_at':'2026-10-08T04:00:00Z','category':'india','source_name':'Example','url':'https://example.com/news'}]
  response=Mock(status_code=200,content=b'[]')
  response.raise_for_status.return_value=None
  response.json.return_value=feed
  with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api.app,'_static_folder',self.tmp.name),patch('requests.get',return_value=response) as get,patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   news=self.client.get('/api/news?category=india&limit=5')
   self.assertEqual(news.status_code,200)
   self.assertEqual(news.headers['X-News-Mode'],'snapshot')
   self.assertEqual(news.json[0]['title'],'India news source report')
   article=self.client.get('/api/news/1')
   self.assertEqual(article.status_code,200)
   self.assertIn('Published original source story',article.json['article'])
   self.assertEqual(get.call_count,1)
   self.assertEqual(get.call_args.args[0],api.PUBLIC_FEED_URL)
 def test_story_lookup_skips_other_feeds_when_first_snapshot_matches(self):
  with patch.object(api.public_archive, 'by_id', return_value=None), \
       patch.object(api, '_snapshot_rows', return_value=[{'id':42,'title':'Source story'}]) as snapshot, \
       patch.object(api, '_hindi_rows') as hindi, \
       patch.object(api, '_official_exam_rows') as exams:
   self.assertEqual(api._resolve_news_id(42), 42)
   snapshot.assert_called_once_with('all')
   hindi.assert_not_called()
   exams.assert_not_called()
 def test_serverless_prefers_fresh_feed_over_bundled_snapshot(self):
  import json
  from pathlib import Path
  Path(self.tmp.name,'news-data.json').write_text(json.dumps([{'id':1,'title':'Old bundled story'}]))
  response=Mock(content=b'[]')
  response.json.return_value=[{'id':2,'title':'Fresh production story'}]
  with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api.app,'_static_folder',self.tmp.name),patch('requests.get',return_value=response):
   self.assertEqual(api._snapshot_rows()[0]['id'],2)
 def test_failed_refresh_preserves_last_good_feed(self):
  api._snapshot_remote_cache.update(until=0,payload=[{'id':2,'title':'Last good story'}])
  with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api.app,'_static_folder',self.tmp.name),patch('requests.get',side_effect=RuntimeError('offline')):
   self.assertEqual(api._snapshot_rows()[0]['id'],2)
 def test_politics_view_includes_india_articles_without_changing_canonical_links(self):
  from pathlib import Path
  import json
  entries=[
   {"id":77,"title":"Three AAP MLAs join BJP in Punjab","category":"india",
    "status":"published","url":"https://example.org/political-report"},
   {"id":78,"title":"New hospital opens in district","category":"india",
    "status":"published","url":"https://example.org/health-report"}
  ]
  Path(self.tmp.name,'news-data.json').write_text(json.dumps(entries))
  with patch.dict(os.environ,{'VERCEL':''}),patch.object(api.app,'_static_folder',self.tmp.name),patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   response=self.client.get('/api/news?category=politics')
   self.assertEqual(response.status_code,200)
   self.assertEqual([row['id'] for row in response.json],[77])
   self.assertEqual(response.json[0]['category'],'india')
   self.assertTrue(api.article_path(entries[0]).startswith('/india/'))
   section=self.client.get('/politics/')
   self.assertEqual(section.status_code,200)
   rendered=section.get_data(as_text=True)
   self.assertIn('Three AAP MLAs join BJP',rendered)
   self.assertIn('<a href="/politics/">Politics<small>1</small>',rendered)
   self.assertIn('<a href="/india/">India<small>2</small>',rendered)
   self.assertIn('<a href="/maharashtra/">Maharashtra<small>—</small>',rendered)
   self.assertIn('<a href="/hindi/">Hindi<small>—</small>',rendered)
 def test_independent_hindi_article_api_matches_public_html_with_database_unavailable(self):
  hindi={'id':762,'title':'भारत में महत्वपूर्ण नई सरकारी घोषणा','summary':'मूल स्रोत से खबर.',
         'category':'hindi','status':'published','public_source':True,
         'url':'https://example.org/hindi-source'}
  with patch.object(api.public_archive,'by_id',return_value=None), \\
       patch.object(api,'_snapshot_rows',return_value=[]), \\
       patch.object(api,'_official_exam_rows',return_value=[]), \\
       patch.object(api,'_hindi_rows',return_value=[hindi]), \\
       patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   detail=self.client.get('/api/news/762')
   self.assertEqual(detail.status_code,200)
   self.assertEqual(detail.json['category'],'hindi')
   page=self.client.get('/hindi/'+api.news_number(hindi))
   self.assertEqual(page.status_code,200)
   self.assertIn(hindi['title'],page.get_data(as_text=True))

 def test_independent_hindi_article_api_works_with_healthy_database(self):
  hindi={'id':763,'title':'भारत में एक महत्वपूर्ण नई घोषणा','summary':'मूल स्रोत का सारांश.',
         'category':'hindi','status':'published','public_source':True,
         'url':'https://example.org/hindi-source-2'}
  database=Mock()
  database.get_by_id.return_value=None
  with patch.object(api.public_archive,'by_id',return_value=None), \\
       patch.object(api,'_snapshot_rows',return_value=[]), \\
       patch.object(api,'_official_exam_rows',return_value=[]), \\
       patch.object(api,'_hindi_rows',return_value=[hindi]), \\
       patch.object(api,'db',return_value=database):
   detail=self.client.get('/api/news/763')
   self.assertEqual(detail.status_code,200)
   self.assertEqual(detail.json['id'],763)
   database.close.assert_called()

 def test_missing_category_returns_empty_list_when_global_feed_is_healthy(self):
  def rows(category="all", search=None):
   return [{"id":12,"title":"Valid India public report","category":"india"}] if category=="all" else []
  with patch.object(api,'db',side_effect=DatabaseUnavailable('down')),patch.object(api,'_snapshot_rows',side_effect=rows):
   response=self.client.get('/api/news?category=politics')
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.json,[])
 def test_unavailable_public_snapshot_stays_503(self):
  response=Mock(status_code=404,content=b'')
  response.raise_for_status.side_effect=RuntimeError('not found')
  with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api.app,'_static_folder',self.tmp.name),patch('requests.get',return_value=response),patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   news=self.client.get('/api/news')
   self.assertEqual(news.status_code,503)

if __name__=='__main__':unittest.main()
