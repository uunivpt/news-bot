"""Public hosted routes must distinguish saved public copy from cloud drafts."""
import unittest
from unittest.mock import patch

import test_hosted_admin as hosted_fixture


class HostedPublicPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hosted_fixture.HostedAdminTests.setUpClass()

    def setUp(self):
        self.fixture = hosted_fixture.HostedAdminTests(
            'test_backend_selection_is_explicit_and_retains_legacy_feed_only_guard')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_unreviewed_published_cloud_import_is_absent_from_every_public_reader(self):
        fixture = self.fixture
        private = dict(fixture.source_report(730099), title='Confidential legacy import test copy',
                       url='https://example.org/private-legacy-import',
                       bot_article='Confidential unreviewed legacy manuscript. ' * 20)
        fixture.store_cloud_report(private, status='published', approved=False)
        database = fixture.local_database()
        try:
            database.update(private['id'], public_source=0)
            database.conn.execute('UPDATE news_items SET view_count=500 WHERE id=?', (private['id'],))
            database.conn.commit()
        finally:
            database.close()
        public = fixture.source_report()
        public['bot_article'] *= 8
        with fixture.public_sources([public]):
            for path in ('/api/news/730099', '/india/' + hosted_fixture.news_number(private)):
                self.assertEqual(fixture.client.get(path).status_code, 404, path)
            for path in ('/api/news', '/api/search?q=Confidential', '/api/trending',
                         '/api/breaking', '/news-sitemap.xml', '/archive/'):
                response = fixture.client.get(path)
                self.assertEqual(response.status_code, 200, (path, response.data))
                self.assertNotIn(private['title'], response.get_data(as_text=True), path)
                self.assertNotIn(private['bot_article'], response.get_data(as_text=True), path)
        fixture.bridge_transport.assert_not_called()

    def test_untouched_pending_cloud_import_keeps_existing_public_archive(self):
        fixture = self.fixture
        archive = dict(fixture.source_report(730098), title='Previously public archival policy report')
        private = dict(archive, title='Unreviewed replacement cloud manuscript',
                       bot_article='Cloud working text must stay private.')
        fixture.store_cloud_report(private, status='pending', approved=False)
        with fixture.public_sources([]), \
             patch.object(hosted_fixture.api.public_archive, 'by_id',
                          side_effect=lambda key: archive if str(key) == str(archive['id']) else None), \
             patch.object(hosted_fixture.api.public_archive, 'rows', return_value=[archive]):
            response = fixture.client.get('/api/news/' + str(archive['id']))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn(archive['bot_article'], response.json['article'])
            search = fixture.client.get('/api/search?q=archival')
            self.assertIn(archive['id'], [row['id'] for row in search.json])
            self.assertNotIn(private['title'], search.get_data(as_text=True))

    def test_distinct_approved_manual_article_can_cite_archive_without_replacing_it(self):
        fixture = self.fixture
        archive = dict(fixture.source_report(730096), title='Previously public source archival report')
        manual = dict(archive, id=730097, source_type='manual',
                      title='Separately approved manual editorial report',
                      bot_article='Distinct approved editorial article citing the same public evidence.')
        fixture.store_cloud_report(manual, status='published', approved=True)
        with fixture.public_sources([]), \
             patch.object(hosted_fixture.api.public_archive, 'by_id',
                          side_effect=lambda key: archive if str(key) == str(archive['id']) else None), \
             patch.object(hosted_fixture.api.public_archive, 'rows', return_value=[archive]):
            source = fixture.client.get('/api/news/' + str(archive['id']))
            editorial = fixture.client.get('/api/news/' + str(manual['id']))
            self.assertEqual(source.status_code, 200, source.data)
            self.assertEqual(editorial.status_code, 200, editorial.data)
            self.assertIn(archive['bot_article'], source.json['article'])
            self.assertNotIn(manual['bot_article'], source.json['article'])
            self.assertIn(manual['bot_article'], editorial.json['article'])
            search = fixture.client.get('/api/search?q=archival')
            self.assertIn(archive['id'], [row['id'] for row in search.json])
        fixture.bridge_transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
