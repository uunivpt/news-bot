import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from app import article_visuals as visuals
from app.news_numbers import news_number
from api import index as api


class ArticleVisualTests(unittest.TestCase):
    def setUp(self):
        self.registry_patch = patch.object(visuals, 'REGISTRY', Path(__file__).parent / 'fixtures' / 'article-visuals-2024.json')
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        visuals.registry.cache_clear()
        self.data = json.loads(visuals.REGISTRY.read_text())['datasets'][0]

    def tearDown(self):
        visuals.registry.cache_clear()

    def test_reviewed_data_retains_source_precision_dates_and_identity(self):
        data = visuals.validate(self.data)
        self.assertEqual(data['points'][-1]['value'], 7.09927893176518)
        self.assertEqual(data['source']['updated_on'], '2026-10-08')
        self.assertEqual(data['source']['retrieved_on'], '2026-11-10')
        self.assertEqual(visuals.for_article(17484337260322), data)
        self.assertEqual(visuals.for_article(news_number({'id': 17484337260322})), data)
        self.assertIsNone(visuals.for_article(987654321))

    def test_rejects_unreviewed_ambiguous_or_invalid_numeric_data(self):
        for key, value in [('reviewed', False), ('points', []), ('article_ids', ['../123']), ('id', 'bad" onclick="x')]:
            with self.subTest(key=key):
                raw = copy.deepcopy(self.data);raw[key] = value
                self.assertIsNone(visuals.validate(raw))
        for bad in (True, None, '7.1', float('nan'), float('inf'), 1e20):
            raw = copy.deepcopy(self.data);raw['points'][0]['value'] = bad
            self.assertIsNone(visuals.validate(raw))
        raw = copy.deepcopy(self.data);raw['points'][1]['label'] = raw['points'][0]['label']
        self.assertIsNone(visuals.validate(raw))
        raw = copy.deepcopy(self.data);raw['source']['updated_on'] = '2027-01-01'
        self.assertIsNone(visuals.validate(raw))

    def test_rejects_unsafe_source_and_licence_urls(self):
        for field in ('url', 'data_url', 'license_url'):
            for bad in ('javascript:alert(1)', 'http://example.com', 'https://127.0.0.1/x', 'https://user:password@example.org', ''):
                raw = copy.deepcopy(self.data);raw['source'][field] = bad
                self.assertIsNone(visuals.validate(raw), (field, bad))

    def test_text_is_escaped_and_unknown_fields_never_become_markup(self):
        raw = copy.deepcopy(self.data)
        raw['title'] = '<img src=x onerror=alert(1)>'
        raw['points'][0]['label'] = '</text><script>alert(1)</script>'
        raw['html'] = '<script>arbitraryMarkup()</script>'
        document = visuals.render(visuals.validate(raw))
        self.assertIn('&lt;img', document)
        self.assertNotIn('<script>', document)
        self.assertNotIn('arbitraryMarkup', document)

    def test_axis_preserves_zero_and_negative_values_and_table_precision(self):
        document = visuals.render(visuals.validate(self.data))
        self.assertIn('7.10%', document)
        self.assertIn('-0.11', document)
        self.assertIn('percentage points', document)
        self.assertIn('7.09927893176518', document)
        zero = float(re.search(r'class="data-zero".*?y1="([0-9.]+)"', document)[1])
        self.assertGreater(zero, 30)
        self.assertLess(zero, 270)
        self.assertRegex(document, r'data-negative.*?y="' + f'{zero:.2f}' + '"')
        for value in (0, 4, -4, 1e-300):
            data = visuals.validate(self.data)
            for point in data['points']:point['value'] = value
            self.assertNotRegex(visuals.render(data), r'\bnan\b|\binf\b')

    def test_missing_broken_and_conflicting_registries_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'visuals.json'
            for content in (None, '{bad', '[]', json.dumps({'version': 1, 'datasets': [self.data, self.data]})):
                visuals.registry.cache_clear()
                if content is not None:path.write_text(content)
                with patch.object(visuals, 'REGISTRY', path):
                    self.assertEqual(visuals.registry(), {})

    def test_public_endpoint_needs_no_database_and_uses_only_reviewed_registry(self):
        client = api.app.test_client()
        with patch.object(api, 'db', side_effect=AssertionError('Must not open a database')), patch.object(api, '_public_rate_allowed', return_value=True), patch.object(api,'article',return_value=({'error':'not found'},404)):
            found = client.get('/api/article-visuals/17484337260322')
            missing = client.get('/api/article-visuals/9999999')
        self.assertEqual(found.status_code, 200)
        self.assertIn('World Bank', found.json['html'])
        self.assertIn('s-maxage=300', found.headers['Cache-Control'])
        self.assertEqual(missing.json, {'html': ''})

    def test_renderer_retains_database_row_mapping_compatibility(self):
        import sqlite3
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT 17484337260322 AS id, ? AS title, ? AS category',
                                 ('Database mapping fixture', 'india')).fetchone()
        with api.app.test_request_context('/'):
            document = api._article_html(row)
        connection.close()
        self.assertIn('Database mapping fixture', document)
        self.assertIn('World Bank', document)

    def test_canonical_article_keeps_publication_and_source_and_works_without_js(self):
        row = {'id': 17484337260322, 'title': 'India GDP growth context', 'category': 'india',
               'summary': 'A sourced report.', 'article': 'Article text remains intact.',
               'published_at': '2026-10-11T05:03:28.576032Z', 'source_type': 'rss',
               'source_name': 'Original publisher', 'url': 'https://example.org/report'}
        with api.app.test_request_context('/'):
            document = api._article_html(row)
        self.assertIn('Article text remains intact.', document)
        self.assertIn('2026-10-11T05:03:28.576032Z', document)
        self.assertIn('Original publisher', document)
        self.assertIn('<svg', document)
        self.assertIn('<table>', document)
        self.assertIn('article-data.js?v=4', document)
        with api.app.test_request_context('/'):
            document = api._article_html(dict(row, id=99))
        self.assertNotIn('article-data.js', document)
        self.assertNotIn('<svg', document)


if __name__ == '__main__':
    unittest.main()
