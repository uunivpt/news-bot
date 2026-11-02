import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash, check_password_hash
from api import index as api
from app.database import NewsDatabase
from app.models import NewsItem
from app.admin_roles import ROLES


class AdminTeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'isolated-owner-fixture-password'
        cls.verifier = generate_password_hash(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.temp.name)/'team.db'))
        self.env = patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps({'pushkarthawari':self.verifier,'other_admin':self.verifier})})
        self.env.start(); api._ensure_admin_users(self.db)
        self.factory = patch.object(api,'db',return_value=self.db);self.factory.start()
        self.closer = patch.object(self.db,'close');self.closer.start()
        api._ADMIN_LOGIN_RATE.clear();api._PUBLIC_RATE.clear()
        self.owner = api.app.test_client();self.owner_headers = self.login(self.owner,'pushkarthawari',self.password)

    def tearDown(self):
        self.closer.stop();self.factory.stop();self.env.stop();self.db.close();self.temp.cleanup()

    def login(self,client,name,password):
        result=client.post('/api/admin/login',json={'username':name,'password':password})
        self.assertEqual(result.status_code,200,result.data)
        return {'X-CSRF-Token':result.json['csrf_token']}

    def hire(self,role='viewer',username='staff_member'):
        response=self.owner.post('/api/admin/users',json={'username':username,'role':role},headers=self.owner_headers)
        self.assertEqual(response.status_code,201,response.data)
        return response.json

    def test_only_named_primary_owner_can_hire_and_legacy_owners_are_lower(self):
        directory=self.owner.get('/api/admin/users')
        self.assertEqual(directory.status_code,200)
        users={u['username']:u for u in directory.json['users']}
        self.assertEqual(users['pushkarthawari']['role'],'owner')
        self.assertTrue(users['pushkarthawari']['protected'])
        self.assertEqual(users['other_admin']['role'],'administrator')
        other=api.app.test_client();headers=self.login(other,'other_admin',self.password)
        self.assertEqual(other.get('/api/admin/users').status_code,403)
        self.assertEqual(other.post('/api/admin/users',json={'role':'viewer'},headers=headers).status_code,403)
        self.assertNotIn('password_hash',directory.get_data(as_text=True))

    def test_generated_credentials_are_hashed_unique_and_never_listed_or_audited(self):
        created=self.hire('editor',username='')
        self.assertTrue(created['username'].startswith('staff_'))
        self.assertGreaterEqual(len(created['password']),20)
        row=self.db.conn.execute('SELECT password_hash FROM admin_users WHERE username=?',(created['username'],)).fetchone()
        self.assertNotEqual(row['password_hash'],created['password'])
        self.assertTrue(check_password_hash(row['password_hash'],created['password']))
        self.assertNotIn(created['password'],self.owner.get('/api/admin/users').get_data(as_text=True))
        self.assertNotIn(created['password'],str([dict(r) for r in self.db.recent_activity()]))
        self.assertIn('no-store',self.owner.get('/api/admin/users').headers['Cache-Control'])

    def test_csrf_reserved_owner_and_escalation_are_blocked(self):
        self.assertEqual(self.owner.post('/api/admin/users',json={'role':'viewer'}).status_code,403)
        self.assertEqual(self.owner.post('/api/admin/users',json={'username':'PUSHKARTHAWARI','role':'viewer'},headers=self.owner_headers).status_code,400)
        self.assertEqual(self.owner.post('/api/admin/users',json={'username':'new_staff','role':'owner'},headers=self.owner_headers).status_code,400)
        self.assertEqual(self.owner.post('/api/admin/users/pushkarthawari',json={'operation':'disable'},headers=self.owner_headers).status_code,403)
        self.hire();self.assertEqual(self.owner.post('/api/admin/users',json={'username':'staff_member','role':'analyst'},headers=self.owner_headers).status_code,409)

    def test_role_changes_apply_to_existing_sessions_and_disabled_accounts_cannot_login(self):
        created=self.hire('publisher');staff=api.app.test_client();headers=self.login(staff,created['username'],created['password'])
        self.assertTrue(staff.get('/api/admin/workspace').json['capabilities']['publish'])
        response=self.owner.post('/api/admin/users/staff_member',json={'operation':'role','role':'viewer'},headers=self.owner_headers)
        self.assertEqual(response.status_code,200)
        workspace=staff.get('/api/admin/workspace').json
        self.assertFalse(workspace['capabilities']['publish'])
        for path in ('/api/admin/users','/api/admin/settings','/api/admin/diagnostics.pdf','/api/admin/activity','/api/admin/dashboard'):
            self.assertEqual(staff.get(path).status_code,403,path)
        for path in ('/api/news/1/approve','/api/news/1/edit','/api/admin/news/create','/api/admin/training'):
            self.assertEqual(staff.post(path,json={},headers=headers).status_code,403,path)
        self.owner.post('/api/admin/users/staff_member',json={'operation':'disable'},headers=self.owner_headers)
        self.assertEqual(staff.get('/api/admin/workspace').status_code,401)
        self.assertEqual(staff.post('/api/admin/login',json={'username':'staff_member','password':created['password']}).status_code,401)

    def test_reset_revokes_previous_session_and_new_password_works(self):
        created=self.hire();staff=api.app.test_client();self.login(staff,created['username'],created['password'])
        reset=self.owner.post('/api/admin/users/staff_member',json={'operation':'reset_password'},headers=self.owner_headers)
        self.assertEqual(reset.status_code,200)
        self.assertNotEqual(reset.json['password'],created['password'])
        self.assertEqual(staff.get('/api/news/1').status_code,401)
        self.login(staff,created['username'],reset.json['password'])
        self.assertEqual(staff.get('/api/admin/workspace').status_code,200)

    def test_all_job_roles_have_expected_server_permissions(self):
        for role,(_,powers) in ROLES.items():
            created=self.hire(role,username='test_'+role)
            client=api.app.test_client();headers=self.login(client,created['username'],created['password'])
            workspace=client.get('/api/admin/workspace').json
            self.assertEqual(set(workspace['access']['permissions']),powers)
            self.assertEqual(client.post('/api/admin/settings',json={'website_enabled':False},headers=headers).status_code,200 if 'settings.manage' in powers else 403)
            self.assertEqual(client.get('/api/admin/users').status_code,403)

    def test_diagnosis_is_fresh_complete_scoped_pdf_and_does_not_mutate(self):
        self.db.insert(NewsItem('Fixture publisher','rss','Fixture news','https://example.org/report',summary='Source summary'))
        before=self.db.conn.total_changes
        response=self.owner.get('/api/admin/diagnostics')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.json['sources']['total_stories'],1)
        names={s['name'] for s in response.json['sources']['items']}
        self.assertTrue({'TV9 Marathi - Maharashtra','ABP Majha - Maharashtra','The Hindu - India'}.issubset(names))
        self.assertEqual(self.db.conn.total_changes,before)
        self.db.insert(NewsItem('Another publisher','rss','Another news','https://example.org/new',summary='New summary'))
        second=self.owner.get('/api/admin/diagnostics').json
        self.assertEqual(second['sources']['total_stories'],2)
        self.assertNotEqual(second['generated_at'],response.json['generated_at'])
        pdf=self.owner.get('/api/admin/diagnostics.pdf')
        self.assertEqual(pdf.status_code,200,pdf.data[:200])
        self.assertTrue(pdf.data.startswith(b'%PDF-'))
        self.assertEqual(pdf.mimetype,'application/pdf')
        self.assertIn('attachment',pdf.headers['Content-Disposition'])
        self.assertNotIn(self.verifier.encode(),pdf.data)
        self.assertNotIn('password_hash',json.dumps(response.json))
        self.assertGreater(len(pdf.data), 5000)
