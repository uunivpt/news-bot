"""Real PostgreSQL checks, enabled explicitly for CI/local integration testing."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from unittest.mock import patch

import psycopg
from api import index as api
from app.database import NewsDatabase, DatabaseBusy

URL = os.getenv('TEST_POSTGRES_URL', '')


@unittest.skipUnless(URL, 'TEST_POSTGRES_URL is not configured')
class PostgresDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These are synthetic fixtures, never application or production rows.
        if urlsplit(URL).hostname not in {'localhost', '127.0.0.1', 'postgres'}:
            raise RuntimeError('Integration fixtures require a local PostgreSQL server')
        cls.database = NewsDatabase(database_url=URL, connect_attempts=1)
        cls.database.conn.execute("""
            INSERT INTO news_items (id,source_name,source_type,title,url,normalized_url,
              url_hash,title_hash,collected_at,published_at,category,status,summary)
            SELECT n,'Audit source','rss','Synthetic public audit report '||n,
              'https://example.org/audit/'||n,'https://example.org/audit/'||n,
              md5('audit-url-'||n),md5('audit-title-'||n),
              '2026-10-30T04:00:00+00:00','2026-10-30T04:00:00+00:00',
              CASE WHEN n%2=0 THEN 'india' ELSE 'world' END,
              CASE WHEN n%10=0 THEN 'pending' ELSE 'published' END,'Audit fixture'
            FROM generate_series(1,100000) AS n ON CONFLICT DO NOTHING
        """)
        cls.database.conn.execute('ANALYZE news_items')

    @classmethod
    def tearDownClass(cls):
        cls.database.close()
        from app.web_database_pool import close_pools
        close_pools()

    def test_public_list_and_archive_identity_lookup_use_indexes(self):
        for sql in (
            "SELECT id,title FROM news_items WHERE status='published' AND category='india' ORDER BY id DESC LIMIT 50",
            "SELECT id,url,status FROM news_items WHERE id IN (99999) OR url IN ('https://example.org/audit/99990')",
        ):
            plan = self.database.conn.execute('EXPLAIN (FORMAT JSON) ' + sql).fetchone()['QUERY PLAN']
            encoded = json.dumps(plan)
            self.assertIn('Index', encoded)
            self.assertNotIn('Seq Scan', encoded)
        rows = self.database.archive_overrides([{'id': 99999, 'url': 'https://example.org/audit/99990'}])
        self.assertEqual({row['id'] for row in rows}, {99999, 99990})
        self.assertEqual(next(row['status'] for row in rows if row['id'] == 99990), 'pending')

    def test_web_connections_are_reused_and_bounded_under_concurrency(self):
        def read(_):
            database = NewsDatabase(database_url=URL, use_pool=True, initialize_schema=False,
                                    connect_timeout=3, statement_timeout=5000)
            try:
                return database.conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
            finally:
                database.close()
                database.close()  # Repeated cleanup must not return a lease twice.
        with ThreadPoolExecutor(max_workers=12) as pool:
            backend_ids = list(pool.map(read, range(100)))
        self.assertLessEqual(len(set(backend_ids)), 4)

    def test_pool_saturation_has_a_bounded_wait_and_recovers(self):
        from app.web_database_pool import get_pool
        pool = get_pool(URL, 3, 5000)
        leases = [pool.getconn() for _ in range(4)]
        try:
            with self.assertRaises(DatabaseBusy):
                NewsDatabase(database_url=URL, use_pool=True, initialize_schema=False,
                             connect_timeout=3, statement_timeout=5000)
        finally:
            for connection in leases:
                pool.putconn(connection)
        connection = pool.getconn()
        pool.putconn(connection)

    def test_query_deadline_is_enforced_by_postgres(self):
        database = NewsDatabase(database_url=URL, initialize_schema=False,
                                connect_attempts=1, statement_timeout=50)
        try:
            with self.assertRaises(psycopg.errors.QueryCanceled):
                database.conn.execute('SELECT pg_sleep(0.2)')
            self.assertEqual(database.conn.execute('SELECT 1 AS ok').fetchone()['ok'], 1)
        finally:
            database.close()

    def test_query_failures_return_safe_retryable_http_response(self):
        api._PUBLIC_RATE.clear()
        with patch.object(api, 'db', return_value=self.database), \
             patch.object(self.database, 'latest_public', side_effect=psycopg.errors.QueryCanceled('private SQL statement')), \
             patch.object(self.database, 'close'):
            response = api.app.test_client().get('/api/news')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['Retry-After'], '30')
        self.assertNotIn('private SQL', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
