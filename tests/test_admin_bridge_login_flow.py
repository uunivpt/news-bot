"""Real phone auth/session/CSRF behind the signed gateway; no phone is contacted."""
import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from flask import Flask
from werkzeug.security import generate_password_hash
from api import index as api
from app.database import NewsDatabase
from app.remote_admin_bridge import _REPLAY, proxy_public_admin
from scripts.termux_local_admin import configure_private_app


class SignedPhoneLoginFlowTests(unittest.TestCase):
    def test_login_workspace_and_logout_across_non_loopback_signed_gateway(self):
        password = 'synthetic-phone-owner-password'
        secret = 'synthetic-private-admin-gateway-secret-123456789'
        environment = {'VERCEL':'', 'POLITICSHUB_LOCAL_ADMIN':'1',
                       'POLITICSHUB_ADMIN_BRIDGE_URL':'https://phone.fixture.ts.net',
                       'POLITICSHUB_ADMIN_BRIDGE_SECRET':secret,
                       'ADMIN_USERS_JSON':json.dumps({'fixture_owner':generate_password_hash(password)})}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, environment):
            path = str(Path(temp) / 'phone.db')
            database = NewsDatabase(path)
            api._ensure_admin_users(database)
            database.close()
            _REPLAY.clear(); api._ADMIN_LOGIN_RATE.clear(); api._PUBLIC_RATE.clear()
            phone = Flask('isolated-phone-auth')
            phone.secret_key = 'isolated-phone-session-signing-key'
            phone.before_request(api.enforce_admin_session_scope)
            phone.add_url_rule('/api/admin/login', view_func=api.login, methods=['POST'])
            phone.add_url_rule('/api/admin/me', view_func=api.me)
            phone.add_url_rule('/api/admin/workspace', view_func=api.admin_workspace)
            phone.add_url_rule('/api/admin/logout', view_func=api.logout, methods=['POST'])
            with patch.object(api, 'app', phone):
                configure_private_app()
            phone_client = phone.test_client(use_cookies=False)
            gateway = Flask('isolated-public-gateway')
            gateway.before_request(proxy_public_admin)

            def relay(req, timeout):
                target = urlsplit(req.full_url)
                path_query = target.path + ('?' + target.query if target.query else '')
                response = phone_client.open(path_query, method=req.get_method(), data=req.data,
                    base_url='https://phone.fixture.ts.net', headers=dict(req.header_items()),
                    environ_overrides={'REMOTE_ADDR':'198.51.100.12'})
                headers = Message()
                for key, value in response.headers:
                    headers.add_header(key, value)
                stream = io.BytesIO(response.data)
                return SimpleNamespace(status=response.status_code, headers=headers,
                                       read=stream.read, close=stream.close)

            with patch.object(api, 'db', side_effect=lambda: NewsDatabase(path)), \
                 patch('app.remote_admin_bridge.build_opener') as opener:
                opener.return_value.open.side_effect = relay
                browser = gateway.test_client()
                base = 'https://www.politicshub.in'
                self.assertFalse(browser.get('/api/admin/me', base_url=base).json['authenticated'])
                login = browser.post('/api/admin/login', base_url=base,
                    headers={'Origin':base}, json={'username':'fixture_owner','password':password})
                self.assertEqual(login.status_code, 200, login.data)
                self.assertIn('Secure', login.headers['Set-Cookie'])
                identity = browser.get('/api/admin/me', base_url=base)
                self.assertTrue(identity.json['authenticated'])
                self.assertEqual(identity.json['scope'], 'owner')
                workspace = browser.get('/api/admin/workspace', base_url=base)
                self.assertEqual(workspace.status_code, 200, workspace.data)
                self.assertFalse(workspace.json['access']['read_only'])
                self.assertEqual(workspace.json['health']['database'], 'connected')
                self.assertEqual(browser.post('/api/admin/logout', base_url=base,
                    headers={'Origin':base}).status_code, 403)
                logout = browser.post('/api/admin/logout', base_url=base,
                    headers={'Origin':base,'X-CSRF-Token':identity.json['csrf_token']})
                self.assertEqual(logout.status_code, 200, logout.data)
                self.assertIn('Max-Age=0', logout.headers['Set-Cookie'])
                self.assertFalse(browser.get('/api/admin/me', base_url=base).json['authenticated'])
