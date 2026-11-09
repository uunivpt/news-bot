"""Hosted sessions and editorial writes use isolated storage, never a phone relay."""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from api import index as api
from app.admin_backend import hosted_enabled
from app.database import DatabaseUnavailable, NewsDatabase
from app.models import NewsItem
from app.news_numbers import news_number


class HostedAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'isolated-hosted-owner-password'
        cls.verifier = generate_password_hash(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='politicshub-hosted-test-')
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'hosted.db')
        environment = {
            'POLITICSHUB_ADMIN_BACKEND': 'hosted', 'VERCEL': '1',
            'POLITICSHUB_GITHUB_FEED_ONLY': '1', 'POLITICSHUB_LOCAL_ADMIN': '',
            'DATABASE_3URL': '', 'DATABASE_URL': '',
            'ADMIN_USERS_JSON': json.dumps({'hosted_owner': self.verifier}),
            'POLITICSHUB_ADMIN_BRIDGE_URL': 'https://retired-phone.fixture.ts.net',
            'POLITICSHUB_ADMIN_BRIDGE_SECRET': 'obsolete-fixture-bridge-secret-1234567890',
        }
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        database = self.local_database()
        database.close()
        self.factory = patch.object(api, 'NewsDatabase', side_effect=lambda **kwargs: self.local_database())
        self.database_factory = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.bridge = patch('app.remote_admin_bridge.build_opener', side_effect=AssertionError('Hosted Admin Room must not contact a phone bridge'))
        self.bridge_transport = self.bridge.start()
        self.addCleanup(self.bridge.stop)
        api._db_retry_after = 0
        api._ADMIN_LOGIN_RATE.clear()
        api._PUBLIC_RATE.clear()
        self.client = api.app.test_client()

    def local_database(self):
        # Exercise api.db's production/hosted guard, then redirect only the
        # actual connector to an isolated SQLite file. Production itself must
        # continue refusing a SQLite fallback when its cloud URL is absent.
        with patch.dict(os.environ, {'VERCEL': ''}):
            return NewsDatabase(self.path)

    def sign_in(self, password=None, username='hosted_owner'):
        return self.client.post('/api/admin/login', json={
            'username': username, 'password': password or self.password,
        })

    @contextmanager
    def public_sources(self, rows):
        # Public route tests never fetch Hindi, archive or government feeds.
        with patch.object(api, '_snapshot_rows', return_value=rows), \
             patch.object(api, '_hindi_rows', return_value=[]), \
             patch.object(api, '_official_exam_rows', return_value=[]), \
             patch.object(api.public_archive, 'by_id', return_value=None), \
             patch.object(api.public_archive, 'rows', return_value=[]), \
             patch.object(api.public_archive, '_load', return_value=()):
            yield

    def source_report(self, item_id=730001):
        return {
            'id': item_id, 'title': 'Current source report about an India public policy decision',
            'url': 'https://example.org/current-source-report', 'source_name': 'Current fixture newsroom',
            'source_type': 'rss', 'category': 'india', 'status': 'published', 'public_source': True,
            'summary': 'The current original source explains the policy decision, its official date and its public significance.',
            'bot_article': 'The current source feed paragraph remains available even when the hosted database has no copy of this report.',
            'published_at': datetime.now(timezone.utc).isoformat(),
        }

    def store_cloud_report(self, row, status='pending', approved=False):
        database = self.local_database()
        try:
            self.assertTrue(database.insert(NewsItem(
                source_name=row['source_name'], source_type=row['source_type'],
                title=row['title'], url=row['url'], summary=row['summary'],
                category=row['category'], published_at=row['published_at'], public_source=True,
            )))
            inserted = database.conn.execute('SELECT id FROM news_items WHERE url=?', (row['url'],)).fetchone()['id']
            database.conn.execute('UPDATE news_items SET id=? WHERE id=?', (row['id'], inserted))
            database.conn.commit()
            database.update(row['id'], status=status, bot_summary=row['summary'], bot_article=row['bot_article'],
                fact_check_status='reviewed' if approved else 'pending',
                fact_check_notes='Private editorial fixture note',
                approved_at=datetime.now(timezone.utc).isoformat() if approved else None)
        finally:
            database.close()

    def test_backend_selection_is_explicit_and_retains_legacy_feed_only_guard(self):
        self.assertTrue(hosted_enabled())
        for value in ('', 'phone', 'unrecognized'):
            with self.subTest(value=value), patch.dict(os.environ, {'POLITICSHUB_ADMIN_BACKEND': value}):
                self.assertFalse(hosted_enabled())
                with api.app.test_request_context('/api/admin/workspace'):
                    with self.assertRaises(DatabaseUnavailable):
                        api.db()
        self.database_factory.assert_not_called()

    def test_anonymous_identity_works_with_stale_bridge_settings_without_opening_storage(self):
        response = self.client.get('/api/admin/me')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.json['authenticated'])
        self.assertIsNone(response.json['csrf_token'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.database_factory.assert_not_called()
        self.bridge_transport.assert_not_called()

    def test_hosted_owner_authentication_rejects_wrong_password_and_sets_secure_session(self):
        denied = self.sign_in('incorrect-hosted-password')
        self.assertEqual(denied.status_code, 401)
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])
        login = self.sign_in()
        self.assertEqual(login.status_code, 200, login.data)
        self.assertEqual(login.json['scope'], 'owner')
        self.assertFalse(login.json['read_only'])
        cookie = login.headers['Set-Cookie']
        for attribute in ('Secure', 'HttpOnly', 'SameSite=Strict'):
            self.assertIn(attribute, cookie)
        identity = self.client.get('/api/admin/me')
        self.assertTrue(identity.json['authenticated'])
        self.assertEqual(identity.json['username'], 'hosted_owner')
        self.assertIn('news.publish', identity.json['permissions'])
        self.bridge_transport.assert_not_called()

    def test_private_workspace_requires_auth_and_reports_hosted_writable_storage(self):
        anonymous = self.client.get('/api/admin/workspace')
        self.assertEqual(anonymous.status_code, 401)
        self.assertIn('no-store', anonymous.headers['Cache-Control'])
        self.assertEqual(self.sign_in().status_code, 200)
        response = self.client.get('/api/admin/workspace')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.json
        self.assertEqual(data['mode'], 'live')
        self.assertEqual(data['data_origin'], 'hosted_database')
        self.assertEqual(data['health']['database'], 'connected')
        self.assertFalse(data['access']['read_only'])
        self.assertTrue(data['capabilities']['publish'])
        self.assertNotIn('phone', data['notice'].lower())
        self.assertNotIn('termux', data['notice'].lower())
        self.assertIn('private', response.headers['Cache-Control'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['Vercel-CDN-Cache-Control'], 'no-store')
        self.bridge_transport.assert_not_called()

    def test_existing_database_owner_is_not_replaced_by_stale_configured_bootstrap(self):
        database = self.local_database()
        api._ensure_admin_users(database)
        database.close()
        other_verifier = generate_password_hash('different-configured-owner-password')
        with patch.dict(os.environ, {'ADMIN_USERS_JSON': json.dumps({'replacement_owner': other_verifier})}):
            self.assertEqual(self.sign_in().status_code, 200)
            other = api.app.test_client().post('/api/admin/login', json={
                'username': 'replacement_owner', 'password': 'different-configured-owner-password',
            })
            self.assertEqual(other.status_code, 401)
        database = self.local_database()
        try:
            rows = [dict(row) for row in database.conn.execute('SELECT username,password_hash FROM admin_users')]
            self.assertEqual(rows, [{'username': 'hosted_owner', 'password_hash': self.verifier}])
        finally:
            database.close()

    def test_hosted_publication_and_logout_keep_csrf_and_never_invoke_phone_transport(self):
        login = self.sign_in()
        self.assertEqual(login.status_code, 200, login.data)
        token = login.json['csrf_token']
        body = {
            'title': 'Hosted fixture editorial report about a public policy decision',
            'summary': 'A complete attributed fixture summary that explains the public policy decision and cites its original record.',
            'article': 'This is original fixture editorial text describing the document, its date and the public policy context. ' * 12,
            'category': 'india', 'source_name': 'Hosted fixture editorial desk',
            'source_url': 'https://example.org/public-notice', 'image_url': '',
        }
        with patch('app.live_publication.signed_read', side_effect=AssertionError('No phone reads in hosted mode')) as phone_read, \
             patch('app.phone_publication.start_delivery_worker', side_effect=AssertionError('No phone worker in hosted mode')) as phone_worker, \
             patch('scripts.mobile_sync_upload.upload_immediate', side_effect=AssertionError('No phone SSH delivery in hosted mode')) as phone_upload:
            blocked = self.client.post('/api/admin/news/create', json=body)
            self.assertEqual(blocked.status_code, 403)
            created = self.client.post('/api/admin/news/create', json=body, headers={'X-CSRF-Token': token})
            self.assertEqual(created.status_code, 201, created.data)
            item_id = created.json['id']
            blocked_publish = self.client.post(f'/api/news/{item_id}/approve', json={})
            self.assertEqual(blocked_publish.status_code, 403)
            approved = self.client.post(f'/api/news/{item_id}/approve', json={}, headers={'X-CSRF-Token': token})
            self.assertEqual(approved.status_code, 200, approved.data)
            self.assertEqual(approved.json['status'], 'published')
            self.assertEqual(approved.json['public_delivery']['state'], 'synced')
            self.assertEqual(approved.json['public_delivery']['channel'], 'hosted_database')
            database = self.local_database()
            try:
                row = dict(database.get_by_id(item_id))
                self.assertEqual(row['status'], 'published')
                self.assertEqual(row['bot_article'], body['article'].strip())
                self.assertTrue(row['approved_at'])
            finally:
                database.close()
            phone_read.assert_not_called()
            phone_worker.assert_not_called()
            phone_upload.assert_not_called()
        self.bridge_transport.assert_not_called()
        self.assertEqual(self.client.post('/api/admin/logout').status_code, 403)
        self.assertEqual(self.client.post('/api/admin/logout', headers={'X-CSRF-Token': token}).status_code, 200)
        self.assertFalse(self.client.get('/api/admin/me').json['authenticated'])
        self.assertEqual(self.client.get('/api/admin/workspace').status_code, 401)

    def test_hosted_writes_still_reject_cross_origin_requests(self):
        response = self.client.post('/api/admin/login', json={
            'username': 'hosted_owner', 'password': self.password,
        }, headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(response.status_code, 403)
        self.database_factory.assert_not_called()
        self.bridge_transport.assert_not_called()

    def test_current_source_article_survives_a_healthy_hosted_database_without_a_matching_row(self):
        snapshot = self.source_report()
        canonical = '/india/' + news_number(snapshot)
        with self.public_sources([snapshot]):
            response = self.client.get('/api/news/' + str(snapshot['id']))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn(snapshot['bot_article'], response.json['article'])
            document = self.client.get(canonical)
            self.assertEqual(document.status_code, 200, document.data)
            self.assertIn(snapshot['bot_article'], document.get_data(as_text=True))
            self.assertIn(snapshot['url'], document.get_data(as_text=True))
            listing = self.client.get('/api/news?category=india').json
            self.assertIn(snapshot['id'], [item['id'] for item in listing])
        database = self.local_database()
        try:
            self.assertIsNone(database.get_by_id(snapshot['id']), 'Public reads must not import feed stories into hosted storage')
        finally:
            database.close()
        self.bridge_transport.assert_not_called()

    def test_reviewed_cloud_edit_overrides_source_copy_and_rejection_hides_both_public_routes(self):
        snapshot = self.source_report()
        edited = dict(snapshot, title='Editor reviewed India policy report with corrected context',
            bot_article='The corrected editorial manuscript replaces the source snapshot after an explicit hosted approval.')
        self.store_cloud_report(edited, status='published', approved=True)
        canonical = '/india/' + news_number(snapshot)
        anonymous = api.app.test_client()
        with self.public_sources([snapshot]):
            raw = anonymous.get('/api/news/' + str(snapshot['id']))
            self.assertEqual(raw.status_code, 200, raw.data)
            self.assertIn(edited['bot_article'], raw.json['article'])
            self.assertNotIn('Private editorial fixture note', raw.get_data(as_text=True))
            document = anonymous.get(canonical)
            self.assertEqual(document.status_code, 200, document.data)
            self.assertIn(edited['bot_article'], document.get_data(as_text=True))
            token = self.sign_in().json['csrf_token']
            rejected = self.client.post('/api/news/' + str(snapshot['id']) + '/reject', json={}, headers={'X-CSRF-Token': token})
            self.assertEqual(rejected.status_code, 200, rejected.data)
            for path in ('/api/news/' + str(snapshot['id']), canonical):
                self.assertEqual(anonymous.get(path).status_code, 404, path)
                self.assertEqual(self.client.get(path).status_code, 404, 'An owner session must not expose rejected copy through a public route')
            private = self.client.get('/api/admin/story/' + str(snapshot['id']) + '/article')
            self.assertEqual(private.status_code, 200, private.data)
            self.assertEqual(private.json['status'], 'rejected')
            self.assertIn(edited['bot_article'], private.json['article'])
        self.bridge_transport.assert_not_called()

    def test_public_listing_and_authenticated_public_routes_never_expose_a_private_hosted_draft(self):
        snapshot = self.source_report()
        draft = dict(self.source_report(730002), title='Private unpublished hosted draft with confidential working copy',
            url='https://example.org/private-working-record', source_type='manual',
            bot_article='Confidential draft manuscript must appear only inside an authorized private article endpoint.')
        self.store_cloud_report(draft)
        self.assertEqual(self.sign_in().status_code, 200)
        anonymous = api.app.test_client()
        with self.public_sources([snapshot]):
            for client in (anonymous, self.client):
                listing = client.get('/api/news?status=all&review_status=all')
                self.assertEqual(listing.status_code, 200, listing.data)
                self.assertNotIn(draft['id'], [item['id'] for item in listing.json])
                self.assertNotIn(draft['bot_article'], listing.get_data(as_text=True))
                self.assertEqual(client.get('/api/news/' + str(draft['id'])).status_code, 404)
                self.assertEqual(client.get('/india/' + news_number(draft)).status_code, 404)
            private = self.client.get('/api/admin/story/' + str(draft['id']) + '/article')
            self.assertEqual(private.status_code, 200, private.data)
            self.assertEqual(private.json['status'], 'pending')
            self.assertEqual(private.json['article'], draft['bot_article'])
            self.assertEqual(anonymous.get('/api/admin/story/' + str(draft['id']) + '/article').status_code, 401)
        self.bridge_transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
