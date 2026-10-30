import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from api import index as api
from app.database import DatabaseUnavailable
from app.public_delivery import WindowLimiter, read_json_rows, remote_rows


class PublicDeliveryTests(unittest.TestCase):
    def test_newsletter_does_not_advertise_signup_when_storage_is_down(self):
        with patch.object(api,'mail_configured',return_value=True),patch.object(api,'db',side_effect=DatabaseUnavailable('private database error')):
            response=api.app.test_client().get('/api/newsletter')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['available'])
        self.assertTrue(response.json['delivery_configured'])
        self.assertFalse(response.json['storage_available'])
        self.assertNotIn('private database',response.get_data(as_text=True))

    def test_only_platform_forwarded_ips_are_trusted_in_vercel(self):
        headers={'X-Vercel-Forwarded-For':'203.0.113.20', 'X-Forwarded-For':'198.51.100.5'}
        with api.app.test_request_context('/', headers=headers, environ_base={'REMOTE_ADDR':'127.0.0.1'}):
            with patch.dict(os.environ, {'VERCEL':''}):
                self.assertEqual(api._public_rate_key(), '127.0.0.1')
            with patch.dict(os.environ, {'VERCEL':'1'}):
                self.assertEqual(api._public_rate_key(), '203.0.113.20')
        with api.app.test_request_context('/',headers={'X-Vercel-Forwarded-For':'invalid'}),patch.dict(os.environ, {'VERCEL':'1'}):
            self.assertEqual(api._public_rate_key(),'unknown')

    def test_busy_worker_does_not_mark_the_database_provider_down(self):
        from app.database import DatabaseBusy
        with api.app.test_request_context('/api/news'), patch.object(api,'_db_retry_after',0), \
             patch.object(api,'NewsDatabase',side_effect=DatabaseBusy('capacity')):
            with self.assertRaises(DatabaseBusy):api.db()
            self.assertEqual(api._db_retry_after,0)

    def test_limiter_is_atomic_and_has_a_strict_memory_bound(self):
        limiter = WindowLimiter(capacity=64)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: limiter.allow('same-client', 20, 60), range(200)))
        self.assertEqual(sum(results), 20)
        for i in range(10000):
            limiter.allow(str(i), 1, 60)
        self.assertEqual(len(limiter), 64)

    def test_limiter_recovers_at_the_window_boundary(self):
        now = [0.0]
        limiter = WindowLimiter(clock=lambda: now[0])
        self.assertTrue(limiter.allow('client', 1, 60))
        self.assertFalse(limiter.allow('client', 1, 60))
        now[0] = 60.0
        self.assertTrue(limiter.allow('client', 1, 60))

    def test_local_snapshot_cache_tracks_atomic_file_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'feed.json'
            path.write_text(json.dumps([{'title': 'Old report'}]))
            self.assertEqual(read_json_rows(path)[0]['title'], 'Old report')
            replacement = Path(temp) / 'replacement.json'
            replacement.write_text(json.dumps([{'title': 'New source report'}]))
            replacement.replace(path)
            self.assertEqual(read_json_rows(path)[0]['title'], 'New source report')
            path.write_text('invalid')
            self.assertEqual(read_json_rows(path), [])

    def test_concurrent_snapshot_reads_share_one_remote_refresh(self):
        started, finish = threading.Event(), threading.Event()
        cache = dict(until=0, payload=[{'title': 'Last good report'}])
        lock = threading.Lock()
        response = Mock(content=b'[]')
        response.json.return_value = [{'title': 'New report'}]

        def fetch(*args, **kwargs):
            started.set()
            self.assertTrue(finish.wait(3))
            return response

        def read():
            return remote_rows(cache, lock, [], ('https://example.org/feed',), ttl=90, max_bytes=1000)

        with patch('requests.get', side_effect=fetch) as get, ThreadPoolExecutor(max_workers=10) as pool:
            first = pool.submit(read)
            self.assertTrue(started.wait(3))
            others = list(pool.map(lambda _: read(), range(30)))
            self.assertTrue(all(rows[0]['title'] == 'Last good report' for rows in others))
            finish.set()
            self.assertEqual(first.result()[0]['title'], 'New report')
            self.assertEqual(read()[0]['title'], 'New report')
            self.assertEqual(get.call_count, 1)

    def test_failed_refresh_keeps_good_data_and_backs_off(self):
        cache = dict(until=0, payload=[{'title': 'Saved report'}])
        lock = threading.Lock()
        with patch('requests.get', side_effect=RuntimeError('unavailable')) as get:
            for _ in range(10):
                result = remote_rows(cache, lock, [], ('https://example.org/feed',), ttl=90, max_bytes=1000)
                self.assertEqual(result[0]['title'], 'Saved report')
            self.assertEqual(get.call_count, 1)

    def test_json_arrays_strings_and_malformed_bodies_are_rejected(self):
        client = api.app.test_client()
        for body in ('[]', '"value"', 'null', '{broken'):
            for path in ('/api/newsletter', '/api/admin/login'):
                response = client.post(path, data=body, content_type='application/json')
                self.assertEqual(response.status_code, 400)

    def test_authenticated_html_and_api_cannot_enter_shared_cache(self):
        client = api.app.test_client()
        with client.session_transaction() as session:
            session['admin_user'] = 'owner'
        for path in ('/sources.html', '/api/admin/me'):
            response = client.get(path)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertEqual(response.headers['Vercel-CDN-Cache-Control'], 'no-store')
            self.assertIn('Cookie', response.headers['Vary'])

    def test_public_etag_supports_revalidation(self):
        database = Mock()
        database.latest_public.return_value = []
        api._PUBLIC_RATE.clear()
        client = api.app.test_client()
        with patch.object(api, 'db', return_value=database):
            response = client.get('/api/news?limit=1')
            self.assertIn('ETag', response.headers)
            self.assertNotIn('Cookie',response.headers.get('Vary',''))
            self.assertNotIn('Set-Cookie',response.headers)
            again = client.get('/api/news?limit=1', headers={'If-None-Match': response.headers['ETag']})
            self.assertEqual(again.status_code, 304)
            self.assertFalse(again.data)

    def test_unchanged_anonymous_cookies_do_not_fragment_public_cache(self):
        database=Mock();database.latest_public.return_value=[]
        client=api.app.test_client()
        client.set_cookie('unrelated-preference','yes')
        api._PUBLIC_RATE.clear()
        with patch.object(api,'db',return_value=database):
            response=client.get('/api/news?limit=1')
        self.assertNotIn('Cookie',response.headers.get('Vary',''))
        self.assertIn('s-maxage=',response.headers['Cache-Control'])

    def test_missing_publication_time_is_not_invented_from_a_large_id(self):
        self.assertEqual(api._public_timestamp({'id':1000000000000001}),0)
        database=Mock()
        database.newest_public.return_value={'id':1000000000000001}
        with patch.object(api,'db',return_value=database):
            response=api.app.test_client().get('/api/health')
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.json['latest_published_at'])

    def test_unpublished_snapshot_and_unsafe_source_urls_stay_private(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(api.app, '_static_folder', temp):
            Path(temp, 'news-data.json').write_text(json.dumps([{'id': 1, 'title': 'Private draft', 'status': 'pending'}]))
            self.assertEqual(api._snapshot_rows(), [])
        for url in ('javascript:alert(1)', '//evil.example/report', 'https://user:password@example.org/report'):
            with api.app.test_request_context('/'):
                self.assertEqual(api._publicize({'id': 1, 'title': 'Public report', 'url': url})['url'], '')

    def test_snapshot_cards_omit_full_article_but_detail_keeps_it(self):
        row = dict(id=99, title='An important public services report', status='published',
                   bot_article='Full original source text. ' * 30, category='india', source_name='Example')
        api._PUBLIC_RATE.clear()
        with patch.object(api, 'db', side_effect=DatabaseUnavailable('down')), patch.object(api, '_snapshot_rows', return_value=[row]):
            client = api.app.test_client()
            cards = client.get('/api/news').json
            self.assertNotIn('article', cards[0])
            self.assertNotIn('bot_article', cards[0])
            self.assertIn('Full original source text', client.get('/api/news/99').json['article'])


if __name__ == '__main__':
    unittest.main()
