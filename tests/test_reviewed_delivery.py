import unittest
from unittest.mock import Mock, patch

from api import index as api
from app import reviewed_delivery as delivery


class ReviewedDeliveryTests(unittest.TestCase):
    def setUp(self):
        delivery._states.clear()

    def test_immutable_published_copy_is_available_before_next_deployment(self):
        revision = 'a' * 40
        row = dict(id=441, title='Historical public source report with original publication time',
                   url='https://example.org/report', status='published', public_source=True,
                   category='india', summary='A historical source summary that remains attributed to the original publisher.',
                   bot_article='A historical source summary that remains attributed to the original publisher.',
                   published_at='2026-01-01T00:00:00Z')
        response = Mock(content=b'[]')
        response.json.return_value = [row]
        with patch('requests.get', return_value=response) as get, \
             api.app.test_request_context('/india/441-report?v='+revision), \
             patch.dict('os.environ', {'VERCEL': '1'}):
            result = api._public_row_by_id(441)
        self.assertEqual(result['id'], 441)
        self.assertEqual(result['published_at_iso'], '2026-01-01T00:00:00Z')
        self.assertFalse(result['ads_eligible'])
        self.assertIn('/'+revision+'/public/news-data.json', get.call_args.args[0])

    def test_revision_is_not_a_user_controlled_url_or_path(self):
        with patch('requests.get') as get:
            self.assertEqual(delivery.reviewed_rows('/missing', '../main'), [])
            self.assertEqual(delivery.reviewed_rows('/missing', 'https://example.org/'), [])
        get.assert_not_called()

    def test_unpublished_or_private_records_are_never_accepted(self):
        response = Mock(content=b'[]')
        response.json.return_value = [dict(id=1, title='Private report', status='pending',
                                         public_source=False, url='https://example.org/')]
        with patch('requests.get', return_value=response):
            self.assertEqual(delivery.reviewed_rows('/missing', 'b'*40), [])

    def test_private_delivery_status_endpoint_requires_login(self):
        with patch.object(api, 'db') as database:
            result = api.app.test_client().get('/api/admin/story/441/delivery')
        self.assertEqual(result.status_code, 401)
        database.assert_not_called()

    def test_historical_copy_outside_latest_window_uses_same_immutable_revision(self):
        revision = 'c' * 40
        latest, archived = Mock(content=b'[]'), Mock(content=b'[]')
        latest.json.return_value = []
        archived.json.return_value = [dict(id=900, title='Original historical report',
            status='published', public_source=True, url='https://example.org/history')]
        with patch('requests.get', side_effect=[latest, archived]) as get:
            row = delivery.reviewed_article('/missing', 900, revision)
        self.assertEqual(row['id'], 900)
        self.assertTrue(all('/'+revision+'/' in call.args[0] for call in get.call_args_list))
        self.assertTrue(get.call_args.args[0].endswith('/mobile-reviewed.json'))

    def test_canonical_redirect_keeps_immutable_publication_revision(self):
        revision = 'd' * 40
        row = dict(id=900, title='Original public transport report', category='india')
        with patch.object(api, '_public_row_by_id', return_value=row):
            result = api.app.test_client().get('/india/900-old-title?v='+revision)
        self.assertEqual(result.status_code, 301)
        self.assertEqual(result.headers['Location'],
                         api.SITE_ORIGIN+api.article_path(row)+'?v='+revision)
