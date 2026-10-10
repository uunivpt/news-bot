import os
import unittest
from unittest.mock import patch, Mock

from app.x_source import collect_x, _excerpt


class XSourceTests(unittest.TestCase):
    def test_missing_api_token_fails_closed(self):
        with patch.dict(os.environ, {"X_API_BEARER_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "X_API_BEARER_TOKEN"):
                collect_x({"handle": "RahulGandhi"})

    def test_handle_must_be_an_exact_valid_username(self):
        with patch.dict(os.environ, {"X_API_BEARER_TOKEN": "test"}):
            with self.assertRaises(ValueError):
                collect_x({"handle": "../bad"})

    @patch("app.x_source.requests.get")
    def test_sourced_post_without_images_and_with_original_link(self, get):
        account = Mock(status_code=200)
        account.json.return_value = {"data": {"id": "777", "username": "RahulGandhi", "name": "Rahul Gandhi"}}
        account.raise_for_status.return_value = None
        tweets = Mock(status_code=200)
        tweets.json.return_value = {"data": [
            {"id": "123456789", "text": "This statement is attributed to the account.", "created_at": "2026-10-10T06:00:00Z"},
            {"id": "invalid", "text": "Ignore this record as its ID is invalid.", "created_at": "2026-10-10T06:00:00Z"},
        ]}
        tweets.raise_for_status.return_value = None
        get.side_effect = [account, tweets]
        with patch.dict(os.environ, {"X_API_BEARER_TOKEN": "test-token"}):
            items = collect_x({"handle": "RahulGandhi", "name": "X — Rahul Gandhi", "category": "politics"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "x")
        self.assertEqual(items[0].url, "https://x.com/RahulGandhi/status/123456789")
        self.assertIsNone(items[0].image_url)
        self.assertIn("not been independently verified", items[0].summary)
        self.assertEqual(get.call_count, 2)

    @patch("app.x_source.requests.get")
    def test_handle_mismatch_is_never_relabelled(self, get):
        response = Mock()
        response.json.return_value = {"data": {"id": "777", "username": "Impersonator"}}
        get.return_value = response
        with patch.dict(os.environ, {"X_API_BEARER_TOKEN": "test-token"}):
            with self.assertRaisesRegex(RuntimeError, "did not match"):
                collect_x({"handle": "RahulGandhi"})

    def test_excerpts_are_truncated_safely(self):
        self.assertNotIn("https://", _excerpt("Read https://example.com for details"))
        self.assertLessEqual(len(_excerpt("example sentence " * 80)), 200)


class XQuoteCardTests(unittest.TestCase):
    def test_card_generation_and_source_guard(self):
        from app.x_quote_poster import render_x_quote_card
        with self.assertRaises(ValueError):
            render_x_quote_card({"source_type": "rss", "summary": "Hello"})
        data = render_x_quote_card({
            "source_type": "x", "source_name": "X — Rahul Gandhi",
            "summary": 'In an X post, @RahulGandhi wrote: “This statement is attributed to the original X account.” This is not verification.',
        })
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertGreater(len(data), 10000)


if __name__ == "__main__":
    unittest.main()
