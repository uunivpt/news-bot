import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from api import index as api
from app.database import NewsDatabase
from app.phase_system import ensure_schema
from app.newsroom import dedupe_story_rows


class AdminDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.database=NewsDatabase(str(Path(self.temp.name)/'admin.db'))

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_hashed_environment_owner_bootstraps_only_an_empty_user_table(self):
        hashed=generate_password_hash('a-long-fixture-password')
        with patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps({'fixture_owner':hashed})}):
            api._ensure_admin_users(self.database)
        self.assertEqual(self.database.conn.execute('SELECT username FROM admin_users').fetchone()['username'],'fixture_owner')
        with patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps({'different_owner':hashed})}):
            api._ensure_admin_users(self.database)
        self.assertEqual(self.database.conn.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0],1)
        self.assertEqual(self.database.conn.execute('SELECT password_hash FROM admin_users').fetchone()[0],hashed)

    def test_environment_owner_bootstrap_rejects_plaintext_and_bad_usernames(self):
        for value in ({'owner':'plain-text-password'},{'bad name':generate_password_hash('long-password')},['invalid']):
            with patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps(value)}):
                api._ensure_admin_users(self.database)
        self.assertEqual(self.database.conn.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0],0)

    def test_dashboard_refresh_does_not_record_a_fake_completed_agent_run(self):
        ensure_schema(self.database)
        api.app.config['TESTING']=True
        client=api.app.test_client()
        with client.session_transaction() as session:
            session['admin_user']='fixture_owner'
        try:
            with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'), \
                 patch.object(api,'cluster_stories',side_effect=AssertionError('Dashboard must not rerun collection work')):
                first=client.get('/api/admin/operations')
                second=client.get('/api/admin/operations')
            self.assertEqual(first.status_code,200)
            self.assertEqual(second.status_code,200)
            self.assertEqual(self.database.conn.execute('SELECT COUNT(*) FROM ph_agent_runs').fetchone()[0],0)
            self.assertEqual(second.json['totals']['runs'],0)
        finally:
            api.app.config['TESTING']=False

    def test_phase_setup_does_not_repeat_schema_or_agent_updates(self):
        ensure_schema(self.database)
        statements=[]
        self.database.conn.set_trace_callback(statements.append)
        second=NewsDatabase(str(self.database.path))
        try:
            second.conn.set_trace_callback(statements.append)
            ensure_schema(second)
            ensure_schema(self.database)
        finally:
            second.close()
        self.assertFalse(any('ph_agents' in sql or 'CREATE TABLE' in sql for sql in statements))

    def test_deduplication_updates_cached_words_when_a_better_story_wins(self):
        rows=[{'id':1,'title':'Alpha beta gamma','news_score':1},
              {'id':2,'title':'Alpha beta delta','news_score':10},
              {'id':3,'title':'Alpha delta epsilon','news_score':20}]
        self.assertEqual([r['id'] for r in dedupe_story_rows(rows,threshold=.5)],[3])

    def test_settings_write_requires_the_current_session_csrf_token(self):
        client=api.app.test_client()
        with client.session_transaction() as session:
            session['admin_user']='fixture_owner';session['csrf_token']='fixture-csrf-token'
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'):
            self.assertEqual(client.post('/api/admin/settings',json={'website_enabled':False}).status_code,403)
            self.assertEqual(client.post('/api/admin/settings',json={'website_enabled':False},headers={'X-CSRF-Token':'wrong'}).status_code,403)
            response=client.post('/api/admin/settings',json={'website_enabled':False},headers={'X-CSRF-Token':'fixture-csrf-token'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.database.get_setting('website_enabled'),'false')


if __name__=='__main__':unittest.main()
