import unittest
from unittest.mock import MagicMock, patch
from api.index import app


class PrivateArticleAdminTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_private_draft_never_returns_to_public_visitor(self):
        with patch("api.index.db") as factory:
            response = self.client.get("/api/admin/story/445/article")
            self.assertEqual(response.status_code, 401)
            factory.assert_not_called()

    def test_authenticated_owner_sees_full_draft_not_snapshot(self):
        private = "Original editable editorial manuscript. " * 40
        with self.client.session_transaction() as sess:
            sess.update(admin_user="localowner", admin_role="owner",
                        admin_scope="owner", csrf_token="test")
        local = MagicMock()
        local.get_by_id.return_value = {
            "id": 445, "status": "pending", "bot_article": private,
        }
        with patch("api.index.db", return_value=local):
            response = self.client.get("/api/admin/story/445/article")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["article"], private)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        local.close.assert_called_once()

    def test_missing_story_is_404(self):
        with self.client.session_transaction() as sess:
            sess.update(admin_user="localowner", admin_role="owner",
                        admin_scope="owner", csrf_token="test")
        local = MagicMock()
        local.get_by_id.return_value = None
        with patch("api.index.db", return_value=local):
            response = self.client.get("/api/admin/story/404/article")
        self.assertEqual(response.status_code, 404)
        local.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
