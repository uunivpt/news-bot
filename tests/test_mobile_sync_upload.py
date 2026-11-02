import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.mobile_sync_upload import validated
from scripts import mobile_sync_upload


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
    def test_scheduler_reads_actual_local_body_and_uses_shared_immediate_delivery(self):
        row={**story(),'bot_article':'A complete locally saved manuscript. '*20,'internal_access_token':'private fixture'}
        with tempfile.TemporaryDirectory() as folder:
            private=Path(folder)/'.politicshub-worker.pgpass'
            private.write_text('synthetic fixture'); private.chmod(0o600)
            with patch.object(Path,'home',return_value=Path(folder)), patch('psycopg.connect') as connect:
                connection=connect.return_value.__enter__.return_value
                connection.execute.return_value.fetchall.return_value=[row]
                rows=mobile_sync_upload.read_local_reviewed()
                self.assertEqual(rows[0]['bot_article'],row['bot_article'])
                self.assertNotIn('internal_access_token',rows[0])
                self.assertEqual(connect.call_args.kwargs['host'],'127.0.0.1')
                self.assertEqual(connection.execute.call_args_list[0].args[0],'SET TRANSACTION READ ONLY')
        with patch('sys.argv',['mobile_sync_upload.py','--push']), \
             patch.object(mobile_sync_upload,'read_local_reviewed',return_value=rows), \
             patch.object(mobile_sync_upload,'upload_immediate',return_value={'commit_sha':'a'*40}) as upload:
            mobile_sync_upload.main()
        upload.assert_called_once_with(rows)

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
