"""SEO contract: canonical pages, HTTP content, quality gates, sitemap XML."""
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from api import index as api
from app.seo_indexing import (
    SITE_ORIGIN, canonical_path, eligible_articles,
    is_indexable, news_sitemap_xml, sitemap_index_xml, static_sitemap_xml,
)


def example():
    return {
        "id": 44, "title": "India Parliament passes a significant new public services law",
        "category": "india", "status": "published", "public_source": True,
        "source_type": "newsdata", "url": "https://example.org/news/44",
        "source_name": "Source News",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "summary": "Official sources report changes to public services after discussion in Parliament. " * 2,
        "bot_summary": "Official sources report changes to public services after discussion in Parliament. " * 2,
        "bot_article": "Official sources described the parliamentary debate and changes to public services. " * 8,
    }


class SEOIndexingTests(unittest.TestCase):
    def test_valid_source_story_and_canonical(self):
        row=example()
        self.assertTrue(is_indexable(row))
        self.assertEqual(canonical_path(row),"/india/44-india-parliament-passes-a-significant-new-public-services-law")
        xml=news_sitemap_xml([row,row])
        root=ET.fromstring(xml)
        self.assertEqual(len(list(root)),1)
        self.assertEqual(root[0][0].text,SITE_ORIGIN+canonical_path(row))

    def test_excludes_thin_future_unsourced_and_telegram(self):
        row=example()
        mutations=(
            {"bot_article":""},{"bot_article":"short"}, {"public_source":False},
            {"source_type":"telegram"},{"url":"http://example.org/news"},
            {"title":"Short"}, {"published_at":(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()},
            {"status":"pending"},
        )
        for change in mutations:
            with self.subTest(change=change):
                self.assertFalse(is_indexable(dict(row,**change)))
        self.assertEqual(eligible_articles([dict(row,public_source=False)]),[])

    def test_static_sitemaps_use_only_www_canonical(self):
        index=ET.fromstring(sitemap_index_xml())
        static=ET.fromstring(static_sitemap_xml())
        self.assertEqual(len(index),2)
        for loc in [x[0].text for x in index]+[x[0].text for x in static]:
            self.assertTrue(loc.startswith("https://www.politicshub.in/"),loc)
        self.assertIn("https://www.politicshub.in/",[x[0].text for x in static])

    def test_flask_html_and_status_codes(self):
        client=api.app.test_client()
        row=example()
        with patch.object(api,"_public_row_by_id",return_value=row):
            canonical=canonical_path(row)
            resp=client.get("/api/seo-article"+canonical)
            self.assertEqual(resp.status_code,200,resp.data[:300])
            self.assertIn("<h1>",resp.get_data(as_text=True))
            self.assertIn('rel="canonical" href="'+SITE_ORIGIN+canonical+'"',resp.get_data(as_text=True))
            self.assertIn('"@type": "NewsArticle"',resp.get_data(as_text=True))
            self.assertNotIn('name="robots" content="noindex',resp.get_data(as_text=True))
            resp2=client.get("/api/seo-article/india/44-incorrect-slug")
            self.assertEqual(resp2.status_code,301)
            self.assertEqual(resp2.headers["Location"],SITE_ORIGIN+canonical)
        with patch.object(api,"_public_row_by_id",return_value=dict(row,bot_article="short")):
            noindex=client.get("/api/seo-article"+canonical)
            self.assertIn('name="robots" content="noindex,follow"',noindex.get_data(as_text=True))

    def test_production_routes_and_snapshot_sitemap(self):
        config=json.loads(Path("vercel.json").read_text())
        rewrites={(r["source"],r["destination"]) for r in config["rewrites"]}
        self.assertIn(("/news-sitemap.xml","/api/seo-news-sitemap"),rewrites)
        self.assertIn(("/india/:story","/api/seo-article/india/:story"),rewrites)
        self.assertNotIn(("/india/:path*","/index.html"),rewrites)
        row=example()
        with patch.object(api,"_published_sitemap_rows",return_value=[row,dict(row,public_source=False)]):
            resp=api.app.test_client().get("/api/seo-news-sitemap")
            self.assertEqual(resp.status_code,200)
            parsed=ET.fromstring(resp.data)
            self.assertEqual(len(parsed),1)
            self.assertEqual(parsed[0][0].text,SITE_ORIGIN+canonical_path(row))


if __name__=="__main__":
    unittest.main()
