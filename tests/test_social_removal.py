"""Retired publishing endpoints stay unavailable, including with old stored state."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import index as api
from app.database import NewsDatabase
from app.models import NewsItem
from app.phase_system import manager_route
from scripts import auto_publish


class SocialRemovalTests(unittest.TestCase):
    def test_website_publishing_still_runs_with_stale_social_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'test.db')
            db = NewsDatabase(path=path)
            db.insert(NewsItem(source_name='Source News', source_type='rss',
                               title='Council announces funding for public school repairs',
                               url='https://example.org/school-repairs', category='india',
                               summary='The council approved funding for repairs to public schools.',
                               public_source=True))
            with patch.object(auto_publish, 'NewsDatabase', return_value=db), \
                 patch.object(auto_publish, 'prepare_content', return_value=True), \
                 patch.dict('os.environ', {'PUBLISH_WEBSITE': 'true', 'PUBLISH_TO_INSTAGRAM': 'true',
                                          'MAX_ITEMS': '1', 'BOT_REPAIR_ITEMS': '0'}, clear=True):
                auto_publish.main()
            db = NewsDatabase(path=path)
            try:
                self.assertEqual(db.get_by_id(1)['status'], 'published')
                receipt = db.conn.execute('SELECT website_published FROM ph_publish_locks WHERE item_id=1').fetchone()
                self.assertEqual(receipt['website_published'], 1)
            finally:
                db.close()

    def test_retired_routes_cannot_queue_or_publish(self):
        client = api.app.test_client()
        with patch.object(api, 'db') as database:
            for path in ['/api/news/1/instagram/queue', '/api/news/1/instagram/retry',
                         '/api/news/1/instagram/publish-now', '/api/news/1/instagram/schedule',
                         '/api/admin/instagram/bulk']:
                self.assertIn(client.post(path, json={}).status_code, (404, 405), path)
            self.assertEqual(client.get('/api/admin/instagram/analytics').status_code, 404)
            database.assert_not_called()

    def test_old_settings_cannot_reenable_retired_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(path=str(Path(folder) / 'test.db'))
            try:
                db.conn.execute('INSERT INTO admin_settings VALUES (?,?,?)',
                                ('instagram_enabled', 'true', NewsItem.now_iso()))
                db.conn.commit()
                self.assertEqual(db.get_settings(), {'website_enabled': 'true'})
                db.set_settings({'instagram_enabled': 'true', 'website_enabled': 'false'})
                self.assertEqual(db.get_settings(), {'website_enabled': 'false'})
            finally:
                db.close()
        with patch.object(api, 'require_admin', return_value=None), \
             patch.object(api, 'require_csrf', return_value=None), \
             patch.object(api, 'db') as database:
            response = api.app.test_client().post('/api/admin/settings', json={'instagram_enabled': True})
            self.assertEqual(response.status_code, 400)
            database.assert_not_called()

    def test_historical_social_fields_are_hidden_for_public_and_admin(self):
        row = {'id': 1, 'title': 'Source report about a new public policy',
               'category': 'india', 'summary': 'A source-linked report.',
               'instagram_status': 'processing', 'instagram_error': 'old provider error',
               'reel_cloudinary_url': 'https://example.org/old-video.mp4'}
        with api.app.test_request_context('/'):
            for is_admin in (False, True):
                with patch.object(api, 'admin_ok', return_value=is_admin):
                    output = api._publicize(row)
                    self.assertFalse(any(key.startswith(('instagram_', 'reel_cloudinary_')) for key in output))
        self.assertEqual(manager_route('Government announces policy', 'india', True),
                         manager_route('Government announces policy', 'india', False))

    def test_website_controls_still_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'test.db')
            with patch.object(api, 'require_admin', return_value=None), \
                 patch.object(api, 'require_csrf', return_value=None), \
                 patch.object(api, 'db', side_effect=lambda: NewsDatabase(path=path)):
                client = api.app.test_client()
                for enabled in (False, True):
                    response = client.post('/api/admin/settings', json={'website_enabled': enabled})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['settings']['website_enabled'], str(enabled).lower())
                self.assertEqual(client.post('/api/admin/settings', json={'website_enabled': 'false'}).status_code, 400)
