import copy
import csv
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from app import article_visuals as visuals
from app.figure_downloads import article_csv, dataset_csv, text_cell
from app.news_numbers import news_number
from api import index as api


def records(content):
    return list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))


def story(text, **fields):
    return {'id': 991, 'title': 'Source report', 'article': text, 'category': 'india',
            'status': 'published', 'source_name': 'Example News',
            'url': 'https://example.org/report', 'published_at': '2026-11-10T05:00:00Z', **fields}


class FigureDownloadTests(unittest.TestCase):
    def setUp(self):
        registry = patch.object(visuals, 'REGISTRY', Path(__file__).parent / 'fixtures' / 'article-visuals-2024.json')
        registry.start()
        self.addCleanup(registry.stop)
        visuals.registry.cache_clear()
        self.addCleanup(visuals.registry.cache_clear)
        rate = patch.object(api, '_public_rate_allowed', return_value=True)
        rate.start()
        self.addCleanup(rate.stop)
        self.data = visuals.catalog()[0]
        self.client = api.app.test_client()

    def test_reviewed_export_preserves_every_observation_precision_and_provenance(self):
        content = dataset_csv(self.data)
        self.assertTrue(content.startswith('\ufeff'))
        rows = records(content)
        self.assertEqual([row['value'] for row in rows], [str(p['value']) for p in self.data['points']])
        self.assertEqual([row['observation'] for row in rows], [p['label'] for p in self.data['points']])
        self.assertTrue(any(float(row['value']) < 0 for row in rows))
        for row in rows:
            self.assertEqual(row['unit'], '%')
            self.assertEqual(row['source_url'], self.data['source']['url'])
            self.assertEqual(row['original_data_url'], self.data['source']['data_url'])
            self.assertEqual(row['source_updated_on'], '2026-10-08')
            self.assertEqual(row['source_retrieved_on'], '2026-11-10')
            self.assertEqual(row['licence_url'], self.data['source']['license_url'])
            self.assertEqual(row['article_published_at'], '')

    def test_story_export_retains_reported_precision_context_and_article_publication(self):
        row = story('Year | GDP growth (%)\n2023 | -2.50001234%\n2024 | 7.6001234%')
        rows = records(article_csv(row, 'https://www.politicshub.in/india/123'))
        self.assertEqual([r['value'] for r in rows], ['-2.50001234', '7.6001234'])
        self.assertEqual([r['observation'] for r in rows], ['2023', '2024'])
        self.assertEqual(rows[0]['article_published_at'], row['published_at'])
        self.assertEqual(rows[0]['source_url'], row['url'])
        self.assertEqual(rows[0]['article_url'], 'https://www.politicshub.in/india/123')
        self.assertIn('Original publisher rights apply', rows[0]['licence'])

    def test_cards_export_only_their_existing_figures_including_marathi_and_index_precision(self):
        for text, expected in [('AQI was 344.123456 in Delhi.', ['344.123456']),
                               ('जागा: पक्ष अ: ५० जागा; पक्ष ब: ४० जागा.', ['50', '40']),
                               ('Budget: Schools: ₹1,23,456 crore; Hospitals: ₹40 crore.', ['1,23,456', '40'])]:
            with self.subTest(text=text):
                rows = records(article_csv(story(text), 'https://www.politicshub.in/india/123'))
                self.assertEqual([r['value'] for r in rows], expected)
                self.assertNotIn('World Bank', str(rows))

    def test_omitted_ranges_and_bounds_do_not_reappear_in_downloads(self):
        for text in ['AQI was 300–400 in Delhi.', 'Vote share: A: at least 55%; B: at most 45%.', 'No numerical observations.']:
            self.assertIsNone(article_csv(story(text), 'https://www.politicshub.in/india/123'))
        rows = records(article_csv(story('Seat tally: A: 50 seats; B: 40 seats; C: at least 10 seats.'), 'https://www.politicshub.in/india/123'))
        self.assertEqual([r['value'] for r in rows], ['50', '40'])

    def test_csv_quotes_unicode_commas_newlines_and_formula_text_but_keeps_negative_numbers(self):
        data = copy.deepcopy(self.data)
        data['points'][0] = {'label': '=HYPERLINK("https://example.org")', 'value': -2.5}
        data['description'] = 'मराठी, "quoted"\nnew line'
        data['source']['name'] = '  @SUM(1,2)'
        rows = records(dataset_csv(data))
        self.assertEqual(rows[0]['value'], '-2.5')
        self.assertTrue(rows[0]['observation'].startswith("'="))
        self.assertTrue(rows[0]['source_name'].startswith("'  @"))
        self.assertIn(data['description'], rows[0]['context'])
        for value in ['=1+1', ' +cmd', '-formula', '@SUM(1)', '\tfoo', '\rfoo', '\nfoo']:
            self.assertTrue(text_cell(value).startswith("'"))

    def test_article_export_does_not_copy_private_fields_or_unsafe_source_urls(self):
        row = story('AQI was 344 in Delhi.', url='https://127.0.0.1/private', admin_notes='PRIVATE-DRAFT')
        content = article_csv(row, 'https://www.politicshub.in/india/123')
        self.assertEqual(records(content)[0]['source_url'], '')
        self.assertNotIn('PRIVATE-DRAFT', content)
        self.assertNotIn('127.0.0.1', content)

    def test_dataset_download_is_a_bounded_attachment_without_database_or_provider_requests(self):
        with patch.object(api, 'db', side_effect=AssertionError('No database needed')), patch('requests.get', side_effect=AssertionError('No provider read needed')):
            response = self.client.get('/api/data-desk/' + self.data['id'] + '/csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('charset=utf-8', response.content_type)
        self.assertIn('attachment; filename="politicshub-', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(len(records(response.get_data(as_text=True))), 6)

    def test_registry_article_identity_and_public_number_download_the_same_reviewed_dataset(self):
        for identity in [17484337260322, news_number({'id': 17484337260322})]:
            with patch.object(api, 'article', side_effect=AssertionError('Registry download must be independent of story backend')):
                response = self.client.get('/api/article-visuals/' + str(identity) + '/csv')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), dataset_csv(self.data))

    def test_story_endpoint_requires_public_copy_even_when_editor_is_signed_in(self):
        for state in ['pending', 'rejected', 'draft']:
            with patch.object(api, 'article', return_value=(story('AQI was 344 in Delhi.', status=state), 200)), patch.object(api, 'admin_ok', return_value=True):
                response = self.client.get('/api/article-visuals/991/csv')
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('Content-Disposition', response.headers)
            self.assertNotIn('344', response.get_data(as_text=True))

    def test_public_article_download_uses_canonical_link_and_no_store(self):
        row = story('AQI was 344 in Delhi.')
        with patch.object(api, 'article', return_value=(row, 200)):
            response = self.client.get('/api/article-visuals/991/csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(records(response.get_data(as_text=True))[0]['article_url'], api.SITE_ORIGIN + api.article_path(row))
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_missing_unsupported_and_unavailable_figures_have_no_download_attachment(self):
        self.assertEqual(self.client.get('/api/data-desk/not-a-dataset/csv').status_code, 404)
        for reply, status in [(({'error': 'not found'}, 404), 404), (({'error': 'unavailable'}, 503), 503), ((story('No numerical data.'), 200), 404)]:
            with patch.object(api, 'article', return_value=reply):
                response = self.client.get('/api/article-visuals/991/csv')
            self.assertEqual(response.status_code, status)
            self.assertNotIn('Content-Disposition', response.headers)

    def test_rate_limit_applies_to_both_download_paths(self):
        with patch.object(api, '_public_rate_allowed', return_value=False):
            for path in ['/api/data-desk/' + self.data['id'] + '/csv', '/api/article-visuals/991/csv']:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers['Retry-After'], '60')

    def test_server_markup_exposes_links_without_script_and_omits_them_without_figures(self):
        from app.story_visuals import render
        self.assertIn('/api/data-desk/' + self.data['id'] + '/csv', visuals.render(self.data))
        self.assertIn('/api/article-visuals/991/csv', render(story('AQI was 344 in Delhi.')))
        self.assertEqual(render(story('AQI was 300–400.')), '')


if __name__ == '__main__':
    unittest.main()
