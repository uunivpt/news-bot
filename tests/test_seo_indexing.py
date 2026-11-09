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
    is_indexable, news_sitemap_xml, google_news_sitemap_xml, sitemap_index_xml, static_sitemap_xml,
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
        self.assertEqual(canonical_path(row),"/india/"+__import__("app.news_numbers",fromlist=["news_number"]).news_number(row))
        xml=news_sitemap_xml([row,row])
        root=ET.fromstring(xml)
        self.assertEqual(len(list(root)),1)
        self.assertEqual(root[0][0].text,SITE_ORIGIN+canonical_path(row))

    def test_unreviewed_source_only_rss_is_browsable_but_not_indexable(self):
        original = example()
        original["source_type"] = "rss"
        self.assertFalse(is_indexable(original))
        original["editorial_value"] = True
        self.assertTrue(is_indexable(original))
        original["editorial_value"] = False
        original["fact_check_status"] = "reviewed"
        self.assertTrue(is_indexable(original))

    def test_reviewed_rss_indexability_survives_public_projection(self):
        original = dict(example(), source_type="rss", fact_check_status="reviewed")
        with api.app.test_request_context("/"):
            public = api._publicize(original)
        self.assertNotIn("fact_check_status", public)
        self.assertTrue(public["seo_reviewed"])
        self.assertTrue(is_indexable(public))
        self.assertIn("max-image-preview:large", api._article_html(public))
        self.assertNotIn('noindex,follow', api._article_html(public))

        unreviewed = dict(original, fact_check_status="pending")
        with api.app.test_request_context("/"):
            public_unreviewed = api._publicize(unreviewed)
        self.assertFalse(public_unreviewed["seo_reviewed"])
        self.assertFalse(is_indexable(public_unreviewed))
        self.assertIn("noindex,follow", api._article_html(public_unreviewed))

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

    def test_plural_sitemap_alias_is_one_hop_to_canonical(self):
        config=json.loads(Path("vercel.json").read_text())
        self.assertIn({"source":"/sitemaps.xml","destination":"/sitemap.xml","permanent":True},config["redirects"])

    def test_static_sitemaps_use_only_www_canonical(self):
        index=ET.fromstring(sitemap_index_xml())
        static=ET.fromstring(static_sitemap_xml())
        self.assertEqual(len(index),3)
        for loc in [x[0].text for x in index]+[x[0].text for x in static]:
            self.assertTrue(loc.startswith("https://www.politicshub.in/"),loc)
        self.assertIn("https://www.politicshub.in/",[x[0].text for x in static])
        self.assertIn("https://www.politicshub.in/topics/",[x[0].text for x in static])

    def test_served_static_sitemap_matches_generator_exactly(self):
        # Vercel serves this file directly; changing only the Python generator
        # does NOT update the URLs actually seen by crawlers.
        served=Path("public/static-sitemap.xml").read_text(encoding="utf-8").strip()
        generated=static_sitemap_xml()
        self.assertEqual(served,generated)
        self.assertEqual(len(ET.fromstring(served)),26)

    def test_active_category_landings_are_discoverable_but_retired_desks_are_not(self):
        from app.seo_indexing import STATIC_PAGES
        locations={node[0].text for node in ET.fromstring(static_sitemap_xml())}
        for path in ("/india/", "/politics/", "/world/", "/hindi/", "/maharashtra/"):
            self.assertIn(path,STATIC_PAGES)
            self.assertIn(SITE_ORIGIN+path,locations)
        for desk in ("business","technology","sports","entertainment","science","health"):
            self.assertNotIn(SITE_ORIGIN+"/"+desk+"/",locations)

    def test_marathi_maharashtra_landing_has_source_links_and_correct_schema(self):
        page=Path("public/maharashtra/index.html").read_text(encoding="utf-8")
        self.assertIn('lang="mr"',page)
        self.assertIn('rel="canonical" href="'+SITE_ORIGIN+'/maharashtra/"',page)
        self.assertIn("TV9 मराठी",page)
        self.assertIn("ABP माझा",page)
        self.assertIn("www.tv9marathi.com/maharashtra",page)
        self.assertIn("marathi.abplive.com/news/maharashtra",page)
        self.assertIn('data-i18n="regionIntroBody"',page)
        self.assertNotIn("LocalBusiness",page)
        match=re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',page)
        self.assertIsNotNone(match)
        structured=json.loads(match.group(1))
        page_nodes=[node for node in structured["@graph"] if node["@type"]=="CollectionPage"]
        self.assertEqual(len(page_nodes),1)
        self.assertEqual(page_nodes[0]["url"],SITE_ORIGIN+"/maharashtra/")
        self.assertEqual(page_nodes[0]["inLanguage"],["mr","en"])

    def test_google_news_language_is_not_hardcoded_to_english(self):
        now=datetime.now(timezone.utc)
        english=example()
        hindi=dict(example(),id=45,url="https://example.org/news/45",category="hindi",
                   title="Latest India government minister policy news report")
        marathi=dict(example(),id=46,url="https://example.org/news/46",source_name="TV9 Marathi",
                     title="महाराष्ट्रातील आजच्या महत्त्वाच्या बातम्या शहरातील राजकीय घडामोडी")
        xml=google_news_sitemap_xml([english,hindi,marathi],now=now)
        root=ET.fromstring(xml)
        ns={"u":"http://www.sitemaps.org/schemas/sitemap/0.9",
            "n":"http://www.google.com/schemas/sitemap-news/0.9"}
        all_languages=[node.find("n:news/n:publication/n:language",ns).text
                       for node in root.findall("u:url",ns)]
        self.assertCountEqual(all_languages,["en","hi","mr"])

    def test_article_and_sitemap_fallback_on_postgres_error(self):
        from psycopg import OperationalError
        row = example()
        with patch.object(api, "db", side_effect=OperationalError("temporary outage")), \
             patch.object(api, "_snapshot_rows", return_value=[row]), \
             patch.object(api, "_archive_rows", return_value=[]), \
             patch.object(api, "_hindi_rows", return_value=[]), \
             patch.object(api, "_official_exam_rows", return_value=[]):
            self.assertEqual(len(api._published_sitemap_rows()), 1)
            with api.app.test_request_context("/"):
                found = api._public_row_by_id(row["id"])
            self.assertIsNotNone(found)
            self.assertEqual(found["id"], row["id"])

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
            self.assertIn('noindex,follow',noindex.get_data(as_text=True))
            self.assertNotIn("pagead2.googlesyndication.com",noindex.get_data(as_text=True))
            self.assertIn("not an independently reported",noindex.get_data(as_text=True))

    def test_static_pages_canonical_match_sitemap(self):
        from app.seo_indexing import STATIC_PAGES
        for path in STATIC_PAGES:
            if path=="/archive/":
                continue  # Server-rendered dynamic archive, not a static HTML file.
            if path in {"/india/", "/politics/", "/world/", "/hindi/"}:
                with patch.object(api, "_public_rows_for_section", return_value=[]):
                    response=api.app.test_client().get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('<link rel="canonical" href="'+SITE_ORIGIN+path+'">', response.get_data(as_text=True))
                continue
            source_path = "public/index.html" if path=="/" else "public"+path
            if source_path.endswith("/"):
                source_path += "index.html"
            source=Path(source_path).read_text(encoding="utf-8")
            expected='<link rel="canonical" href="'+SITE_ORIGIN+path+'">'
            with self.subTest(path=path):
                self.assertIn(expected,source)

    def test_long_headline_sitemap_matches_rendered_page_canonical(self):
        row=example()
        row["title"]="World News Finnish Envoy Praises the Courage of the Air Crew During an International Flight Incident and Says That Every Human Life Saved Is Highly Appreciated"
        with api.app.test_request_context("/api/seo-news-sitemap"):
            displayed=api._publicize(row)
            expected=SITE_ORIGIN+canonical_path(displayed)
        with patch.object(api,"_published_sitemap_rows",return_value=[row]):
            response=api.app.test_client().get("/api/seo-news-sitemap")
            self.assertEqual(response.status_code,200)
            nodes=ET.fromstring(response.data)
            self.assertEqual(len(nodes),1)
            self.assertEqual(nodes[0][0].text,expected)
        with patch.object(api,"_public_row_by_id",return_value=displayed):
            page=api.app.test_client().get("/api/seo-article"+canonical_path(displayed))
            self.assertEqual(page.status_code,200)
            self.assertIn('<link rel="canonical" href="'+expected+'">',page.get_data(as_text=True))

    def test_archive_works_without_long_form_articles(self):
        with patch.object(api,"_published_sitemap_rows",return_value=[]):
            response=api.app.test_client().get("/api/seo-archive")
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertNotIn('href="/nana-patekar-tribute.html"',page)
        self.assertIn("noindex,follow",page)
        self.assertNotIn("pagead2.googlesyndication.com",page)

    def test_archive_discovery_links_match_article_canonicals(self):
        one=example()
        second=dict(one,id=45,url="https://example.org/news/45",title="India announces public school infrastructure investment for rural districts")
        with patch.object(api,"_published_sitemap_rows",return_value=[one,second,dict(one,id=46,url="https://example.org/news/46",bot_article="short")]):
            response=api.app.test_client().get("/api/seo-archive")
            self.assertEqual(response.status_code,200)
            html_text=response.get_data(as_text=True)
            self.assertIn('<link rel="canonical" href="'+SITE_ORIGIN+'/archive/">',html_text)
            self.assertIn('<h1>News Archive</h1>',html_text)
            self.assertIn('href="'+canonical_path(one)+'"',html_text)
            self.assertIn('href="'+canonical_path(second)+'"',html_text)
            self.assertNotIn("/46-",html_text)
            self.assertEqual(api.app.test_client().get("/api/seo-archive?page=2").status_code,404)
        self.assertIn("href=\"/archive/\"",Path("public/index.html").read_text())
        config=json.loads(Path("vercel.json").read_text())
        self.assertIn({"source":"/archive/","destination":"/api/seo-archive"},config["rewrites"])
        self.assertNotIn("href=\"/nana-patekar-tribute.html\"",html_text)
        sm=static_sitemap_xml()
        self.assertIn(SITE_ORIGIN+"/archive/",sm)

    def test_google_news_sitemap_fresh_only_with_required_tags(self):
        now=datetime(2026,10,8,10,0,tzinfo=timezone.utc)
        row=example()
        row["published_at"]="2026-10-08T08:00:00+00:00"
        xml=google_news_sitemap_xml([row],now=now)
        root=ET.fromstring(xml)
        self.assertEqual(len(root),1)
        self.assertEqual(root.attrib.get("xmlns:news"),None)  # Namespace parsed by ElementTree.
        ns={"s":"http://www.sitemaps.org/schemas/sitemap/0.9","n":"http://www.google.com/schemas/sitemap-news/0.9"}
        titles=[x.text for x in root.findall(".//n:title",ns)]
        self.assertIn(row["title"],titles)
        self.assertNotIn("Nana Patekar dies at 75 in Goa, leaving a lasting cinema legacy",titles)
        self.assertEqual(len(root.findall(".//n:publication_date",ns)),1)
        self.assertEqual(len(root.findall(".//n:name",ns)),1)
        self.assertEqual(len(root.findall(".//n:language",ns)),1)
        later=google_news_sitemap_xml([row],now=now+timedelta(days=4))
        self.assertEqual(len(ET.fromstring(later)),0)

    def test_withheld_reports_are_not_promoted_or_in_sitemaps(self):
        for name in ('nana-patekar-tribute.html', 'elon-musk-ambani-starlink.html'):
            page = Path('public', name).read_text()
            self.assertIn('noindex,follow', page)
            self.assertNotIn('NewsArticle', page)
            self.assertNotIn(name, Path('public/index.html').read_text())
            with patch.object(api, '_published_sitemap_rows', return_value=[example()]):
                for path in ('/api/seo-news-sitemap', '/api/seo-google-news'):
                    response = api.app.test_client().get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn(name, response.get_data(as_text=True))
        feed = Path('public/assets/site.js').read_text()
        self.assertNotIn('const NANA_TRIBUTE=', feed)
        self.assertNotIn('const MUSK_STARLINK=', feed)

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


    def test_server_rendered_homepage_and_metadata(self):
        config=json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        self.assertNotIn({"source":"/","destination":"/api/seo-home"}, config["rewrites"])
        with patch.object(api,"_public_rows_for_section",return_value=[example()]):
            response=api.app.test_client().get("/api/seo-home")
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertIn("<h1>",page)
        self.assertIn('<link rel="canonical" href="'+SITE_ORIGIN+'/"',page)
        self.assertIn('type="application/ld+json"',page)
        self.assertIn('"CollectionPage"',page)
        description=re.search(r'<meta name="description" content="([^"]+)"',page)
        self.assertIsNotNone(description)
        self.assertGreater(len(description.group(1)),70)

    def test_static_home_fallback_and_article_logo(self):
        source=Path("public/index.html").read_text(encoding="utf-8")
        self.assertIn("<h1",source)
        self.assertIn('property="og:image"',source)
        self.assertIn('type="application/ld+json"',source)
        with patch.object(api,"_public_row_by_id",return_value=example()):
            response=api.app.test_client().get("/api/seo-article"+canonical_path(example()))
        self.assertEqual(response.status_code,200)
        self.assertIn('"ImageObject"',response.get_data(as_text=True))



if __name__=="__main__":
    unittest.main()
