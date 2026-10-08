import tempfile
import unittest
from pathlib import Path

from app.database import NewsDatabase
from scripts.restore_public_snapshot import restore, select_stories


def story(i, *, source_type="newsdata", url=None, public=True):
    return {
        "id": i,
        "source_name": "Public Wire",
        "source_type": source_type,
        "title": "Official report confirms major public transportation update",
        "url": url or f"https://example.org/news/{i}",
        "summary": "Officials released a verified transport update describing the service and its public impact.",
        "bot_article": "A complete source-based report with further context and attribution.",
        "category": "india",
        "published_at": "2026-10-08T09:00:00+00:00",
        "public_source": public,
    }


class RecoverySnapshotTests(unittest.TestCase):
    def test_filters_unverified_or_repeated_content(self):
        rows = select_stories([
            story(100),
            story(101, source_type="telegram"),
            story(102, public=False),
            story(103, url="http://untrusted.example/news"),
            story(104, url="https://example.org/news/100"),
            story(105),
        ])
        self.assertEqual([x["id"] for x in rows], [100, 105])

    def test_restores_into_empty_database_without_replacing_existing_data(self):
        with tempfile.TemporaryDirectory() as d:
            db = NewsDatabase(str(Path(d) / "recovery.db"))
            try:
                rows = select_stories([story(100), story(101)])
                self.assertEqual(restore(db, rows), 2)
                record = dict(db.get_by_id(100))
                self.assertEqual(record["status"], "published")
                self.assertEqual(record["source_name"], "Public Wire")
                self.assertEqual(record["bot_article"],
                                 "A complete source-based report with further context and attribution.")
                self.assertEqual(record["category"], "india")
                self.assertEqual(db.newsletter_count(), 0)
                with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
                    restore(db, rows)
                self.assertEqual(db.count(), 2)
            finally:
                db.close()

    def test_resume_partial_restore_and_ignore_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            db = NewsDatabase(str(Path(d) / "recovery.db"))
            try:
                first = select_stories([story(100), story(101)])
                self.assertEqual(restore(db, first), 2)
                full = select_stories([story(100), story(101), story(102)])
                self.assertEqual(restore(db, full, resume=True), 1)
                self.assertEqual(db.count(), 3)
                self.assertEqual(restore(db, full, resume=True), 0)
            finally:
                db.close()

    def test_resume_refuses_foreign_existing_articles(self):
        with tempfile.TemporaryDirectory() as d:
            db = NewsDatabase(str(Path(d) / "recovery.db"))
            try:
                self.assertEqual(restore(db, select_stories([story(900)])), 1)
                with self.assertRaisesRegex(RuntimeError, "Refusing to mix projects"):
                    restore(db, select_stories([story(100)]), resume=True)
                self.assertEqual(db.count(), 1)
            finally:
                db.close()

    def test_never_restores_empty_or_unauthorized_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            db = NewsDatabase(str(Path(d) / "recovery.db"))
            try:
                with self.assertRaises(ValueError):
                    restore(db, [])
                self.assertEqual(db.count(), 0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
