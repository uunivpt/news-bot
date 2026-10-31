import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bs4 import BeautifulSoup
from api import index as api
from app.briefing import select_briefing, briefing_excerpt
from app.database import DatabaseUnavailable


NOW = datetime.now(timezone.utc)


def report(identity, hours=1, category="india", **changes):
    return {"id": identity, "title": f"Published public affairs report number {identity}",
            "summary": "A source-linked summary of a public affairs development.",
            "url": f"https://example.org/reports/{identity}", "source_name": "Example News",
            "published_at": (NOW - timedelta(hours=hours)).isoformat(),
            "category": category, "status": "published", "public_source": True, **changes}


class BriefingTests(unittest.TestCase):
    def select(self, rows, **options):
        return select_briefing(rows, timestamp=api._public_timestamp, now=NOW, **options)

    def test_window_excludes_stale_future_missing_dates_and_unpublished_reports(self):
        rows = [report(1), report(2, hours=25), report(3, hours=-1),
                report(4, published_at="bad"), report(5, status="pending"),
                report(6, public_source=False), report(7, url="javascript:alert(1)"),
                report(8, url="https://user:password@example.org/private")]
        self.assertEqual([row["id"] for row in self.select(rows)], [1])
        self.assertEqual([row["id"] for row in self.select(rows, days=7)], [1, 2])

    def test_represents_each_desk_then_fills_by_recency_and_caps_at_six(self):
        rows = [report(i, hours=i / 10) for i in range(1, 10)]
        rows += [report(20, hours=3, category="politics"), report(21, hours=4, category="world")]
        selected = self.select(rows)
        self.assertEqual([row["id"] for row in selected], [1, 20, 21, 2, 3, 4])
        self.assertEqual([row["id"] for row in self.select(rows, desk="world")], [21])

    def test_deduplicates_ids_and_source_urls_with_newest_version_winning(self):
        rows = [report(1), report(1, hours=2, url="https://example.org/other"),
                report(2, hours=3, url="https://example.org/reports/1"), report(3, hours=4)]
        self.assertEqual([row["id"] for row in self.select(rows)], [1, 3])

    def test_uses_publication_time_instead_of_collection_time(self):
        rows = [report(1, hours=100, collected_at=NOW.isoformat()),
                report(2, hours=100, published_at_site=(NOW - timedelta(hours=2)).isoformat())]
        self.assertEqual([row["id"] for row in self.select(rows)], [2])

    def test_snippets_remove_publisher_markup_and_scripts_without_losing_unicode(self):
        source = '<p class="publisher">महाराष्ट्र <strong>public news</strong> &amp; updates</p><script>bad()</script>'
        self.assertEqual(briefing_excerpt(source), "महाराष्ट्र public news & updates")
        self.assertLessEqual(len(briefing_excerpt("A source-linked public report. " * 40)), 320)

    def test_html_has_working_source_links_dates_filters_and_escaped_content(self):
        row = report(1, title='<script>alert("x")</script> public affairs report',
                     summary='<img src=x onerror=alert(1)> & important news')
        with patch.object(api, "_public_rows_for_section", return_value=[row]) as loader:
            response = api.app.test_client().get("/briefing/?desk=india&period=week")
        self.assertEqual(response.status_code, 200)
        loader.assert_called_once_with("india", 200)
        page = BeautifulSoup(response.data, "html.parser")
        self.assertEqual(len(page.select(".briefing-story")), 1)
        self.assertEqual(page.select_one('a[target="_blank"]')["href"], row["url"])
        self.assertIn("datetime", page.select_one("time").attrs)
        self.assertIsNone(page.select_one(".briefing-story script"))
        self.assertIsNone(page.select_one(".briefing-story img"))
        self.assertNotIn("<img", page.select_one(".briefing-summary").get_text())
        self.assertEqual(page.select_one("form")["method"], "get")
        self.assertEqual(page.select_one('[name="desk"] option[selected]')["value"], "india")
        self.assertNotIn("Vary", response.headers)
        self.assertIn("s-maxage=180", response.headers["Cache-Control"])

    def test_database_outage_uses_snapshot_and_stale_snapshot_stays_empty(self):
        with patch.object(api, "db", side_effect=DatabaseUnavailable("down")), \
             patch.object(api, "_snapshot_rows", return_value=[report(1)]):
            response = api.app.test_client().get("/api/briefing")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Original source", response.get_data(as_text=True))
        with patch.object(api, "db", side_effect=DatabaseUnavailable("down")), \
             patch.object(api, "_snapshot_rows", return_value=[report(1, hours=200)]):
            response = api.app.test_client().get("/briefing/")
        page = BeautifulSoup(response.data, "html.parser")
        self.assertIsNone(page.select_one(".briefing-story"))
        self.assertIn("No reports in this window", page.get_text())
        self.assertIsNotNone(page.select_one('a[href="/briefing/?desk=all&period=week"]'))

    def test_invalid_filters_redirect_and_authenticated_responses_are_private(self):
        client = api.app.test_client()
        for query in ("desk=unknown", "period=forever", "desk=%3Cscript%3E"):
            self.assertEqual(client.get("/briefing/?" + query).status_code, 302)
        with client.session_transaction() as session:
            session["admin_user"] = "test-owner"
        with patch.object(api, "_public_rows_for_section", return_value=[]):
            response = client.get("/briefing/")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")


if __name__ == "__main__":
    unittest.main()
