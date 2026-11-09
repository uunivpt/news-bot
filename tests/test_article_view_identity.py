import unittest
from unittest.mock import MagicMock, patch
from api import index as api


class ArticleViewIdentityTests(unittest.TestCase):
    def test_canonical_number_resolves_before_increment(self):
        database = MagicMock()
        database.increment_view.return_value = True
        with patch.object(api, 'db', return_value=database), \
             patch.object(api, '_resolve_news_id', return_value=42) as resolve, \
             patch.object(api, '_public_rate_allowed', return_value=True):
            result = api.app.test_client().post('/api/news/617958005290/view')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['tracked'])
        resolve.assert_called_once_with(617958005290)
        database.increment_view.assert_called_once_with(42)
        database.close.assert_called_once()

    def test_internal_id_remains_compatible(self):
        database = MagicMock()
        database.increment_view.return_value = True
        with patch.object(api, 'db', return_value=database), \
             patch.object(api, '_resolve_news_id') as resolve, \
             patch.object(api, '_public_rate_allowed', return_value=True):
            result = api.app.test_client().post('/api/news/42/view')
        self.assertEqual(result.status_code, 200)
        database.increment_view.assert_called_once_with(42)
        resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
