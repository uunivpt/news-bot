import unittest
from datetime import datetime, timedelta, timezone

from api import index as api
from app.models import NewsItem
from scripts.offline_snapshot import build, public_story


class PublicNewsImageTests(unittest.TestCase):
    def test_owner_licensed_photos_are_public_when_credited(self):
        row = dict(id=31, source_type="manual", image_source="article-source",
                   image_url="https://media.example.org/photo.jpg",
                   image_license="licensed", image_credit="Photo Desk")
        self.assertTrue(api._is_source_supplied_image(row))
        self.assertEqual(api._public_image_path(row), "/api/image/31")
        for license_name in ("cc0", "pdm", "rights-owned"):
            self.assertTrue(api._is_source_supplied_image(dict(row, image_license=license_name)))

    def test_unlicensed_or_untrusted_images_are_never_published(self):
        row = dict(id=31, source_type="manual", image_source="article-source",
                   image_url="https://media.example.org/photo.jpg",
                   image_license="licensed", image_credit="Photo Desk")
        for change in (
            {"image_credit": ""},
            {"image_source": "rss"},
            {"image_license": ""},
            {"image_license": "unknown"},
            {"image_url": "https://127.0.0.1/private.jpg"},
            {"image_url": "javascript:alert(1)"},
        ):
            with self.subTest(change=change):
                invalid = dict(row, **change)
                self.assertFalse(api._is_source_supplied_image(invalid))
                self.assertEqual(api._public_image_path(invalid), "")

    def test_canonical_story_displays_photo_credit(self):
        row = dict(id=51, title="Public source photograph test", category="india",
                   source_type="manual", status="published",
                   summary="An attributed public account of a local news announcement.",
                   bot_article="Officials issued a public update after a formal meeting.",
                   image_source="article-source",
                   image_url="https://media.example.org/photo.jpg",
                   image_license="rights-owned",
                   image_credit="Original press photographer")
        with api.app.test_request_context("/"):
            page=api._article_html(row)
        self.assertIn('data-news-photo', page)
        self.assertIn('Photo: Original press photographer', page)
        self.assertIn('rights-owned', page)

    def test_newsdata_refresh_retains_approved_image_rights(self):
        now=datetime.now(timezone.utc)
        item=NewsItem(
            source_name="Example Publisher",source_type="newsdata",
            title="Officials issue a new public guidance notice",
            url="https://example.org/latest-official-guidance",
            summary="Officials provided a detailed update with supporting records and additional public information.",
            published_at=(now-timedelta(minutes=25)).isoformat(),public_source=True,
        )
        old=public_story(item, now)
        self.assertIsNotNone(old)
        old.update(summary="Older version of this report.",
                   image_url="https://media.example.org/photo.jpg",
                   image_license="licensed", image_credit="Press Agency",
                   image_source="article-source",
                   image_source_url="https://media.example.org/photo.jpg")
        rows,changed=build([old],[item],now)
        self.assertEqual(changed,1)
        self.assertEqual(rows[0]["image_credit"],"Press Agency")
        self.assertEqual(rows[0]["image_source"],"article-source")


if __name__ == "__main__":
    unittest.main()
