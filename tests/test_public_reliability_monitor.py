import json
import unittest

from scripts.check_public_reliability import check


class PublicReliabilityMonitorTests(unittest.TestCase):
    def responses(self):
        row = {"id": 77, "title": "Three AAP MLAs join BJP in Punjab",
               "status": "published", "category": "india", "url": "https://example.org/77"}
        return {
            "/api/health": (200, json.dumps({"ok": True, "stories": 140})),
            "/api/news?limit=30": (200, json.dumps([row])),
            "/api/news?category=politics&limit=50": (200, json.dumps([row])),
            "/politics/": (200, '<h1>Politics news</h1><a href="/politics/">Politics<small>22</small></a>'),
            "/api/news/77": (200, json.dumps(row)),
            "/api/admin/me": (200, '{"authenticated":false}')
        }

    def test_healthy_public_site_and_unauthed_gateway(self):
        sources = self.responses()
        self.assertTrue(check(lambda p: sources[p]))

    def test_missing_politics_count_is_error_not_a_false_success(self):
        sources = self.responses()
        sources["/politics/"] = (200, '<h1>Politics news</h1><a href="/politics/">Politics<small>0</small></a>')
        self.assertFalse(check(lambda p: sources[p]))

    def test_unpublished_or_private_records_are_rejected(self):
        sources = self.responses()
        entry = json.loads(sources["/api/news?limit=30"][1])[0]
        entry["status"] = "pending"
        entry["approved_at"] = "internal"
        sources["/api/news?limit=30"] = (200, json.dumps([entry]))
        self.assertFalse(check(lambda p: sources[p]))

    def test_empty_politics_desk_is_valid_and_phone_outage_is_separate(self):
        sources = self.responses()
        sources["/api/news?category=politics&limit=50"] = (200, "[]")
        sources["/api/admin/me"] = (503, '{"code":"phone_admin_offline"}')
        self.assertTrue(check(lambda p: sources[p]))


if __name__ == "__main__":
    unittest.main()
