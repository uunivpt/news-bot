import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.database import NewsDatabase
from app.newsletter import (
    request_optin, confirm_optin, lookup_unsubscribe, unsubscribe,
    unsubscribe_token, verified_story, send_daily, send_mail, now_utc,
)


class NewsletterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(path=str(Path(self.tmp.name) / "news.db"))
        self.key = "a-durable-newsletter-signing-secret-for-tests"

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_double_optin_does_not_activate_until_confirmation(self):
        token = request_optin(self.db, "reader@example.com")
        pending = self.db.conn.execute("SELECT status,confirmed_at FROM newsletter_optins").fetchone()
        self.assertEqual(pending["status"], "pending")
        self.assertIsNone(pending["confirmed_at"])
        self.assertIsNone(request_optin(self.db, "reader@example.com"))
        self.assertIsNone(confirm_optin(self.db, "incorrect"))
        active = confirm_optin(self.db, token)
        self.assertEqual(active["status"], "active")
        self.assertIsNotNone(active["confirmed_at"])
        self.assertIsNone(confirm_optin(self.db, token))

    def test_tampered_and_old_unsubscribe_links_do_not_work(self):
        token = request_optin(self.db, "reader@example.com")
        active = confirm_optin(self.db, token)
        signed = unsubscribe_token(active["subscriber_id"], self.key)
        self.assertIsNone(lookup_unsubscribe(self.db, signed+"corrupt", self.key))
        self.assertIsNotNone(lookup_unsubscribe(self.db, signed, self.key))
        self.assertTrue(unsubscribe(self.db, signed, self.key))
        self.assertIsNone(lookup_unsubscribe(self.db, signed, self.key))
        self.assertFalse(unsubscribe(self.db, signed, self.key))

    def test_daily_digest_sends_once_per_ist_day(self):
        token = request_optin(self.db, "reader@example.com")
        confirm_optin(self.db, token)
        story = {"title":"Officials announce a public transport expansion plan",
                 "summary":"The full verified report explains the transport expansion and its public impact.",
                 "source":"Independent Wire","url":"https://example.org/transport"}
        with patch("app.newsletter.send_mail") as mock:
            self.assertEqual(send_daily(self.db, story, self.key), 1)
            self.assertEqual(send_daily(self.db, story, self.key), 0)
            self.assertEqual(mock.call_count, 1)

    def test_story_requires_recent_source_backed_reporting(self):
        recent = (now_utc()-timedelta(hours=2)).isoformat()
        row = {"title":"Officials publish a new public transport plan for residents",
               "summary":"A detailed public report explains the available transport services and schedule for residents.",
               "source_name":"Example Newswire", "url":"https://example.org/story",
               "published_at":recent, "public_source":True}
        self.assertIsNone(verified_story([dict(row, public_source=False)]))
        self.assertIsNone(verified_story([dict(row, fact_check_status="needs_review")]))
        self.assertEqual(verified_story([row])["source"], "Example Newswire")
        self.assertIsNone(verified_story([dict(row, published_at=(now_utc()-timedelta(days=4)).isoformat())]))

    def test_outgoing_email_has_sender_unsubscribe_and_both_bodies(self):
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD":"app-password-for-test"}):
            with patch("app.newsletter.smtplib.SMTP_SSL") as smtp:
                send_mail("reader@example.com","PoliticsHub Brief","Hello",["A sourced update"],
                          unsubscribe="https://www.politicshub.in/newsletter/unsubscribe?token=abc")
                msg=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertIn("politicshub.in@gmail.com",msg["From"])
                self.assertIn("List-Unsubscribe",msg)
                self.assertIn("List-Unsubscribe-Post",msg)
                self.assertIn("List-ID", msg)
                self.assertIsNotNone(msg["Date"])
                self.assertIsNotNone(msg["Message-ID"])
                self.assertTrue(msg.is_multipart())

    def test_verified_custom_domain_smtp_uses_starttls_and_sender(self):
        settings = {
            "NEWSLETTER_SMTP_HOST": "smtp.mail-provider.example",
            "NEWSLETTER_SMTP_PORT": "587",
            "NEWSLETTER_SMTP_USER": "mailer",
            "NEWSLETTER_SMTP_PASSWORD": "provider-app-password",
            "NEWSLETTER_FROM_EMAIL": "news@politicshub.in",
        }
        with patch.dict(os.environ, settings, clear=True):
            with patch("app.newsletter.smtplib.SMTP") as mock_smtp:
                send_mail("reader@example.com", "Your news", "News digest", ["Verified updates"],
                          unsubscribe="https://www.politicshub.in/newsletter/unsubscribe?token=valid")
                server = mock_smtp.return_value.__enter__.return_value
                msg = server.send_message.call_args.args[0]
                self.assertIn("news@politicshub.in", msg["From"])
                self.assertIn("List-ID", msg)
                self.assertIn("api/newsletter/one-click?", msg["List-Unsubscribe"])
                server.starttls.assert_called_once()
                server.login.assert_called_once_with("mailer", "provider-app-password")

    def test_partial_domain_mail_config_fails_closed_without_gmail_fallback(self):
        from app.newsletter import mail_configured
        with patch.dict(os.environ, {
            "NEWSLETTER_SMTP_HOST": "smtp.mail-provider.example",
            "GMAIL_APP_PASSWORD": "working-gmail-app-password",
        }, clear=True):
            self.assertFalse(mail_configured())
            with self.assertRaisesRegex(RuntimeError, "not fully configured"):
                send_mail("reader@example.com", "News", "Hello", ["Test"])


if __name__ == "__main__":
    unittest.main()
