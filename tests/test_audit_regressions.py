import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import psycopg
from app.database import NewsDatabase, DatabaseUnavailable
from app.collector import _source_due
from app.rss import collect_rss
from app.models import NewsItem
from api import index as api


class AuditRegressions(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.database=NewsDatabase(str(Path(self.tmp.name)/'test.db'))
  api._PUBLIC_RATE.clear()
  api._db_retry_after=0
  self.client=api.app.test_client()
 def tearDown(self):
  self.database.close()
  self.tmp.cleanup()
  api._db_retry_after=0
 def test_collector_schedule_persists(self):
  self.database.set_settings({'collector_last:rss:Example':NewsItem.now_iso()})
  self.assertFalse(_source_due(self.database,'rss',{'name':'Example','check_every_minutes':60}))
 def test_unknown_admin_setting_is_rejected(self):
  self.database.set_settings({'unexpected':'yes'})
  self.assertNotIn('unexpected',self.database.get_settings())
 def test_quota_failure_is_not_retried_or_leaked(self):
  with patch('psycopg.connect',side_effect=psycopg.OperationalError('secret-host: Your account or project has exceeded the quota.')) as connect:
   with self.assertRaises(DatabaseUnavailable) as caught:
    NewsDatabase(database_url='postgresql://u:p@host/db')
  self.assertEqual(connect.call_count,1)
  self.assertNotIn('secret-host',str(caught.exception))
 def test_api_connection_circuit_breaker(self):
  with api.app.test_request_context('/api/news'),patch.object(api,'NewsDatabase',side_effect=DatabaseUnavailable('down')) as connect:
   for _ in range(2):
    with self.assertRaises(DatabaseUnavailable):api.db()
   self.assertEqual(connect.call_count,1)
 def test_snapshot_outage_is_visible_and_not_cached(self):
  with patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   response=self.client.get('/api/news')
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.headers['X-News-Mode'],'snapshot')
   self.assertEqual(response.headers['Cache-Control'],'no-store')
   health=self.client.get('/api/health')
   self.assertEqual(health.status_code,503)
   self.assertFalse(health.json['ok'])
 def test_missing_runtime_snapshot_returns_unavailable(self):
  with patch.object(api,'db',side_effect=DatabaseUnavailable('down')),patch.object(api.app,'_static_folder',self.tmp.name):
   response=self.client.get('/api/news')
  self.assertEqual(response.status_code,503)
 def test_empty_healthy_database_does_not_resurrect_snapshot(self):
  database=Mock()
  database.latest.return_value=[]
  with patch.object(api,'db',return_value=database):
   response=self.client.get('/api/news')
  self.assertEqual(response.json,[])
 def test_snapshot_article_survives_outage(self):
  rows=api._snapshot_rows()
  self.assertTrue(rows)
  with patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
   response=self.client.get('/api/news/'+str(rows[0]['id']))
  self.assertEqual(response.status_code,200)
 def test_image_cache_policy_is_preserved(self):
  with api.app.test_request_context('/api/image/1'):
   response=api.Response(b'img',headers={'Cache-Control':'public, max-age=86400'})
   self.assertEqual(api.security_headers(response).headers['Cache-Control'],'public, max-age=86400')
 def test_article_uses_standalone_script_and_safe_json(self):
  with api.app.test_request_context('/'):
   page=api._article_html({'id':1,'title':'</script><script>alert(1)</script>','category':'india'})
  self.assertIn('/assets/story-page.js',page)
  self.assertNotIn('/assets/site.js',page)
  self.assertNotIn('</script><script>alert(1)</script>',page)
 def test_rss_publication_timestamp_keeps_timezone(self):
  self.assertEqual(api._public_timestamp({'published_at':'Wed, 07 Oct 2026 10:00:00 +0530'}), api._public_timestamp({'published_at':'2026-10-07T04:30:00Z'}))
 def test_healthy_missing_story_does_not_use_snapshot(self):
  database=Mock();database.get_by_id.return_value=None
  with patch.object(api,'db',return_value=database),api.app.test_request_context('/'):
   self.assertIsNone(api._public_row_by_id(api._snapshot_rows()[0]['id']))
 def test_rate_limits_are_independent_per_endpoint(self):
  with api.app.test_request_context('/api/newsletter',method='POST'):
   self.assertTrue(api._public_rate_allowed(1,3600))
   self.assertFalse(api._public_rate_allowed(1,3600))
  with api.app.test_request_context('/api/news'):
   self.assertTrue(api._public_rate_allowed())
 def test_malformed_feed_fails_source_check(self):
  response=Mock(content=b'<html>not a feed</html>')
  with patch('app.rss.requests.get',return_value=response):
   with self.assertRaises(ValueError):collect_rss({'name':'broken','url':'https://example.com'})

if __name__=='__main__':unittest.main()
