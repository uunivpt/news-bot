"""Website publication controls and private-field boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import index as api
from app.database import NewsDatabase
from app.models import NewsItem
from scripts import auto_publish


class WebsitePublishControlTests(unittest.TestCase):
    def test_website_publishing_records_a_durable_receipt(self):
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
                 patch.dict('os.environ', {'PUBLISH_WEBSITE': 'true', 'MAX_ITEMS': '1', 'BOT_REPAIR_ITEMS': '0'}, clear=True):
                auto_publish.main()
            db = NewsDatabase(path=path)
            try:
                self.assertEqual(db.get_by_id(1)['status'], 'published')
                receipt = db.conn.execute('SELECT website_published FROM ph_publish_locks WHERE item_id=1').fetchone()
                self.assertEqual(receipt['website_published'], 1)
            finally:
                db.close()

    def test_unknown_settings_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(path=str(Path(folder) / 'test.db'))
            try:
                db.conn.execute('INSERT INTO admin_settings VALUES (?,?,?)',
                                ('unknown_feature_enabled', 'true', NewsItem.now_iso()))
                db.conn.commit()
                self.assertEqual(db.get_settings(), {'website_enabled': 'true'})
                db.set_settings({'unknown_feature_enabled': 'true', 'website_enabled': 'false'})
                self.assertEqual(db.get_settings(), {'website_enabled': 'false'})
            finally:
                db.close()
        with patch.object(api, 'require_admin', return_value=None), \
             patch.object(api, 'require_csrf', return_value=None), \
             patch.object(api, 'db') as database:
            response = api.app.test_client().post('/api/admin/settings', json={'unknown_feature_enabled': True})
            self.assertEqual(response.status_code, 400)
            database.assert_not_called()

    def test_private_fields_are_hidden_for_public_and_admin(self):
        row = {'id': 1, 'title': 'Source report about a new public policy',
               'category': 'india', 'summary': 'A source-linked report.',
               'internal_access_token': 'private', 'password_hash': 'private'}
        with api.app.test_request_context('/'):
            for is_admin in (False, True):
                with patch.object(api, 'admin_ok', return_value=is_admin):
                    output = api._publicize(row)
                    self.assertNotIn('internal_access_token', output)
                    self.assertNotIn('password_hash', output)

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
