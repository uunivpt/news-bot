import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from api import index as api
from app.admin_access import configured_users
from app.admin_workspace import coverage, project_rows
from app.database import NewsDatabase, DatabaseUnavailable
from app.models import NewsItem


class AdminWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'isolated-fixture-owner-password'
        cls.verifier = generate_password_hash(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = NewsDatabase(str(Path(self.temp.name) / 'workspace.db'))
        self.config = patch.dict(os.environ, {'ADMIN_USERS_JSON':json.dumps({'fixture_owner':self.verifier})})
        self.config.start()
        api._ensure_admin_users(self.database)
        self.client = api.app.test_client()
        api._ADMIN_LOGIN_RATE.clear()
        api._PUBLIC_RATE.clear()
        self.snapshot = [{'id':90,'title':'Public report','url':'https://example.org/report','source_name':'Example',
                          'category':'india','status':'published','summary':'A public summary','bot_article':'Public body',
                          'published_at':'2026-10-30T12:00:00Z','fact_check_notes':'PRIVATE','fact_check_status':'reviewed'}]

    def tearDown(self):
        self.config.stop()
        self.database.close()
        self.temp.cleanup()

    def sign_in(self, password=None):
        return self.client.post('/api/admin/login',json={'username':'fixture_owner','password':password or self.password})

    def recovery(self):
        with patch.object(api,'db',side_effect=DatabaseUnavailable('unavailable')):
            response = self.sign_in()
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['read_only'])
        self.assertEqual(response.json['scope'],'recovery')
        return response.json

    def test_anonymous_workspace_is_private_and_requires_authentication(self):
        response = self.client.get('/api/admin/workspace')
        self.assertEqual(response.status_code,401)
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_valid_owner_gets_a_restricted_session_during_outage(self):
        data = self.recovery()
        with patch.object(api,'db',side_effect=DatabaseUnavailable('unavailable')),patch.object(api,'_snapshot_rows',return_value=self.snapshot):
            response = self.client.get('/api/admin/workspace')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['mode'],'snapshot')
        self.assertFalse(response.json['capabilities']['publish'])
        self.assertIsNone(response.json['stats']['pending'])
        self.assertIsNone(response.json['stories'][0]['fact_check_status'])
        self.assertNotIn('bot_article',response.json['stories'][0])
        self.assertNotIn('PRIVATE',response.get_data(as_text=True))
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertIn('no-store',response.headers['Vercel-CDN-Cache-Control'])
        self.assertEqual(self.client.get('/api/admin/me').json['expires_at'],data['expires_at'])

    def test_recovery_does_not_turn_wrong_credentials_into_a_success(self):
        with patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
            self.assertEqual(self.sign_in('wrong-fixture-password').status_code,401)
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])

    def test_recovery_cannot_read_private_queues_or_mutate_any_api(self):
        data = self.recovery()
        with patch.object(api,'db',side_effect=AssertionError('Recovery request must not reach the database')):
            for path in ['/api/admin/news','/api/admin/stories','/api/admin/operations','/api/admin/settings','/api/admin/activity']:
                self.assertEqual(self.client.get(path).status_code,403,path)
            for path in ['/api/admin/settings','/api/news/90/publish','/api/news/90/reject','/api/news/90/approve','/api/fact-check','/api/admin/training']:
                response = self.client.post(path,json={},headers={'X-CSRF-Token':data['csrf_token']})
                self.assertEqual(response.status_code,403,path)
                self.assertEqual(response.json['code'],'recovery_read_only')

    def test_recovery_stays_read_only_after_database_returns(self):
        self.recovery()
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'),patch.object(api,'_snapshot_rows',return_value=self.snapshot):
            response = self.client.get('/api/admin/workspace')
        self.assertTrue(response.json['health']['reauthenticate'])
        self.assertEqual(response.json['mode'],'snapshot')
        self.assertFalse(response.json['capabilities']['publish'])

    def test_recovery_logout_requires_csrf_and_clears_session(self):
        data = self.recovery()
        self.assertEqual(self.client.post('/api/admin/logout').status_code,403)
        self.assertEqual(self.client.post('/api/admin/logout',headers={'X-CSRF-Token':data['csrf_token']}).status_code,200)
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])

    def test_expired_session_is_rejected(self):
        self.recovery()
        with self.client.session_transaction() as session:
            session['admin_expires_at'] = int(time.time()) - 1
        self.assertEqual(self.client.get('/api/admin/workspace').status_code,401)

    def test_cross_origin_login_is_rejected_before_database_access(self):
        with patch.object(api,'db',side_effect=AssertionError('Do not touch database')):
            response = self.client.post('/api/admin/login',json={'username':'fixture_owner','password':self.password},headers={'Origin':'https://untrusted.example'})
        self.assertEqual(response.status_code,403)

    def test_vercel_tls_termination_accepts_the_same_https_host(self):
        with patch.dict(os.environ,{'VERCEL':'1'}),patch.object(api,'db',side_effect=DatabaseUnavailable('unavailable')):
            response=self.client.post('/api/admin/login',json={'username':'fixture_owner','password':self.password},headers={'Origin':'https://localhost'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['scope'],'recovery')

    def test_outage_attempts_are_bounded_without_persistent_storage(self):
        with patch.object(api,'db',side_effect=DatabaseUnavailable('down')):
            for _ in range(12):
                self.assertEqual(self.sign_in('wrong').status_code,401)
            self.assertEqual(self.sign_in().status_code,429)

    def test_healthy_database_does_not_accept_a_different_packaged_password(self):
        self.database.conn.execute('UPDATE admin_users SET password_hash=?',(generate_password_hash('changed-owner-password'),))
        self.database.conn.commit()
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'):
            self.assertEqual(self.sign_in().status_code,401)

    def test_live_queue_paginates_and_filters_database_records(self):
        for index in range(31):
            self.database.insert(NewsItem(source_name='Example',source_type='rss',title=f'Council report {index}',url=f'https://example.org/{index}',summary='A report',category='india',published_at='2026-10-30T10:00:00Z'))
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'):
            login = self.sign_in()
            self.assertEqual(login.json['scope'],'owner')
            first = self.client.get('/api/admin/stories?status=pending&search=Council&page=1').json
            second = self.client.get('/api/admin/stories?status=pending&search=Council&page=2').json
            self.assertEqual(first['total'],31)
            self.assertEqual(len(first['stories']),25)
            self.assertEqual(len(second['stories']),6)
            self.assertFalse(set(row['id'] for row in first['stories']) & set(row['id'] for row in second['stories']))
            self.assertEqual(self.client.get('/api/admin/stories?source=%27%20OR%201=1--').json['total'],0)
            self.assertEqual(self.client.get('/api/admin/stories?page=bad').status_code,400)
            workspace = self.client.get('/api/admin/workspace').json
        self.assertEqual(workspace['stats']['pending'],31)
        self.assertTrue(workspace['capabilities']['publish'])
        self.assertEqual(workspace['coverage']['sample_size'],31)

    def test_environment_can_disable_or_replace_the_packaged_identity(self):
        with patch.dict(os.environ,{'ADMIN_USERS_JSON':'{}'}):self.assertEqual(configured_users(),{})
        with patch.dict(os.environ,{'ADMIN_USERS_JSON':'invalid'}):self.assertEqual(configured_users(),{})

    def test_snapshot_projection_counts_real_flags_and_does_not_infer_verification(self):
        rows = project_rows(self.snapshot,snapshot=True,now=1793361600)
        self.assertIsNone(rows[0]['fact_check_status'])
        self.assertIn('No image',rows[0]['quality_flags'])
        self.assertTrue(rows[0]['article_available'])
        self.assertEqual(coverage(rows)['sources'],[{'name':'Example','count':1}])

    def test_editorial_revision_prevents_overwriting_a_newer_edit(self):
        self.database.insert(NewsItem(source_name='Example',source_type='rss',title='Original headline',url='https://example.org/edit',summary='Full summary '*200,category='india'))
        item_id=self.database.latest(1)[0]['id']
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'):
            signed=self.sign_in().json
            draft=self.client.get(f'/api/admin/story/{item_id}').json
            self.assertGreater(len(draft['summary']),1600)
            headers={'X-CSRF-Token':signed['csrf_token'],'If-Match':draft['revision']}
            first=self.client.post(f'/api/news/{item_id}/edit',json={'title':'First editor headline'},headers=headers)
            self.assertEqual(first.status_code,200)
            second=self.client.post(f'/api/news/{item_id}/edit',json={'title':'Stale editor headline'},headers=headers)
            self.assertEqual(second.status_code,409)
            self.assertEqual(self.database.get_by_id(item_id)['title'],'First editor headline')

    def test_missing_stories_and_invalid_editorial_desks_are_rejected(self):
        with patch.object(api,'db',return_value=self.database),patch.object(self.database,'close'):
            signed=self.sign_in().json
            headers={'X-CSRF-Token':signed['csrf_token']}
            self.assertEqual(self.client.post('/api/news/999999/publish',json={},headers=headers).status_code,404)
            self.assertEqual(self.client.post('/api/news/999999/edit',json={'title':'New title'},headers=headers).status_code,404)
            self.assertEqual(self.client.post('/api/news/999999/edit',json={'category':'unexpected'},headers=headers).status_code,400)


if __name__ == '__main__':unittest.main()
