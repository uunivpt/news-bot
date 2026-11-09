"""Hosted owners get full powers after password authentication, never recovery."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from api import index as api
from app.admin_roles import ALL
from app.database import NewsDatabase, DatabaseUnavailable


class HostedOwnerAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'owner.db')
        self.password='isolated-owner-access-password'
        env=patch.dict(os.environ,{'VERCEL':'','DATABASE_3URL':'','DATABASE_URL':'',
            'POLITICSHUB_ADMIN_BACKEND':'hosted','ADMIN_USERS_JSON':json.dumps({
                'pushkarthawari':generate_password_hash(self.password)})})
        env.start();self.addCleanup(env.stop)
        def database():
            db=NewsDatabase(self.path)
            api._ensure_admin_users(db)
            return db
        factory=patch.object(api,'db',side_effect=database)
        factory.start();self.addCleanup(factory.stop)
        api._ADMIN_LOGIN_RATE.clear();api._PUBLIC_RATE.clear()
        self.client=api.app.test_client()

    def recovery(self):
        with self.client.session_transaction() as session:
            session.update(admin_user='pushkarthawari',admin_role='recovery',
                           admin_scope='recovery',csrf_token='old-token')

    def test_stale_recovery_requires_fresh_login_then_owner_has_every_permission(self):
        self.recovery()
        stale=self.client.get('/api/admin/workspace')
        self.assertEqual(stale.status_code,401)
        self.assertEqual(stale.json['code'],'reauthenticate')
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])
        result=self.client.post('/api/admin/login',json={
            'username':'pushkarthawari','password':self.password})
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json['read_only'])
        identity=self.client.get('/api/admin/me').json
        self.assertEqual(identity['role'],'owner')
        self.assertEqual(set(identity['permissions']),ALL)
        workspace=self.client.get('/api/admin/workspace').json
        self.assertFalse(workspace['access']['read_only'])
        self.assertTrue(workspace['capabilities']['publish'])
        self.assertEqual(self.client.get('/api/admin/users').status_code,200)

    def test_identity_probe_expires_recovery_without_granting_owner_access(self):
        self.recovery()
        result=self.client.get('/api/admin/me')
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json['authenticated'])
        self.assertEqual(self.client.get('/api/admin/users').status_code,401)

    def test_database_failure_does_not_issue_a_new_read_only_login(self):
        with patch.object(api,'db',side_effect=DatabaseUnavailable('fixture outage')):
            result=self.client.post('/api/admin/login',json={
                'username':'pushkarthawari','password':self.password})
        self.assertEqual(result.status_code,503)
        self.assertEqual(result.json['code'],'admin_storage_unavailable')
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])

    def test_legacy_owner_cookie_requires_fresh_login_for_hiring_permissions(self):
        with self.client.session_transaction() as session:
            session.update(admin_user='pushkarthawari',admin_role='owner',
                           admin_scope='owner',csrf_token='legacy-token')
        result=self.client.get('/api/admin/users')
        self.assertEqual(result.status_code,401)
        self.assertEqual(result.json['code'],'reauthenticate')
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])
