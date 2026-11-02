"""Phase 3 contract: real measurements, read-only access, and no false green states."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import NewsDatabase
from app.models import NewsItem
from app.newsroom_operations import publication_operations, source_triage


NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def row(name, status, *, configured=True, enabled=True):
    return {
        "name": name, "collection_status": status,
        "configured": configured, "enabled": enabled,
        "last_attempt_at": "2026-11-02T14:00:00Z",
        "last_success_at": "2026-11-02T13:00:00Z",
    }


class SourceTriageTests(unittest.TestCase):
    def test_an_unavailable_or_snapshot_inventory_cannot_claim_any_collector_health(self):
        for scope in ("snapshot", "unavailable", "sample"):
            result = source_triage({"scope": scope, "items": [row("A", "healthy")]})
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["counts"])
            self.assertIsNone(result["attention"])
            self.assertFalse(result["incidents"])

    def test_no_checks_is_not_a_green_system(self):
        result = source_triage({"scope": "database", "items": [
            row("Publisher", "awaiting_collection"), row("Disabled", "disabled", enabled=False),
            row("Separate Hindi", "external_pipeline")
        ]})
        self.assertEqual(result["status"], "awaiting_checks")
        self.assertEqual(result["observed"], 0)
        self.assertEqual(result["counts"]["awaiting_collection"], 1)
        self.assertEqual(result["counts"]["disabled"], 1)
        self.assertEqual(result["counts"]["external_pipeline"], 1)

    def test_failed_stale_and_missing_setup_are_prioritized_without_counting_disabled(self):
        result = source_triage({"scope": "database", "items": [
            row("The Hindu", "healthy"),
            row("Z ABP", "stale"), row("A TV9", "failed"),
            row("Unconfigured", "not_configured"),
            row("Disabled", "failed", enabled=False),
            row("History", "failed", configured=False)
        ]})
        self.assertEqual(result["tracked"], 4)
        self.assertEqual(result["observed"], 3)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["attention"], 3)
        self.assertEqual([r["name"] for r in result["incidents"]],
                         ["A TV9", "Z ABP", "Unconfigured"])


class PublicationOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.temp.name) / "phase3.db"))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def story(self, category, minutes, *, published=True):
        now = NOW - timedelta(hours=3)
        label = f"{category}-{minutes}-{self.db.count()}"
        self.db.insert(NewsItem(source_name="Source", source_type="rss",
                                title=label, summary="Source summary", category=category,
                                url="https://example.org/" + label))
        ident = self.db.conn.execute(
            "SELECT id FROM news_items ORDER BY id DESC LIMIT 1").fetchone()["id"]
        collected = now.isoformat()
        at = (now + timedelta(minutes=minutes)).isoformat()
        self.db.conn.execute(
            "UPDATE news_items SET status=?,collected_at=?,published_at_site=? WHERE id=?",
            ("published" if published else "pending", collected, at, ident))
        self.db.conn.commit()
        return ident

    def test_latency_uses_committed_collected_to_published_timestamps(self):
        self.story("india", 10)
        self.story("world", 30)
        self.story("india", -10)
        self.story("world", 60, published=False)
        before = self.db.conn.total_changes
        result = publication_operations(self.db, now=NOW)
        metric = result["latency"]
        self.assertEqual(metric["evaluated"], 3)
        self.assertEqual(metric["measured"], 2)
        self.assertEqual(metric["median_minutes"], 20)
        self.assertEqual(metric["p95_minutes"], 30)
        self.assertEqual(metric["under_60m"], 2)
        self.assertFalse(result["delivery"]["recorded"])
        self.assertFalse(result["corrections"]["recorded"])
        self.assertEqual(self.db.conn.total_changes, before)
        tables = [r["name"] for r in self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertNotIn("ph_public_delivery", tables)
        self.assertNotIn("ph_editorial_updates", tables)

    def test_delivery_and_editorial_counts_are_scoped_and_read_only(self):
        india = self.story("india", 5)
        world = self.story("world", 40)
        self.db.conn.execute(
            "CREATE TABLE ph_public_delivery (item_id BIGINT, state TEXT)")
        self.db.conn.execute(
            "CREATE TABLE ph_editorial_updates (item_id BIGINT, status TEXT)")
        for table, entries in [
            ("ph_public_delivery", [(india, "queued"), (world, "failed")]),
            ("ph_editorial_updates", [(india, "pending"), (world, "published")])
        ]:
            self.db.conn.executemany(
                f"INSERT INTO {table}(item_id,status) VALUES (?,?)" if table == "ph_editorial_updates"
                else f"INSERT INTO {table}(item_id,state) VALUES (?,?)", entries)
        self.db.conn.commit()
        result = publication_operations(
            self.db, where=" WHERE category=?", params=("india",), now=NOW)
        self.assertEqual(result["latency"]["measured"], 1)
        self.assertEqual(result["delivery"]["counts"], {"queued": 1})
        self.assertEqual(result["corrections"]["counts"], {"pending": 1})

    def test_future_times_and_missing_timestamps_cannot_be_measured(self):
        self.story("india", 20)
        ident = self.story("india", 15)
        self.db.conn.execute(
            "UPDATE news_items SET published_at_site=? WHERE id=?",
            ((NOW + timedelta(days=2)).isoformat(), ident))
        self.db.conn.commit()
        result = publication_operations(self.db, now=NOW)
        self.assertEqual(result["latency"]["measured"], 1)


if __name__ == "__main__":
    unittest.main()
