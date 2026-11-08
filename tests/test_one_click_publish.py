import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from api import index as api
from app.admin_workspace import editorial_revision
from app.database import NewsDatabase
from app.models import NewsItem
from app.monetization import is_monetizable, review_fingerprint


class OneClickPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'phone.db')
        self.database = NewsDatabase(self.path)
        self.source_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        self.database.insert(NewsItem(source_name='Source News', source_type='rss',
            title='Council publishes the public transport timetable for local residents',
            url='https://example.org/timetable', summary='The council published a timetable for local residents to review before planning their journeys.',
            published_at=self.source_date, public_source=True, category='india'))
        self.sid = self.database.latest(1)[0]['id']
        self.client = api.app.test_client()
        with self.client.session_transaction() as session:
            session.update(admin_user='editor', admin_role='owner', admin_scope='owner', csrf_token='test')
        self.headers = {'X-CSRF-Token': 'test'}
        self.factory = patch.object(api, 'db', return_value=self.database)
        self.closer = patch.object(self.database, 'close')
        self.factory.start(); self.closer.start()

    def tearDown(self):
        self.closer.stop(); self.factory.stop()
        self.database.close(); self.tmp.cleanup()

    def post(self, suffix='approve', **kwargs):
        return self.client.post(f'/api/news/{self.sid}/{suffix}', json={}, headers=self.headers, **kwargs)

    def test_verify_empty_payload_publishes_summary_without_another_confirmation(self):
        with patch.dict(os.environ, {'POLITICSHUB_LOCAL_ADMIN': '1'}):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json['status'], 'published')
        row = dict(self.database.get_by_id(self.sid))
        self.assertEqual(row['status'], 'published')
        self.assertEqual(row['fact_check_status'], 'reviewed')
        self.assertEqual(row['bot_article'], row['summary'])
        self.assertEqual(row['published_at_site'], self.source_date)
        self.assertIsNotNone(row['approved_at'])
        self.assertFalse(is_monetizable(row))
        self.assertNotIn('Originality and added value confirmed.', row['fact_check_notes'])
        audits = self.database.conn.execute("SELECT * FROM admin_activity WHERE action='news.verify_publish'").fetchall()
        self.assertEqual(len(audits), 1)
        with api.app.test_request_context('/'):
            page = api._article_html(row)
        self.assertIn('noindex,follow', page)
        self.assertNotIn('adsbygoogle.js', page)
        self.assertIn(row['summary'], page)

    def test_repeating_verify_or_legacy_publish_does_not_duplicate_audit_or_refresh_date(self):
        first = self.post()
        before = dict(self.database.get_by_id(self.sid))
        second = self.post()
        third = self.post('publish')
        self.assertTrue(first.json['changed'])
        self.assertFalse(second.json['changed'])
        self.assertFalse(third.json['changed'])
        after = dict(self.database.get_by_id(self.sid))
        self.assertEqual(before['approved_at'], after['approved_at'])
        self.assertEqual(before['published_at_site'], after['published_at_site'])
        self.assertEqual(self.database.conn.execute("SELECT COUNT(*) FROM admin_activity WHERE action='news.verify_publish'").fetchone()[0], 1)

    def test_article_only_story_derives_excerpt_and_actual_source_host_for_export(self):
        from app.phone_publication import public_export
        from scripts.mobile_sync_upload import validated
        from scripts.offline_snapshot import mobile_reviewed_story
        body = 'The public notice explains the revised local transport timetable and its effective dates.'
        self.database.conn.execute('UPDATE news_items SET summary=?,bot_summary=?,bot_article=?,source_name=? WHERE id=?',
                                   ('', '', body, '', self.sid))
        self.database.conn.commit()
        response = self.post()
        self.assertEqual(response.status_code, 200, response.data)
        row = dict(self.database.get_by_id(self.sid))
        self.assertEqual(row['source_name'], 'example.org')
        self.assertEqual(row['bot_summary'], body)
        export = public_export(row)
        self.assertEqual(validated([export]), 1)
        self.assertIsNotNone(mobile_reviewed_story(export, datetime.now(timezone.utc)))

    def test_long_editor_headline_and_short_summary_do_not_fail_public_delivery(self):
        from app.phone_publication import public_export
        from scripts.mobile_sync_upload import validated
        from scripts.offline_snapshot import mobile_reviewed_story
        self.database.update(self.sid, title='A detailed public transport headline ' * 7,
                             summary='Revised timetable.', bot_summary='Revised timetable.')
        response = self.post()
        self.assertEqual(response.status_code, 200, response.data)
        row = public_export(dict(self.database.get_by_id(self.sid)))
        self.assertGreater(len(row['title']), 210)
        self.assertEqual(validated([row]), 1)
        self.assertIsNotNone(mobile_reviewed_story(row, datetime.now(timezone.utc)))

    def test_stale_copy_revision_is_rejected_before_publication(self):
        revision = editorial_revision(dict(self.database.get_by_id(self.sid)))
        self.database.update(self.sid, title='A newer edited public transport timetable for local residents')
        response = self.client.post(f'/api/news/{self.sid}/approve', json={'revision': revision}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'story_changed')
        self.assertEqual(self.database.get_by_id(self.sid)['status'], 'pending')

    def test_simultaneous_verifies_commit_publication_and_audit_only_once(self):
        def verify(_):
            with api.app.test_client() as client:
                response = client.post(f'/api/news/{self.sid}/approve', json={})
                return response.status_code, response.json
        with patch.object(api, 'db', side_effect=lambda: NewsDatabase(self.path)), \
             patch.object(api, 'require_admin', return_value=None), \
             patch.object(api, 'require_csrf', return_value=None):
            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(verify, range(3)))
        self.assertTrue(all(status == 200 for status, _ in responses), responses)
        self.assertEqual(sum(bool(data['changed']) for _, data in responses), 1)
        count = self.database.conn.execute("SELECT COUNT(*) FROM admin_activity WHERE action='news.verify_publish'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_legacy_naive_source_date_is_not_replaced_with_today(self):
        self.database.conn.execute('UPDATE news_items SET published_at=? WHERE id=?', ('2026-01-10', self.sid))
        self.database.conn.commit()
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.get_by_id(self.sid)['published_at_site'], '2026-01-10T00:00:00+00:00')

    def test_authentication_and_csrf_are_still_required(self):
        missing_csrf = self.client.post(f'/api/news/{self.sid}/approve', json={})
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(api.app.test_client().post(f'/api/news/{self.sid}/approve', json={}).status_code, 401)

    def test_unreadable_or_private_source_is_not_falsely_published(self):
        self.database.update(self.sid, public_source=0)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'source_unavailable')
        self.assertEqual(self.database.get_by_id(self.sid)['status'], 'pending')

    def test_telemetry_failure_does_not_undo_committed_publication(self):
        with patch('app.advanced_system.record_editorial_publication', side_effect=RuntimeError('fixture')):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['telemetry_recorded'])
        self.assertEqual(self.database.get_by_id(self.sid)['status'], 'published')

    def test_public_delivery_failure_is_reported_without_reverting_publication(self):
        with patch('app.phone_publication.deliver_publication', side_effect=RuntimeError('fixture')):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'published')
        self.assertEqual(response.json['public_delivery']['state'], 'failed')
        self.assertEqual(self.database.get_by_id(self.sid)['status'], 'published')

    def test_existing_genuine_unchanged_monetization_evidence_is_preserved(self):
        article = "The official timetable distinguishes public-route changes from services that continue under earlier arrangements. The notice identifies the responsible office and provides the date on which updated schedules are expected to apply. Residents should consult the current published document rather than a forwarded copy with no reference number. Individual route listings may include conditions that are not fully described in the public announcement. Staff contact channels are listed separately from the general inquiries desk in the detailed guidance. The issuing authority can publish later corrections, which should be checked before relying on an old timetable. Accessibility information is best verified against the official service page for the affected locality. Readers should compare published hours with any holiday notices before planning a journey."
        self.database.update(self.sid, bot_summary=self.database.get_by_id(self.sid)['summary'], bot_article=article)
        row = dict(self.database.get_by_id(self.sid))
        notes = ('Originality and added value confirmed. Evidence: https://independent.example.net/notice. '
                 'Notes: The editor compared the original notice and confirmed rights. Content SHA256: ' + review_fingerprint(row) + '.')
        self.database.update(self.sid, fact_check_status='reviewed', approved_at=self.source_date, fact_check_notes=notes)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        row = dict(self.database.get_by_id(self.sid))
        self.assertEqual(row['fact_check_notes'], notes)
        self.assertTrue(is_monetizable(row))
