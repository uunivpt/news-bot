import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from api.index import app, _article_html


ADSENSE_URL = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533'


class AdSenseScripts(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.in_head = False
        self.scripts = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        if tag == 'script' and 'adsbygoogle.js' in dict(attrs).get('src', ''):
            self.scripts.append((self.in_head, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class UIAdSenseTests(unittest.TestCase):
    def assert_adsense_head(self, page):
        scripts = AdSenseScripts(page).scripts
        self.assertEqual(len(scripts), 1)
        in_head, attrs = scripts[0]
        self.assertTrue(in_head)
        self.assertEqual(attrs['src'], ADSENSE_URL)
        self.assertIn('async', attrs)
        self.assertEqual(attrs.get('crossorigin'), 'anonymous')
        self.assertNotIn('/assets/adsense.js', page)

    def test_static_news_documents_include_one_async_adsense_script(self):
        client = app.test_client()
        for path in ['/elon-musk-ambani-starlink.html', '/nana-patekar-tribute.html']:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assert_adsense_head(response.get_data(as_text=True))

    def test_server_rendered_news_documents_include_one_async_adsense_script(self):
        row = {
            'id': 44, 'title': 'India Parliament passes a new public services law',
            'category': 'india', 'status': 'published', 'public_source': True,
            'source_type': 'rss', 'url': 'https://example.org/news/44',
            'source_name': 'Source News', 'published_at': '2026-10-15T08:00:00Z',
            'summary': 'Official sources report changes to public services after discussion in Parliament. ' * 2,
            'bot_article': 'Official sources described the parliamentary debate and changes to public services. ' * 8,
        }
        client = app.test_client()
        with patch('api.index._public_rows_for_section', return_value=[row]), \
             patch('api.index._public_row_by_id', return_value=row), \
             patch('api.index._published_sitemap_rows', return_value=[row]):
            for path in ['/india/', '/india/44-india-parliament-passes-a-new-public-services-law']:
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assert_adsense_head(response.get_data(as_text=True))
                    self.assertIn('https://pagead2.googlesyndication.com', response.headers['Content-Security-Policy'])
            # A collection/links-only archive must not be monetized like an article.
            archive = client.get('/archive/')
            self.assertEqual(archive.status_code, 200)
            self.assertEqual(AdSenseScripts(archive.get_data(as_text=True)).scripts, [])

    def test_utility_and_admin_documents_do_not_include_advertising(self):
        client = app.test_client()
        for path in ['/privacy.html', '/cookies.html', '/newsletter.html', '/settings.html', '/admin/', '/admin/setup.html']:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(AdSenseScripts(response.get_data(as_text=True)).scripts, [])

    def test_public_files_are_not_redirected_to_category_404(self):
        client = app.test_client()
        for path in ['index.html','about.html','privacy.html','contact.html','newsletter.html','story.html','ads.txt']:
            response = client.get('/'+path)
            assert response.status_code == 200, path
        assert client.get('/api/seo-section/not-a-section').status_code == 404
        assert client.get('/missing.html').status_code == 404


    def test_shared_assets_and_verification_are_present(self):
        root = Path('public')
        for path in root.glob('*.html'):
            if path.name.startswith('newsroom-console'):
                continue
            html = path.read_text()
            assert '/assets/polish.css?v=' in html, path
            assert '/assets/ui.js?v=phui30' in html, path
            assert 'PH.bindChrome()' not in html
            assert 'googletagmanager.com/gtag/js' not in html
        home = (root/'index.html').read_text()
        assert 'name="google-adsense-account" content="ca-pub-1752666987448533"' in home
        assert 'pub-1752666987448533' in (root/'ads.txt').read_text()
        self.assert_adsense_head(home)


    def test_google_ads_page_view_conversion_setup(self):
        code = (Path('public') / 'assets/ui.js').read_text()
        self.assertIn("gtag/js?id=G-2HVZQST08G", code)
        self.assertIn("'config', 'G-2HVZQST08G'", code)
        self.assertIn("'config', 'AW-18495731647'", code)
        self.assertIn("'send_to': 'AW-18495731647/4NrBCOKXz6UdEL_vufNE'", code)
        self.assertIn("path === '/' || path === '/index.html'", code)
        self.assertEqual(code.count("'event', 'conversion'"), 1)
        self.assertIn("!path.startsWith('/admin')", code)
        self.assertIn("google-analytics.com", (Path('api') / 'index.py').read_text())

    def test_article_summary_keeps_the_complete_sentence(self):
        summary = 'Context matters. ' * 30 + 'This final sentence must remain intact.'
        row = {'id':1, 'title':'Report', 'category':'india', 'summary':summary, 'article':summary, 'source_name':'Test', 'published_at':'2026-10-13T12:00:00Z'}
        with app.test_request_context('/'):
            page = _article_html(row)
        self.assertIn('<p class="dek">'+summary+'</p>', page)

    def test_admin_entrypoint_and_setup_scripts_load_under_csp(self):
        client = app.test_client()
        for path in ['/admin/', '/admin/setup.html', '/newsroom-console-8x4m7k2q.html']:
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn('<script>', response.get_data(as_text=True))
