import os
import unittest
from unittest.mock import MagicMock, patch
from flask import Flask

from api import index as api
from scripts import termux_local_admin


class LocalAdminAccessTests(unittest.TestCase):
    def test_bridge_secret_survives_new_shell_using_existing_private_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp)/'.politicshub-admin-bridge.secret'
            legacy.write_text('private-existing-bridge-key-1234567890')
            legacy.chmod(0o600)
            with patch.object(termux_local_admin, 'HOME', Path(tmp)), \
                 patch.object(termux_local_admin, 'BRIDGE_SECRET_FILE', Path(tmp)/'new-secret'), \
                 patch.dict(os.environ, {'POLITICSHUB_ADMIN_BRIDGE_SECRET':'', 'POLITICSHUB_ADMIN_BRIDGE_SECRET_FILE':''}):
                self.assertTrue(termux_local_admin.load_bridge_secret())
                self.assertEqual(os.environ['POLITICSHUB_ADMIN_BRIDGE_SECRET'], legacy.read_text())

    def private_client(self, secret):
        fresh = Flask('private-phone-tests')
        fresh.get('/api/admin/me')(lambda: {'ok': True})
        with patch.object(api, 'app', fresh), patch.dict(os.environ, {'POLITICSHUB_ADMIN_BRIDGE_SECRET': secret}):
            termux_local_admin.configure_private_app()
        return fresh.test_client()

    def test_valid_bridge_signature_is_not_rejected_for_preserved_remote_address(self):
        from app.remote_admin_bridge import _REPLAY, bridge_headers
        _REPLAY.clear()
        secret = 'only-a-private-bridge-test-key-1234567890'
        client = self.private_client(secret)
        with patch.dict(os.environ, {'POLITICSHUB_ADMIN_BRIDGE_SECRET': secret}):
            response = client.get('/api/admin/me', base_url='https://phone.example.ts.net',
                headers=bridge_headers(secret, 'GET', '/api/admin/me', b''),
                environ_overrides={'REMOTE_ADDR': '198.51.100.12'})
        self.assertEqual(response.status_code, 200)

    def test_direct_loopback_still_works_with_bridge_configured(self):
        secret = 'only-a-private-bridge-test-key-1234567890'
        client = self.private_client(secret)
        with patch.dict(os.environ, {'POLITICSHUB_ADMIN_BRIDGE_SECRET': secret}):
            self.assertEqual(client.get('/api/admin/me', base_url='http://127.0.0.1:8765',
                environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code, 200)
            for peer, host in [('198.51.100.12', 'http://127.0.0.1:8765'),
                               ('127.0.0.1', 'https://phone.example.ts.net')]:
                self.assertEqual(client.get('/api/admin/me', base_url=host,
                    environ_overrides={'REMOTE_ADDR': peer}).status_code, 403)

    def test_reset_owner_updates_running_server_without_starting_duplicate(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [(8,), ('admin_users',), (1,)]
        with patch.object(termux_local_admin, '_listening', return_value=True), \
             patch('psycopg.connect') as connect, \
             patch('getpass.getpass', side_effect=['private-pg-password', 'new owner password', 'new owner password']), \
             patch.object(termux_local_admin, 'create_local_owner', return_value=True) as create, \
             patch.object(termux_local_admin.subprocess, 'run') as run, \
             patch.object(termux_local_admin.subprocess, 'Popen') as spawn:
            run.return_value.returncode = 0
            connect.return_value.__enter__.return_value = conn
            self.assertEqual(termux_local_admin.start(reset=True), 0)
        create.assert_called_once_with(conn, 'new owner password', reset=True)
        spawn.assert_not_called()

    def test_loopback_port_and_local_postgres_only(self):
        self.assertEqual(termux_local_admin.HOST, "127.0.0.1")
        self.assertEqual(termux_local_admin.PORT, 8765)
        self.assertIn("@127.0.0.1:5432/", termux_local_admin.LOCAL_DSN)
        self.assertIn("sslmode=disable", termux_local_admin.LOCAL_DSN)

    def test_local_owner_requires_strong_password(self):
        connection = MagicMock()
        with self.assertRaisesRegex(ValueError, "12"):
            termux_local_admin.create_local_owner(connection, "short")
        connection.execute.assert_not_called()

    def test_local_owner_preserves_existing_account(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = {"username": "localowner"}
        self.assertFalse(termux_local_admin.create_local_owner(connection, "a secure user password"))
        self.assertEqual(connection.execute.call_count, 2)

    def test_local_owner_created_with_hashed_password(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = None
        password = "my strong private password"
        self.assertTrue(termux_local_admin.create_local_owner(connection, password))
        sent = connection.execute.call_args.args[1]
        self.assertEqual(sent[0], "localowner")
        self.assertTrue(sent[1].startswith("scrypt:"))
        self.assertNotIn(password, sent[1])

    def test_approve_requires_explicit_editor_confirmation(self):
        with patch.dict(os.environ, {"POLITICSHUB_LOCAL_ADMIN": "1"}):
            client = api.app.test_client()
            with client.session_transaction() as session:
                session.update(admin_user="localowner", admin_role="owner",
                               admin_scope="owner", csrf_token="securecsrf")
            with patch.object(api, "db") as db:
                response = client.post("/api/news/455/approve",
                    json={"notes": "I checked the facts.", "evidence_urls": []},
                    headers={"X-CSRF-Token": "securecsrf"})
                self.assertEqual(response.status_code, 400)
                db.assert_not_called()

    def test_unapproved_story_cannot_be_published(self):
        record = {
            "id": 455, "status": "pending", "approved_at": None,
            "fact_check_status": "pending", "source_type": "rss",
            "public_source": True, "bot_article": "A" * 1100
        }
        db = MagicMock()
        db.get_by_id.return_value = record
        with patch.dict(os.environ, {"POLITICSHUB_LOCAL_ADMIN": "1"}):
            client = api.app.test_client()
            with client.session_transaction() as session:
                session.update(admin_user="localowner", admin_role="owner",
                               admin_scope="owner", csrf_token="securecsrf")
            with patch.object(api, "db", return_value=db):
                response = client.post("/api/news/455/publish",
                    json={}, headers={"X-CSRF-Token": "securecsrf"})
        self.assertEqual(response.status_code, 409)
        db.update.assert_not_called()
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
