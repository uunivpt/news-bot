import hashlib
import os
import unittest
from unittest.mock import patch
from flask import Flask, request
from app.remote_admin_bridge import (
    _REPLAY, bridge_config, bridge_headers, is_private_endpoint,
    verify_phone_bridge,
)


class RemoteAdminBridgeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("bridge-test")
        _REPLAY.clear()
        self.secret = "another-private-key-used-only-in-testing-123456789"

    def request(self, *, url="/api/admin/workspace", method="GET", body=b"", headers=None):
        with self.app.test_request_context(url, method=method, data=body, headers=headers or {}):
            return verify_phone_bridge(request, self.secret, now=1234567890)

    def test_approved_admin_paths_are_exactly_scoped(self):
        for p in ("/api/admin/login", "/api/admin/me", "/api/admin/workspace",
                  "/api/admin/story/455", "/api/news/455/approve",
                  "/api/news/455/edit", "/api/fact-check"):
            self.assertTrue(is_private_endpoint(p), p)
        for p in ("/api/admin/setup", "/api/admin/nonexistent",
                  "/api/news/455", "/api/news",
                  "/api/health", "/api/newsletter/daily",
                  "/api/admin/story/../../etc/passwd"):
            self.assertFalse(is_private_endpoint(p), p)

    def test_no_bridge_without_pair_of_envs(self):
        with patch.dict(os.environ, {"POLITICSHUB_ADMIN_BRIDGE_URL": "",
                                     "POLITICSHUB_ADMIN_BRIDGE_SECRET": ""}):
            self.assertIsNone(bridge_config())
        with patch.dict(os.environ, {"POLITICSHUB_ADMIN_BRIDGE_URL": "https://example.trycloudflare.com",
                                     "POLITICSHUB_ADMIN_BRIDGE_SECRET": "short"}):
            with self.assertRaises(ValueError):
                bridge_config()

    def test_tunnel_url_cannot_target_private_network_or_other_domains(self):
        for value in ("http://example.trycloudflare.com", "http://127.0.0.1:5432",
                      "https://localhost", "https://example.com",
                      "https://www.politicshub.in", "https://example.trycloudflare.com/foo",
                      "https://test.trycloudflare.com:9443",
                      "https://x.trycloudflare.com@evil.example"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {
                    "POLITICSHUB_ADMIN_BRIDGE_URL": value,
                    "POLITICSHUB_ADMIN_BRIDGE_SECRET": self.secret
                }):
                    with self.assertRaises(ValueError):
                        bridge_config()
        with patch.dict(os.environ, {
            "POLITICSHUB_ADMIN_BRIDGE_URL": "https://phone-admin.trycloudflare.com",
            "POLITICSHUB_ADMIN_BRIDGE_SECRET": self.secret
        }):
            self.assertEqual(bridge_config()[0], "https://phone-admin.trycloudflare.com")

    def test_authentication_validates_body_clock_method_and_query(self):
        date = 1234567890
        nonce = "anewrandomnonceforsecurevalidation0001"
        body = b'{"evidence_urls":["https://example.org/a"],"notes":"review"}'
        path = "/api/news/455/approve?version=2"
        headers = bridge_headers(self.secret, "POST", path, body, when=date, nonce=nonce)
        self.assertTrue(self.request(url=path, method="POST", body=body, headers=headers))
        self.assertFalse(self.request(url=path, method="POST", body=body, headers=headers),
                         "Replay must be rejected")
        self.assertFalse(self.request(url=path, method="POST", body=b"changed", headers=headers))
        self.assertFalse(self.request(url=path, method="POST", body=body, headers={
            **headers, "X-PH-Bridge-Nonce": "anothernonceforsecurevalidation0002"
        }))
        self.assertFalse(self.request(url=path, method="POST", body=body, headers={
            **headers, "X-PH-Bridge-Time": str(date-80)
        }))
        self.assertFalse(self.request(url="/api/admin/me", method="GET", body=b"",
                                      headers=headers))

    def test_request_without_signature_rejected(self):
        self.assertFalse(self.request())
        self.assertFalse(self.request(headers={"X-PH-Bridge-Time": "1234567890"}))


if __name__ == "__main__":
    unittest.main()
