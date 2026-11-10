import json
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import commons_photos as photos
from api import index as api


def photo():
    return {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Rahul_Gandhi.jpg/1200px-Rahul_Gandhi.jpg",
        "image_source": "wikimedia-commons",
        "image_credit": "Press photographer",
        "image_license": "cc-by-sa-4.0",
        "image_source_url": "https://commons.wikimedia.org/wiki/File:Rahul_Gandhi.jpg",
        "image_license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    }


class CommonsPhotoTests(unittest.TestCase):
    def test_exact_subject_match_does_not_fabricate_image(self):
        self.assertEqual(photos.topic_for("Rahul Gandhi challenges a new policy", "india"), "Rahul Gandhi")
        self.assertIsNone(photos.topic_for("Rahul Gandhi and Narendra Modi debate", "india"))
        self.assertIsNone(photos.topic_for("A parliamentary debate was held", "india"))
        self.assertIsNone(photos.topic_for("US Supreme Court approves new rule", "world"))
        self.assertEqual(photos.topic_for("Supreme Court hears Delhi case", "india"), "Supreme Court of India")

    def test_license_and_photo_url_are_required(self):
        self.assertTrue(photos.valid_photo(photo()))
        for change in (
            {"image_url": "https://example.com/photo.jpg"},
            {"image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/logo.jpg/1200px-logo.jpg"},
            {"image_credit": ""},
            {"image_source": "random"},
            {"image_license": "unknown"},
            {"image_license_url": "https://malicious.example/licenses"},
            {"image_source_url": "https://en.wikipedia.org/wiki/Other"},
        ):
            with self.subTest(change=change):
                self.assertFalse(photos.valid_photo({**photo(), **change}))

    def test_wikipedia_subject_image_requires_licensed_commons_metadata(self):
        requests = []
        def transport(url, **kwargs):
            requests.append((url, kwargs))
            if "en.wikipedia.org" in url:
                payload = {"query": {"pages": [{"pageimage": "Rahul_Gandhi.jpg"}]}}
            else:
                payload = {"query": {"pages": [{"imageinfo": [{
                    "width": 1600, "height": 1000,
                    "thumburl": photo()["image_url"],
                    "descriptionurl": photo()["image_source_url"],
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "<a>Press photographer</a>"},
                    },
                }]}]}}
            return SimpleNamespace(content=json.dumps(payload).encode())
        result = photos.lookup_photo("Rahul Gandhi", transport=transport)
        self.assertTrue(photos.valid_photo(result))
        self.assertEqual(result["image_credit"], "Press photographer")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(kwargs["timeout"] == 8 for _, kwargs in requests))
        self.assertIsNone(photos.lookup_photo("Unapproved arbitrary search", transport=transport))

    def test_real_commons_thumbnail_host_tracking_and_older_license(self):
        def transport(url, **kwargs):
            if "en.wikipedia.org" in url:
                response = {"query": {"pages": [{"pageimage": "Delhi_fort.jpg"}]}}
            else:
                response = {"query": {"pages": [{"imageinfo": [{
                    "width": 4242, "height": 1949,
                    "thumburl": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2a/Delhi_fort.jpg/1280px-Delhi_fort.jpg?utm_source=commons.wikimedia.org",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Delhi_fort.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 3.0"},
                        "Artist": {"value": "<a>PerSona77</a>"},
                    },
                }]}]}}
            return SimpleNamespace(content=json.dumps(response).encode())
        result = photos.lookup_photo("Red Fort", transport=transport)
        self.assertIsNotNone(result)
        self.assertEqual(result["image_license"], "cc-by-sa-3.0")
        self.assertEqual(result["image_credit"], "PerSona77")
        self.assertEqual(result["image_url"],
            "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2a/Delhi_fort.jpg/1280px-Delhi_fort.jpg")
        self.assertTrue(photos.valid_photo(result))
        self.assertNotIn("utm_source", result["image_url"])

    def test_ambiguous_or_unknown_license_is_never_selected(self):
        def transport(url, **kwargs):
            payload = {"query": {"pages": [{"pageimage": "Rahul_Gandhi.jpg"}]}}
            if "commons.wikimedia.org" in url:
                payload = {"query": {"pages": [{"imageinfo": [{
                    "width": 1600, "height": 1000,
                    "thumburl": photo()["image_url"],
                    "descriptionurl": photo()["image_source_url"],
                    "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
                }]}]}}
            return SimpleNamespace(content=json.dumps(payload).encode())
        self.assertIsNone(photos.lookup_photo("Rahul Gandhi", transport=transport))

    def test_enrichment_is_bounded_cached_and_non_destructive(self):
        rows = [
            {"url": "https://publisher.example/1", "title": "Rahul Gandhi challenges policy", "category": "india"},
            {"url": "https://publisher.example/2", "title": "Rahul Gandhi speaks on debate", "category": "india"},
            {"url": "https://publisher.example/3", "title": "Ordinary municipal announcement", "category": "india"},
            {"url": "https://publisher.example/4", "title": "Rahul Gandhi official statement", "category": "india",
             "image_source": "article-source", "image_url": "https://publisher.example/owned.jpg"},
        ]
        calls = []
        def lookup(subject):
            calls.append(subject)
            return photo()
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        updated, cache, matched, requests = photos.enrich(rows, {}, lookup=lookup, max_lookup=1, now=now)
        self.assertEqual((matched, requests), (2, 1))
        self.assertEqual(calls, ["Rahul Gandhi"])
        self.assertTrue(all(updated[i]["image_source"] == "wikimedia-commons" for i in (0, 1)))
        self.assertNotIn("image_url", updated[2])
        self.assertEqual(updated[3]["image_source"], "article-source")
        again, _, matched, requests = photos.enrich(rows, cache, lookup=lookup, now=now)
        self.assertEqual((matched, requests), (2, 0))
        self.assertEqual(again[0]["image_license"], "cc-by-sa-4.0")
        unrelated, _, _, _ = photos.enrich(
            [{**updated[0], "title": "An unrelated public policy announcement"}],
            cache, lookup=lookup, now=now,
        )
        self.assertNotIn("image_url", unrelated[0])

    def test_public_projection_and_canonical_article_credit(self):
        row = {
            "id": 42, "title": "Rahul Gandhi challenges a public policy",
            "category": "india", "source_type": "manual", "status": "published",
            "url": "https://publisher.example/article",
            "summary": "Public official statements and attributed details were reported.",
            "bot_article": "The article records the source's statements without implying independently recorded events.",
            **photo(),
        }
        with api.app.test_request_context("/"):
            item = api._publicize(row)
            html = api._article_html(row)
        self.assertEqual(item["image_url"], photo()["image_url"])
        self.assertIn("Illustrative archive photo", html)
        self.assertIn("Photo source", html)
        self.assertIn("License", html)
        self.assertIn(photo()["image_license_url"], html)


if __name__ == "__main__":
    unittest.main()
