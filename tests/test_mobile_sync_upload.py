import unittest

from scripts.mobile_sync_upload import validated


def story():
    return {
        "id": 4503599627371000,
        "title": "Official report confirms new public details in India",
        "source_name": "Verified source",
        "source_type": "rss",
        "url": "https://example.org/public-release",
        "summary": "Officials released full new details in the public report. Additional context is linked at the original source.",
        "status": "published",
        "public_source": True,
        "approved_at": "2026-10-31T09:00:00+00:00",
        "fact_check_status": "verified",
    }


class MobileUploadSafetyTests(unittest.TestCase):
    def test_empty_export_is_safe(self):
        self.assertEqual(validated([]), 0)

    def test_verified_export_is_accepted(self):
        self.assertEqual(validated([story()]), 1)

    def test_human_reviewed_and_approved_story_is_accepted(self):
        row = story()
        row["fact_check_status"] = "reviewed"
        self.assertEqual(validated([row]), 1)

    def test_reviewed_without_approval_timestamp_rejected(self):
        row = story()
        row["fact_check_status"] = "reviewed"
        row["approved_at"] = None
        with self.assertRaises(ValueError):
            validated([row])

    def test_unapproved_or_pending_rejected(self):
        row = story()
        row["approved_at"] = None
        with self.assertRaises(ValueError):
            validated([row])
        row = story()
        row["fact_check_status"] = "pending"
        with self.assertRaises(ValueError):
            validated([row])

    def test_unsafe_or_duplicate_data_rejected(self):
        row = story()
        row["url"] = "http://example.org/public-release"
        with self.assertRaises(ValueError):
            validated([row])
        with self.assertRaises(ValueError):
            validated([story(), story()])
        row = story()
        row["id"] = 2**53
        with self.assertRaises(ValueError):
            validated([row])


if __name__ == "__main__":
    unittest.main()
