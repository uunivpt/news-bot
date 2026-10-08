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
 def test_unavailable_public_snapshot_stays_503(self):
  response=Mock(status_code=404,content=b'')
  response.raise_for_status.side_effect=RuntimeError('not found')
  with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api.app,'_static_folder',self.tmp.name),patch('requests.get',return_value=response),patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   news=self.client.get('/api/news')
   self.assertEqual(news.status_code,503)

if __name__=='__main__':unittest.main()
