import unittest
from unittest.mock import Mock, patch

from scripts.check_meta_access import check_endpoint, diagnostic_status, _reason


class MetaAuthCheckTests(unittest.TestCase):
    @patch("scripts.check_meta_access.requests.get")
    def test_block_is_safely_classified_without_printing_token(self, get):
        reply = Mock(status_code=400, ok=False)
        reply.json.return_value = {"error": {
            "code": 200, "message": "API access blocked.", "fbtrace_id": "AbCdEF_123"
        }}
        get.return_value = reply
        result = check_endpoint("graph.instagram.com", "TOP-SECRET-TOKEN", "v25.0")
        self.assertEqual(result.reason, "meta_api_access_blocked")
        self.assertEqual(result.code, 200)
        self.assertNotIn("TOP-SECRET", str(result))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer TOP-SECRET-TOKEN")

    @patch("scripts.check_meta_access.requests.get")
    def test_facebook_login_token_reports_host_mismatch(self, get):
        first = Mock(status_code=400, ok=False)
        first.json.return_value = {"error": {"code": 200, "message": "API access blocked."}}
        second = Mock(status_code=200, ok=True)
        second.json.return_value = {"id": "private_user_id", "name": "Private User"}
        get.side_effect = [first, second]
        status, results = diagnostic_status("token", "v25.0", "graph.instagram.com")
        self.assertEqual(status, "different_host_working")
        self.assertTrue(results[1].passed)
        self.assertNotIn("private_user_id", str(results))

    @patch("scripts.check_meta_access.requests.get")
    def test_successful_configured_host_is_accepted(self, get):
        first = Mock(status_code=200, ok=True)
        first.json.return_value = {"id": "private_ig_id", "username": "redacted"}
        second = Mock(status_code=400, ok=False)
        second.json.return_value = {"error": {"code": 190, "message": "Wrong token"}}
        get.side_effect = [first, second]
        status, _ = diagnostic_status("token", "v25.0", "graph.instagram.com")
        self.assertEqual(status, "configured_host_working")

    def test_error_code_classifications(self):
        self.assertEqual(_reason(190, "expired"), "invalid_expired_or_revoked_token")
        self.assertEqual(_reason(200, "Insufficient permission"), "permission_or_app_access_denied")
        self.assertEqual(_reason(4, "rate limit"), "rate_limited")

    @patch("scripts.check_meta_access.requests.get", side_effect=__import__("requests").Timeout())
    def test_network_failures_are_reported_without_tokens(self, get):
        result = check_endpoint("graph.instagram.com", "secret", "v25.0")
        self.assertEqual(result.reason, "network_error")


if __name__ == "__main__":
    unittest.main()
