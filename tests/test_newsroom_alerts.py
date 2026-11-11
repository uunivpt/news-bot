"""Phase 4: source history, truthful trends, scoped incident followups."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import NewsDatabase
from app.models import NewsItem
from app.newsroom_alerts import newsroom_alerts
from app.source_collection import ensure_collection_schema, record_collection


NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
INVENTORY = {
    "scope": "database", "items": [
        {"name": "TV9 Marathi", "enabled": True, "configured": True,
         "collection_status": "failed", "last_attempt_at": NOW.isoformat()},
        {"name": "The Hindu", "enabled": True, "configured": True,
         "collection_status": "healthy", "last_attempt_at": NOW.isoformat()},
        {"name": "Disabled", "enabled": False, "configured": True,
         "collection_status": "disabled"},
    ],
}


class Phase4AlertsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.tmp.name) / "phase4.db"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def story(self, desk):
        label = desk + "-" + str(self.db.count())
        self.db.insert(NewsItem(
            source_name="Fixture News", source_type="rss",
            title="Fixture " + label,
            url="https://example.org/" + label, category=desk,
            summary="A source-linked test story",
        ))
        item_id = self.db.conn.execute(
            "SELECT id FROM news_items ORDER BY id DESC LIMIT 1").fetchone()["id"]
        self.db.conn.execute(
            "UPDATE news_items SET status='published',published_at_site=? WHERE id=?",
            ((NOW - timedelta(hours=1)).isoformat(), item_id),
        )
        self.db.conn.commit()
        return item_id

    def test_no_history_does_not_pretend_collectors_are_healthy_and_creates_no_tables(self):
        ident = self.story("india")
        before = self.db.conn.total_changes
        summary = newsroom_alerts(self.db, INVENTORY, now=NOW)
        self.assertEqual(summary["status"], "attention")
        self.assertEqual(summary["scope"], "database")
        self.assertFalse(summary["availability"]["collector_history"])
        self.assertFalse(summary["availability"]["delivery"])
        self.assertFalse(summary["availability"]["corrections"])
        self.assertIsNone(summary["trend"]["recorded_outcomes"])
        self.assertEqual(summary["trend"]["series"][-1]["published"], 1)
        self.assertIsNone(summary["trend"]["series"][-1]["healthy"])
        self.assertEqual(summary["alerts"][0]["kind"], "source")
        self.assertEqual(summary["alerts"][0]["source"], "TV9 Marathi")
        self.assertEqual(self.db.conn.total_changes, before)
        existing = {r["name"] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("ph_source_collection_history", existing)
        self.assertNotIn("ph_public_delivery", existing)
        self.assertNotIn("ph_editorial_updates", existing)

    def test_completed_checks_are_written_once_and_error_text_is_not_logged(self):
        ensure_collection_schema(self.db)
        record_collection(self.db, "rss", "Publisher", status="checking")
        self.assertEqual(self.db.conn.execute(
            "SELECT COUNT(*) AS count FROM ph_source_collection_history").fetchone()["count"], 0)
        record_collection(self.db, "rss", "Publisher", status="healthy",
                          item_count=3, added_count=2, duplicate_count=1)
        record_collection(self.db, "rss", "Publisher", status="failed",
                          error=ValueError("Bearer token=DO-NOT-STORE"))
        records = [dict(row) for row in self.db.conn.execute(
            "SELECT * FROM ph_source_collection_history ORDER BY id").fetchall()]
        self.assertEqual([row["status"] for row in records], ["healthy", "failed"])
        self.assertEqual(records[0]["item_count"], 3)
        self.assertEqual(records[0]["added_count"], 2)
        self.assertEqual(records[1]["error_class"], "ValueError")
        self.assertNotIn("DO-NOT-STORE", str(records))
        latest = self.db.conn.execute(
            "SELECT last_success_at FROM ph_source_collection WHERE source_name='Publisher'").fetchone()
        self.assertIsNotNone(latest["last_success_at"])

    def test_real_collection_history_and_publication_counts_are_bucketed_by_utc_day(self):
        self.story("india")
        ensure_collection_schema(self.db)
        self.db.conn.execute(
            "INSERT INTO ph_source_collection_history"
            "(source_type,source_name,attempted_at,status) VALUES"
            "('rss','A',?,'healthy'),('rss','A',?,'failed'),('rss','A',?,'not_configured')",
            ((NOW - timedelta(days=1)).isoformat(),
             NOW.isoformat(), NOW.isoformat()),
        )
        self.db.conn.commit()
        summary = newsroom_alerts(self.db, {"scope":"database","items":[]}, now=NOW)
        self.assertTrue(summary["availability"]["collector_history"])
        self.assertEqual(summary["trend"]["recorded_outcomes"], 3)
        self.assertEqual(summary["trend"]["series"][-2]["healthy"], 1)
        self.assertEqual(summary["trend"]["series"][-1]["failed"], 1)
        self.assertEqual(summary["trend"]["series"][-1]["not_configured"], 1)
        self.assertEqual(len(summary["trend"]["series"]), 14)

    def test_empty_history_table_does_not_report_unmeasured_days_as_zero(self):
        ensure_collection_schema(self.db)
        before = self.db.conn.total_changes
        result = newsroom_alerts(self.db, {"scope": "database", "items": []}, now=NOW)
        self.assertTrue(result["trend"]["collector_history_available"])
        self.assertEqual(result["trend"]["recorded_outcomes"], 0)
        self.assertTrue(all(day["healthy"] is None and day["failed"] is None
                            and day["not_configured"] is None
                            for day in result["trend"]["series"]))
        self.assertEqual(self.db.conn.total_changes, before)

    def test_days_with_no_checks_remain_unrecorded_even_if_another_day_has_checks(self):
        ensure_collection_schema(self.db)
        record_collection(self.db, "rss", "Publisher", status="healthy")
        stamp = (NOW - timedelta(days=1)).isoformat()
        self.db.conn.execute(
            "UPDATE ph_source_collection_history SET attempted_at=?",
            (stamp,),
        )
        self.db.conn.commit()
        result = newsroom_alerts(self.db, {"scope": "database", "items": []}, now=NOW)
        self.assertEqual(result["trend"]["series"][-2]["healthy"], 1)
        self.assertEqual(result["trend"]["series"][-2]["failed"], 0)
        self.assertIsNone(result["trend"]["series"][-1]["healthy"])
        self.assertIsNone(result["trend"]["series"][-1]["failed"])

    def test_overdue_corrections_and_failed_deliveries_trigger_without_mutation(self):
        ident = self.story("india")
        self.db.conn.execute(
            "CREATE TABLE ph_public_delivery (item_id BIGINT,state TEXT,updated_at TEXT)")
        self.db.conn.execute(
            "CREATE TABLE ph_editorial_updates (id INTEGER PRIMARY KEY,item_id BIGINT,status TEXT,"
            "kind TEXT,created_at TEXT)")
        self.db.conn.execute(
            "INSERT INTO ph_public_delivery VALUES (?,?,?)",
            (ident, "failed", (NOW - timedelta(hours=2)).isoformat()),
        )
        self.db.conn.execute(
            "INSERT INTO ph_editorial_updates(item_id,status,kind,created_at) VALUES (?,?,?,?)",
            (ident, "pending", "correction", (NOW - timedelta(hours=7)).isoformat()),
        )
        self.db.conn.commit()
        before = self.db.conn.total_changes
        results = newsroom_alerts(self.db, {"scope":"database","items":[]}, now=NOW)
        self.assertEqual([a["kind"] for a in results["alerts"]], ["delivery", "correction"])
        self.assertEqual([a["severity"] for a in results["alerts"]], ["high", "high"])
        self.assertEqual(results["followups"][0]["item_id"], ident)
        self.assertEqual(results["followups"][0]["kind"], "correction")
        self.assertEqual(self.db.conn.total_changes, before)

    def test_stalled_delivery_and_update_thresholds_exclude_recent_items(self):
        ident = self.story("india")
        self.db.conn.execute(
            "CREATE TABLE ph_public_delivery (item_id BIGINT,state TEXT,updated_at TEXT)")
        self.db.conn.execute(
            "CREATE TABLE ph_editorial_updates (id INTEGER PRIMARY KEY,item_id BIGINT,status TEXT,"
            "kind TEXT,created_at TEXT)")
        self.db.conn.execute(
            "INSERT INTO ph_public_delivery VALUES (?,?,?)",
            (ident, "queued", (NOW - timedelta(minutes=44)).isoformat()),
        )
        self.db.conn.execute(
            "INSERT INTO ph_editorial_updates(item_id,status,kind,created_at) VALUES (?,?,?,?)",
            (ident, "pending", "update", (NOW - timedelta(hours=12)).isoformat()),
        )
        self.db.conn.commit()
        summary = newsroom_alerts(self.db, {"scope":"database","items":[]}, now=NOW)
        self.assertFalse(summary["alerts"])
        self.assertFalse(summary["followups"])
        self.assertEqual(summary["status"], "partial")

    def test_staff_scope_hides_other_desk_deliveries_and_corrections(self):
        india = self.story("india")
        world = self.story("world")
        self.db.conn.execute(
            "CREATE TABLE ph_public_delivery (item_id BIGINT,state TEXT,updated_at TEXT)")
        self.db.conn.execute(
            "CREATE TABLE ph_editorial_updates (id INTEGER PRIMARY KEY,item_id BIGINT,status TEXT,"
            "kind TEXT,created_at TEXT)")
        self.db.conn.executemany(
            "INSERT INTO ph_public_delivery VALUES (?,?,?)",
            [(india, "failed", NOW.isoformat()), (world, "failed", NOW.isoformat())],
        )
        self.db.conn.executemany(
            "INSERT INTO ph_editorial_updates(item_id,status,kind,created_at) VALUES (?,?,?,?)",
            [(india, "pending", "correction", (NOW-timedelta(days=1)).isoformat()),
             (world, "pending", "correction", (NOW-timedelta(days=1)).isoformat())],
        )
        self.db.conn.commit()
        result = newsroom_alerts(
            self.db, {"scope":"database","items":[]},
            where=" WHERE category=?", params=("india",), now=NOW)
        self.assertEqual(len(result["alerts"]), 2)
        self.assertTrue(all(item["item_id"] == india for item in result["alerts"]))
        self.assertEqual(result["trend"]["series"][-1]["published"], 1)

    def test_missing_database_inventory_never_creates_claimed_healthy_alerts(self):
        for scope in ("snapshot", "unavailable"):
            before=self.db.conn.total_changes
            state=newsroom_alerts(self.db, {"scope":scope,"items":[]}, now=NOW)
            self.assertEqual(state["scope"], "unavailable")
            self.assertIsNone(state["trend"])
            self.assertFalse(state["alerts"])
            self.assertEqual(self.db.conn.total_changes, before)


if __name__ == "__main__":
    unittest.main()
