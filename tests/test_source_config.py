import json
from pathlib import Path
import unittest


class SourceConfigTests(unittest.TestCase):
    def test_production_source_config_is_valid_and_grouped(self):
        path = Path("config/sources.json")
        with path.open(encoding="utf-8") as handle:
            config = json.load(handle)

        expected_groups = {"rss", "telegram", "website", "newsapi", "newsdata"}
        self.assertTrue(expected_groups.issubset(config))
        for group in expected_groups:
            self.assertIsInstance(config[group], list)
            for source in config[group]:
                self.assertIsInstance(source, dict)
                self.assertIn("name", source)
                self.assertIn("enabled", source)

    def test_pib_source_uses_official_current_directory_and_unverified_feed_is_disabled(self):
        config = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        rows = {row["name"]:row for row in config["rss"]}
        released = rows["PIB Press Releases"]
        self.assertFalse(released["enabled"])
        self.assertEqual(released["url"],"https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3")
        self.assertIn("Re-enable only", released["note"])
        phone_pib = next(x for x in config["website"] if x["name"] == "Government of India - PIB")
        self.assertTrue(phone_pib["enabled"])
        self.assertTrue(phone_pib["collection_allowed"])
        invitation = rows["PIB Media Invitations"]
        self.assertFalse(invitation["enabled"])
        self.assertIn("Re-enable only",invitation["note"])

    def test_news_api_sources_are_india_scoped_and_licensed_for_use(self):
        config = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        newsapi = config["newsapi"]
        newsdata = config["newsdata"]
        self.assertTrue(newsapi)
        self.assertTrue(newsdata)
        self.assertTrue(all(item.get("country") == "in" for item in newsapi + newsdata))
        self.assertTrue(all(item.get("enabled") for item in newsdata))
        for item in newsapi:
            if not item.get("enabled"):
                self.assertTrue(item.get("license_review_required"))


if __name__ == "__main__":
    unittest.main()
