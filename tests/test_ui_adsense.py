import unittest
from pathlib import Path
from unittest.mock import patch
from api.index import app, _article_html


class UIAdSenseTests(unittest.TestCase):
    def test_ads_disabled_until_both_explicit_release_flags(self):
        client = app.test_client()
        for flags, enabled in [({}, False), ({'ADSENSE_ENABLED':'true'}, False), ({'ADSENSE_CMP_READY':'true'}, False), ({'ADSENSE_ENABLED':'true','ADSENSE_CMP_READY':'true'}, True)]:
            with patch.dict('os.environ', flags, clear=True):
                response = client.get('/api/ads-config')
            assert response.status_code == 200
            assert response.json == {'enabled': enabled, 'client':'ca-pub-1752666987448533'}
            assert response.headers['Cache-Control'] == 'no-store'


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
            assert '/assets/polish.css?v=phui19' in html, path
            assert '/assets/ui.js?v=phui19' in html, path
            assert 'PH.bindChrome()' not in html
            assert 'googletagmanager.com/gtag/js' not in html
        home = (root/'index.html').read_text()
        assert 'name="google-adsense-account" content="ca-pub-1752666987448533"' in home
        assert 'pub-1752666987448533' in (root/'ads.txt').read_text()

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
