import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scripts.mobile_editorial_approve import (
    approve_local, check_evidence, parse_published,
    review_eligibility, risk_flags,
)


NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def story(**overrides):
    record = {
        "id": 455,
        "title": "India transport authority announces verified public timetable updates",
        "source_name": "Official transport authority",
        "source_type": "rss",
        "url": "https://transport.gov.example/notice",
        "public_source": 1,
        "summary": "The transport office provided confirmation about new public service times and routes.",
        "bot_summary": "The transport office provided confirmation about new public service times and routes.",
        "bot_article": "The official bulletin confirms additional public transport services. " * 12,
        "published_at": (NOW - timedelta(hours=3)).isoformat(),
        "published_at_site": None,
        "status": "pending",
        "fact_check_status": "pending",
        "approved_at": None,
    }
    record.update(overrides)
    return record


class EditorialApprovalPolicyTests(unittest.TestCase):
    def test_eligible_draft_requires_human_review_not_auto_approval(self):
        row = story()
        self.assertEqual(review_eligibility(row, NOW), [])
        self.assertEqual(risk_flags(row), [])
        self.assertEqual(check_evidence(row, ["https://another.example.org/report"])[1], [])

    def test_telegram_violent_conflict_requires_two_distinct_hosts(self):
        row = story(
            url="https://t.me/DDGeopolitics/193655",
            title="Russian armed forces launched strikes across Ukraine overnight",
            bot_article="A short draft.",
        )
        self.assertTrue(risk_flags(row))
        self.assertIn("Full draft is too short for editorial approval", review_eligibility(row, NOW))
        _, errors = check_evidence(row, ["https://othernews.example.net/report"])
        self.assertTrue(any("Need 2" in x for x in errors))
        _, errors = check_evidence(
            row, ["https://othernews.example.net/report", "https://othernews.example.net/second"]
        )
        self.assertTrue(errors)
        sources, errors = check_evidence(
            row, ["https://othernews.example.net/report", "https://official.example.org/notice"]
        )
        self.assertEqual(len(sources), 2)
        self.assertEqual(errors, [])

    def test_rejects_pending_short_story_and_stale_reporting(self):
        row = story(bot_article="No detail")
        self.assertTrue(review_eligibility(row, NOW))
        old = story(published_at=(NOW - timedelta(days=8)).isoformat())
        self.assertIn("Old or future-dated story: do not republish as new", review_eligibility(old, NOW))

    def test_rejects_unapproved_source_or_already_published(self):
        for row in (story(public_source=0), story(status="published"),
                    story(approved_at=NOW.isoformat()),
                    story(url="http://example.org/article")):
            with self.subTest(row=row):
                self.assertTrue(review_eligibility(row, NOW))

    def test_parses_rss_and_iso_dates_in_utc(self):
        self.assertEqual(parse_published("Sat, 31 Oct 2026 12:00:00 GMT"), NOW)
        self.assertEqual(parse_published("2026-10-31T12:00:00+00:00"), NOW)
        self.assertIsNone(parse_published("not a timestamp"))


class AtomicApprovalTests(unittest.TestCase):
    @patch("psycopg.connect")
    def test_approval_writes_one_row_and_audit_in_single_transaction(self, connect):
        row = story()
        conn = MagicMock()
        cur = MagicMock()
        connect.return_value.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        cur.fetchone.return_value = dict(row)
        cur.rowcount = 1
        evidence = ["https://another.example.org/full-article"]
        result = approve_local(
            row, evidence, "I independently checked the article text, date, named agencies and context.",
            "never-logged-password", now=NOW
        )
        self.assertEqual(result, 455)
        self.assertEqual(cur.execute.call_count, 3)
        updates = cur.execute.call_args_list
        self.assertIn("FOR UPDATE", updates[0].args[0])
        self.assertIn("approved_at", updates[1].args[0])
        self.assertIn("status='pending'", updates[1].args[0])
        self.assertIn("INSERT INTO admin_activity", updates[2].args[0])
        self.assertEqual(updates[1].args[1][0], "reviewed")
        self.assertEqual(updates[1].args[1][4], "published")
        self.assertNotIn("never-logged-password", str(updates))

    @patch("psycopg.connect")
    def test_prevent_stale_preview_overwriting_changed_story(self, connect):
        row = story()
        conn = MagicMock()
        cur = MagicMock()
        connect.return_value.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        cur.fetchone.return_value = story(title="A revised source headline")
        with self.assertRaisesRegex(RuntimeError, "changed during review"):
            approve_local(
                row, ["https://another.example.org/report"],
                "Independent documents establish the reported timetable, identity and date.",
                "password", now=NOW
            )
        self.assertEqual(cur.execute.call_count, 1)

    @patch("psycopg.connect")
    def test_no_password_or_connection_needed_for_insufficient_evidence(self, connect):
        with self.assertRaises(ValueError):
            approve_local(
                story(), [], "Independent source is still being checked in detail; not verified.",
                "password", now=NOW,
            )
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
