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

    def test_admin_workspace_and_paginated_queue_use_small_projections(self):
        client = api.app.test_client()
        api._PUBLIC_RATE.clear()
        with client.session_transaction() as session:
            session['admin_user'] = 'synthetic_audit_owner'
        with patch.object(api, 'db', return_value=self.database), patch.object(self.database, 'close'):
            workspace = client.get('/api/admin/workspace')
            first = client.get('/api/admin/stories?source=Audit%20source&page=1')
            second = client.get('/api/admin/stories?source=Audit%20source&page=2')
        self.assertEqual(workspace.status_code, 200)
        self.assertGreaterEqual(workspace.json['stats']['total'], 100000)
        self.assertLessEqual(len(workspace.json['stories']), 200)
        self.assertLess(len(workspace.data), 500000)
        self.assertTrue(workspace.json['capabilities']['publish'])
        self.assertEqual(workspace.json['source_inventory']['scope'], 'database')
        self.assertEqual(workspace.json['source_inventory']['total_stories'], 100000)
        inventory = {item['name']: item for item in workspace.json['source_inventory']['items']}
        self.assertEqual(inventory['Audit source']['story_count'], 100000)
        self.assertIn('TV9 Marathi - Maharashtra', inventory)
        self.assertIn('ABP Majha - Maharashtra', inventory)
        self.assertIn('The Hindu - India', inventory)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['total'], 100000)
        self.assertEqual(len(first.json['stories']), 25)
        self.assertFalse({row['id'] for row in first.json['stories']} & {row['id'] for row in second.json['stories']})
        self.assertTrue(all('bot_article' not in row for row in first.json['stories']))

    def test_staff_role_and_password_changes_persist_in_postgres(self):
        from werkzeug.security import generate_password_hash
        from app.diagnostics import diagnosis, diagnosis_pdf
        api._PUBLIC_RATE.clear();api._ADMIN_LOGIN_RATE.clear()
        database=self.database
        with patch.object(api,'db',return_value=database),patch.object(database,'close'):
            api._ensure_admin_users(database)
            database.conn.execute("INSERT INTO admin_users(username,password_hash,role,created_at) VALUES (%s,%s,'owner','2026-11-02T00:00:00Z') ON CONFLICT(username) DO UPDATE SET password_hash=EXCLUDED.password_hash,role='owner'",('pushkarthawari',generate_password_hash('isolated-pg-owner-password')))
            owner=api.app.test_client()
            login=owner.post('/api/admin/login',json={'username':'pushkarthawari','password':'isolated-pg-owner-password'})
            self.assertEqual(login.status_code,200)
            headers={'X-CSRF-Token':login.json['csrf_token']}
            created=owner.post('/api/admin/users',json={'username':'pg_fixture_staff','role':'publisher'},headers=headers)
            self.assertEqual(created.status_code,201,created.data)
            staff=api.app.test_client()
            self.assertEqual(staff.post('/api/admin/login',json={'username':'pg_fixture_staff','password':created.json['password']}).status_code,200)
            changed=owner.post('/api/admin/users/pg_fixture_staff',json={'operation':'role','role':'viewer'},headers=headers)
            self.assertEqual(changed.status_code,200)
            self.assertFalse(staff.get('/api/admin/workspace').json['capabilities']['publish'])
            reset=owner.post('/api/admin/users/pg_fixture_staff',json={'operation':'reset_password'},headers=headers)
            self.assertEqual(reset.status_code,200)
            self.assertEqual(staff.get('/api/admin/workspace').status_code,401)
            self.assertEqual(staff.post('/api/admin/login',json={'username':'pg_fixture_staff','password':reset.json['password']}).status_code,200)
            report=diagnosis(database,actor='PostgreSQL integration fixture')
            self.assertEqual(report['sources']['total_stories'],100000)
            self.assertTrue(diagnosis_pdf(report).startswith(b'%PDF-'))
            database.conn.execute("DELETE FROM admin_users WHERE username IN ('pushkarthawari','pg_fixture_staff')")

    def test_editorial_studio_scopes_claims_and_public_updates_use_real_postgres(self):
        from werkzeug.security import generate_password_hash
        from app.models import NewsItem
        database=self.database
        api._PUBLIC_RATE.clear();api._ADMIN_LOGIN_RATE.clear()
        with patch.object(api,'db',return_value=database),patch.object(database,'close'):
            api._ensure_admin_users(database)
            for name in ('pushkarthawari','pg_editorial_staff'):
                database.conn.execute("INSERT INTO admin_users(username,password_hash,role,created_at) VALUES (%s,%s,'owner','2026-11-02T00:00:00Z') ON CONFLICT(username) DO UPDATE SET password_hash=EXCLUDED.password_hash",(name,generate_password_hash('isolated-editorial-pg-password')))
            database.conn.execute("SELECT setval(pg_get_serial_sequence('news_items','id'),(SELECT MAX(id) FROM news_items))")
            database.insert(NewsItem('PostgreSQL editorial fixture','rss','मराठी बातमी नवीन पाणी पुरवठ्याची अधिकृत माहिती','https://example.org/pg-editorial-fixture',summary='प्रशासनाने पाणी पुरवठ्याबाबत नवीन माहिती प्रसिद्ध केली आहे.',category='maharashtra',public_source=True))
            sid=database.conn.execute("SELECT id FROM news_items WHERE url='https://example.org/pg-editorial-fixture'").fetchone()['id']
            owner=api.app.test_client();login=owner.post('/api/admin/login',json={'username':'pushkarthawari','password':'isolated-editorial-pg-password'});headers={'X-CSRF-Token':login.json['csrf_token']}
            def post(path,body):return owner.post(path,json=body,headers=headers)
            group=post('/api/admin/editorial/events',{'title':'PostgreSQL event fixture','story_ids':[sid]});self.assertEqual(group.status_code,201,group.data)
            studio=owner.get(f'/api/admin/studio/{sid}').json
            saved=post(f'/api/admin/studio/{sid}/save',{'revision':studio['revision'],'title':'मराठी संपादकीय माहिती पाणी पुरवठ्याच्या वेळापत्रकाची नोंद','summary':'अधिकृत माहितीचा संदर्भ आणि पाणी पुरवठ्याची नोंद.','article':'स्रोतांनुसार उपलब्ध असलेली अधिकृत माहिती वाचकांसाठी येथे नोंदवली आहे. '*20,'category':'maharashtra'})
            self.assertEqual(saved.status_code,200,saved.data)
            claim=post(f'/api/admin/editorial/story/{sid}/claims',{'statement':'पाणी पुरवठ्याची माहिती उपलब्ध आहे.'});self.assertEqual(claim.status_code,201)
            evidence=post(f'/api/admin/editorial/story/{sid}/claims/{claim.json["id"]}',{'source_url':'https://example.org/official','publisher':'Official fixture','excerpt':'पाणी पुरवठ्याची माहिती उपलब्ध आहे.','stance':'supports','assessment':'supported'});self.assertEqual(evidence.status_code,200,evidence.data)
            self.assertEqual(post(f'/api/admin/editorial/story/{sid}/assign',{'username':'pg_editorial_staff'}).status_code,200)
            self.assertEqual(post('/api/admin/users/pg_editorial_staff',{'operation':'policy','permissions':['news.read','news.edit'],'categories':['maharashtra'],'own_only':True}).status_code,200)
            staff=api.app.test_client();staff.post('/api/admin/login',json={'username':'pg_editorial_staff','password':'isolated-editorial-pg-password'})
            self.assertEqual(staff.get('/api/admin/workspace').json['stats']['total'],1)
            self.assertEqual(staff.get('/api/admin/studio/99999').status_code,403)
            self.assertEqual(post(f'/api/news/{sid}/approve',{}).status_code,200)
            studio=owner.get(f'/api/admin/studio/{sid}').json
            proposal=post(f'/api/admin/editorial/story/{sid}/updates',{'revision':studio['revision'],'label':'नवीन अधिकृत माहिती','body':'पाणी पुरवठ्याबाबत नवीन अधिकृत माहिती उपलब्ध झाली.','kind':'update','source_url':'https://example.org/new-official'});self.assertEqual(proposal.status_code,201)
            published=post(f'/api/admin/editorial/story/{sid}/updates/{proposal.json["id"]}/publish',{});self.assertEqual(published.status_code,200,published.data)
            self.assertIn('Update —',database.get_by_id(sid)['bot_article'])
            database.conn.execute('DELETE FROM news_items WHERE id=%s',(sid,))
            database.conn.execute("DELETE FROM admin_users WHERE username IN ('pushkarthawari','pg_editorial_staff')")


if __name__ == '__main__':
    unittest.main()
