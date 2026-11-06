import copy
import json
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from api import index as api
from app.newsroom import dedupe_story_rows
from app.database import DatabaseUnavailable


def story(identity, title, *, category="hindi", score=10):
    return {"id": identity, "title": title, "category": category,
            "summary": "मूळ प्रकाशकाच्या वृत्ताचा संक्षिप्त संदर्भ.",
            "url": f"https://example.org/reports/{identity}", "source_name": "Fixture RSS",
            "published_at": (datetime.now(timezone.utc) - timedelta(minutes=identity)).isoformat(),
            "status": "published", "public_source": True, "news_score": score}


class MultilingualHeadlineTests(unittest.TestCase):
    def test_distinct_devanagari_only_headlines_are_retained(self):
        rows = [story(1, "रेल सेवाओं में बदलाव के बारे में नई सूचना"),
                story(2, "विद्यालयों में प्रवेश की प्रक्रिया का विवरण"),
                story(3, "नदी के जलस्तर की जानकारी जारी")]
        original = copy.deepcopy(rows)
        self.assertEqual([row["id"] for row in dedupe_story_rows(rows)], [1, 2, 3])
        self.assertEqual(rows, original)

    def test_shared_english_label_does_not_merge_unrelated_hindi_reports(self):
        rows = [story(1, "Live: रेलवे की नई समय सारिणी जारी"),
                story(2, "Live: विद्यालयों की प्रवेश प्रक्रिया शुरू")]
        self.assertEqual(len(dedupe_story_rows(rows)), 2)

    def test_marathi_headlines_keep_their_combining_marks(self):
        rows = [story(1, "पुण्यातील सार्वजनिक वाहतुकीबाबत नवीन माहिती", category="india"),
                story(2, "शाळांमधील प्रवेश प्रक्रियेचे वेळापत्रक जाहीर", category="india")]
        self.assertEqual([row["title"] for row in dedupe_story_rows(rows)], [row["title"] for row in rows])

    def test_unicode_equivalent_duplicate_keeps_higher_scored_copy(self):
        rows = [story(1, "क़ानून पर सार्वजनिक चर्चा का विवरण", score=10),
                story(2, "क़ानून पर सार्वजनिक चर्चा का विवरण", score=20)]
        self.assertEqual([row["id"] for row in dedupe_story_rows(rows)], [2])

    def test_exact_hindi_duplicates_are_still_collapsed(self):
        rows = [story(1, "सार्वजनिक सूचना का पूरा विवरण"), story(2, "सार्वजनिक सूचना का पूरा विवरण")]
        self.assertEqual(len(dedupe_story_rows(rows)), 1)

    def test_english_duplicate_scoring_stays_the_same(self):
        rows = [story(1, "Government announces a new public transport plan", category="india", score=10),
                story(2, "Government announces a new public transport plan", category="india", score=20),
                story(3, "Scientists publish independent research findings", category="world", score=10)]
        self.assertEqual([row["id"] for row in dedupe_story_rows(rows)], [2, 3])

    def test_short_acronym_headlines_survive_while_blank_headlines_do_not(self):
        rows = [story(1, "US UK"), story(2, "EU UN"), story(3, " ")]
        self.assertEqual([row["id"] for row in dedupe_story_rows(rows)], [1, 2])

    def test_hindi_api_retains_headlines_dates_and_original_sources(self):
        rows = [story(1, "रेल सेवाओं में बदलाव के बारे में नई सूचना"),
                story(2, "विद्यालयों में प्रवेश की प्रक्रिया का विवरण"),
                story(3, "नदी के जलस्तर की जानकारी जारी")]
        with patch.object(api, "_hindi_rows", return_value=rows):
            response = api.app.test_client().get("/api/hindi-feed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json], [1, 2, 3])
        for original, actual in zip(rows, response.json):
            for field in ("title", "published_at", "source_name", "url"):
                self.assertEqual(actual[field], original[field])

    def test_long_hindi_rss_headline_matches_feed_detail_article_and_share(self):
        title = 'धनतेरस 2026 Live: शुभ संयोग में धनतेरस आज, जानें खरीदारी का शुभ मुहूर्त और किन बातों का रखें ध्यान'
        row = story(762, title)
        row['source_type'] = 'rss'
        original = copy.deepcopy(row)
        client = api.app.test_client()
        with patch.object(api, '_hindi_rows', return_value=[row]), \
             patch.object(api, '_official_exam_rows', return_value=[]), \
             patch.object(api, '_snapshot_rows', return_value=[]), \
             patch.object(api.public_archive, 'by_id', return_value=None), \
             patch.object(api, 'db', side_effect=DatabaseUnavailable('fixture unavailable')):
            feed = client.get('/api/hindi-feed')
            detail = client.get('/api/news/762')
            page = client.get('/hindi/' + api.news_number(row))
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(feed.json[0]['title'], title)
        self.assertEqual(detail.json['title'], title)
        self.assertEqual(detail.json['url'], row['url'])
        self.assertEqual(detail.json['source_name'], row['source_name'])
        self.assertEqual(datetime.fromisoformat(detail.json['published_at_iso'].replace('Z', '+00:00')),
                         datetime.fromisoformat(row['published_at']))
        document = BeautifulSoup(page.data, 'html.parser')
        self.assertEqual(document.select_one('.art h1').get_text(), title)
        self.assertEqual(document.select_one('.article-share')['data-share-title'], title)
        self.assertEqual(document.select_one('meta[property="og:title"]')['content'], title)
        metadata = json.loads(document.select_one('script[type="application/ld+json"]').string)
        self.assertEqual(metadata['headline'], title)
        self.assertEqual(metadata['datePublished'], detail.json['published_at_iso'])
        self.assertEqual(row, original)

    def test_hindi_rss_headline_is_still_cleaned_and_other_rss_policy_is_unchanged(self):
        title = 'धनतेरस 2026 Live: शुभ संयोग में धनतेरस आज, जानें खरीदारी का शुभ मुहूर्त और किन बातों का रखें ध्यान'
        row = story(763, title)
        row.update(source_type='rss', title='<strong>' + title + '</strong><script>unsafe()</script>')
        with api.app.test_request_context('/'):
            self.assertEqual(api._publicize(row)['title'], title)
            row['category'] = 'india'
            self.assertEqual(api._publicize(row)['title'], api._public_title(row['title'], row['summary']))


if __name__ == "__main__":
    unittest.main()
