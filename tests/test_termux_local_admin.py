import os
import unittest
from unittest.mock import MagicMock, patch

from api import index as api
from scripts import termux_local_admin


class LocalAdminAccessTests(unittest.TestCase):
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
