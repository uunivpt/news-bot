import unittest
from unittest.mock import patch
from api.index import app


class ManualArticleTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.valid = {
            "title": "An original independently sourced article about a public policy announcement",
            "summary": "An editorial summary of what happened, why the decision matters and how the original document supports it.",
            "article": "This is a detailed original editorial account with dates, context and source analysis. " * 12,
            "category": "india",
            "source_name": "PoliticsHub Editorial",
            "source_url": "https://example.org/public/notice",
            "image_url": "",
        }

    def test_anonymous_creation_rejected(self):
        with patch("api.index.db") as db:
            response = self.client.post("/api/admin/news/create", json=self.valid)
            self.assertEqual(response.status_code, 401)
            db.assert_not_called()

    def test_bad_source_and_short_article_rejected_before_database(self):
        with self.client.session_transaction() as sess:
            sess.update(admin_user="localowner",admin_role="owner",
                        admin_scope="owner",csrf_token="t")
        for changes in ({"source_url": "http://example.org/notice"},
                        {"article":"short"}, {"image_url":"https://example.org/image.jpg"},
                        {"category":"invalid"}):
            with self.subTest(changes=changes), patch("api.index.db") as db:
                body = dict(self.valid, **changes)
                result = self.client.post("/api/admin/news/create", json=body,
                             headers={"X-CSRF-Token":"t"})
                self.assertEqual(result.status_code, 400)
                db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
