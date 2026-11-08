import tempfile
import unittest
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

from api import index as api
from app.database import NewsDatabase
from app.monetization import is_monetizable, review_fingerprint
from app.seo_indexing import is_indexable


def story():
    return dict(id=44, title="District officials explain the revised public water supply arrangements",
                category="india", status="published", public_source=True, source_type="manual",
                url="https://example.org/notice", source_name="PoliticsHub Editorial",
                published_at=datetime.now(timezone.utc).isoformat(),
                summary="The district issued new water supply arrangements, with official documents describing the affected areas and their schedules.",
                bot_article="The district issued new water supply arrangements. " +
                "The official notice lists the delivery schedule and explains how residents can request help. " * 10)


def reviewed(row):
    row.update(fact_check_status="reviewed", approved_at=datetime.now(timezone.utc).isoformat())
    row["fact_check_notes"] = ("Originality and added value confirmed. Evidence: https://example.net/notice. "
                               "Notes: Compared the official notice and independently checked the additional explanation. "
                               "Content SHA256: " + review_fingerprint(row) + ".")
    return row


class MonetizationTests(unittest.TestCase):
    def test_search_eligibility_does_not_authorize_ads(self):
        row = story()
        self.assertTrue(is_indexable(row))
        self.assertFalse(is_monetizable(row))
        self.assertTrue(is_monetizable(reviewed(row)))
        row['bot_article'] += ' A different claim was added after review.'
        self.assertFalse(is_monetizable(row))

    def test_repeated_summary_cannot_be_monetized_even_with_review(self):
        row = story()
        row['summary'] = row['bot_article']
        self.assertFalse(is_indexable(row))
        self.assertFalse(is_monetizable(reviewed(row)))
        with api.app.test_request_context('/'):
            page = api._article_html(row)
        self.assertNotIn('adsbygoogle.js', page)
        self.assertEqual(page.count('<p>' + row['summary'].strip() + '</p>'), 1)
        self.assertNotIn('<p class="dek">', page)

    def test_public_projection_retains_decision_without_exposing_review_notes(self):
        with api.app.test_request_context('/'):
            projected = api._publicize(reviewed(story()))
            self.assertTrue(projected['ads_eligible'])
            self.assertNotIn('fact_check_notes', projected)
            self.assertIn('adsbygoogle.js', api._article_html(projected))
            forged = dict(story(), ads_eligible=True)
            self.assertFalse(api._publicize(forged)['ads_eligible'])

    def test_automated_editorial_flags_are_not_a_human_review(self):
        row = dict(story(), editorial_value=True, source_count=4,
                   fact_check_status='passed', approved_at='2026-11-01T10:00:00Z')
        self.assertFalse(is_monetizable(row))

    def test_sensitive_public_interest_news_requires_separate_ad_suitability_review(self):
        row = story()
        row['title'] = 'Regional officials issue updated report on fatal attack'
        row = reviewed(row)
        self.assertFalse(is_monetizable(row))
        row['fact_check_notes'] += ' Ad suitability reviewed for sensitive coverage.'
        self.assertTrue(is_monetizable(row))

    def test_source_image_link_alone_does_not_establish_republication_rights(self):
        row = reviewed(dict(story(), image_url='https://example.org/news/photo.jpg'))
        self.assertFalse(is_monetizable(row))
        row.update(image_license='licensed', image_credit='Photo used with publisher permission')
        self.assertTrue(is_monetizable(reviewed(row)))


class EditorialApprovalFlowTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv('TEST_POSTGRES_URL'), 'TEST_POSTGRES_URL is not configured')
    def test_postgres_editorial_create_approve_publish_and_edit(self):
        import psycopg
        from psycopg import sql
        url = os.environ['TEST_POSTGRES_URL']
        parsed = urlsplit(url)
        if parsed.hostname not in {'localhost', '127.0.0.1', 'postgres'}:
            self.fail('Editorial integration fixtures require local PostgreSQL')
        name = 'editorial_test_' + uuid.uuid4().hex
        factory = NewsDatabase
        with psycopg.connect(url, autocommit=True) as server:
            server.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                isolated = urlunsplit(parsed._replace(path='/' + name))
                with patch.object(sys.modules[__name__], 'NewsDatabase',
                                  side_effect=lambda path: factory(database_url=isolated)):
                    self.test_verify_publishes_without_granting_ads_and_edits_invalidate_review()
            finally:
                server.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def test_verify_publishes_without_granting_ads_and_edits_invalidate_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'editorial.db')
            NewsDatabase(path).close()
            client = api.app.test_client()
            with client.session_transaction() as sess:
                sess.update(admin_user='owner', admin_role='owner', admin_scope='owner', csrf_token='test')
            headers = {'X-CSRF-Token': 'test'}
            row = story()
            draft = dict(title=row['title'], summary=row['summary'], article=row['bot_article'],
                         category='india', source_url=row['url'], source_name=row['source_name'])
            with patch.object(api, 'db', side_effect=lambda: NewsDatabase(path)), \
                 patch.dict('os.environ', {'POLITICSHUB_LOCAL_ADMIN': '0'}):
                created = client.post('/api/admin/news/create', json=draft, headers=headers)
                self.assertEqual(created.status_code, 201, created.data)
                sid = created.json['id']
                url = '/api/news/' + str(sid)
                approved = client.post(url+'/approve', json={}, headers=headers)
                self.assertEqual(approved.status_code, 200, approved.data)
                self.assertEqual(approved.json['status'], 'published')
                self.assertEqual(client.post(url+'/publish', json={}, headers=headers).status_code, 200)
                db = NewsDatabase(path)
                record = dict(db.get_by_id(sid)); db.close()
                self.assertFalse(is_monetizable(record))
                article = client.get(api.article_path(record))
                self.assertNotIn('adsbygoogle.js', article.get_data(as_text=True))
                revision = client.get('/api/admin/story/'+str(sid)).json['revision']
                edited = client.post(url+'/edit', json={'bot_article': row['bot_article']+' New unreviewed material.'},
                                     headers=dict(headers, **{'If-Match': revision}))
                self.assertEqual(edited.status_code, 200, edited.data)
                db = NewsDatabase(path)
                record = dict(db.get_by_id(sid)); db.close()
                self.assertIsNone(record['approved_at'])
                self.assertEqual(record['status'], 'pending')
                self.assertFalse(is_monetizable(record))
                self.assertEqual(client.post(url+'/approve', json={}, headers=headers).json['status'], 'published')
