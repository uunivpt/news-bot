import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import NewsDatabase
from app.hosted_publication import delivery, is_editorial_override, overlay, version
from app.models import NewsItem
from app.seo_indexing import SITE_ORIGIN, canonical_path


STAMP = '2026-11-09T09:00:00+00:00'


class HostedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.temp.name) / 'hosted.db'))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def story(self, key, *, source_type='rss', url=None, approved=True, status='published'):
        url = url or 'https://example.org/report/' + str(key)
        self.db.insert(NewsItem(source_name='Named source', source_type=source_type,
            title='Original public affairs report number ' + str(key), url=url,
            summary='A source-linked summary with context for the public reader.',
            published_at=STAMP, public_source=True, category='india'))
        item_id = self.db.conn.execute('SELECT MAX(id) FROM news_items').fetchone()[0]
        self.db.update(item_id, status=status,
            approved_at=STAMP if approved else None,
            fact_check_status='reviewed' if approved else 'pending',
            bot_article='An editable private manuscript. ' * 40,
            fact_check_notes='Private review notes must not enter listing reads.')
        return dict(self.db.get_by_id(item_id))

    def test_approved_cloud_story_joins_current_snapshot_without_publishing_old_database(self):
        published = self.story('approved')
        self.story('unreviewed', approved=False)
        snapshot = {'id': 9000, 'title': 'Current GitHub headline',
                    'url': 'https://example.org/current', 'status': 'published'}
        original = json.dumps(snapshot)
        result = overlay(self.db, [snapshot])
        self.assertEqual({row['id'] for row in result}, {9000, published['id']})
        self.assertEqual(json.dumps(snapshot), original)
        cloud = next(row for row in result if row['id'] == published['id'])
        self.assertNotIn('bot_article', cloud)
        self.assertNotIn('fact_check_notes', cloud)

    def test_approved_edit_replaces_old_public_copy_and_preserves_identity(self):
        row = self.story('edited')
        old = dict(row, title='Outdated public title', bot_article='Outdated public manuscript')
        self.db.update(row['id'], title='Editor corrected the public headline with new context')
        result = overlay(self.db, [old])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], row['id'])
        self.assertIn('Editor corrected', result[0]['title'])
        self.assertNotIn('bot_article', result[0])

    def test_rejection_and_pending_review_suppress_previous_snapshot_copy(self):
        row = self.story('withdrawn')
        for changes in ({'status': 'rejected'},
                        {'status': 'pending'},
                        {'status': 'published', 'fact_check_status': 'needs_review'}):
            with self.subTest(changes=changes):
                self.db.update(row['id'], **changes)
                self.assertEqual(overlay(self.db, [row]), [])

    def test_untouched_legacy_rows_do_not_hide_previously_published_snapshot(self):
        row = self.story('legacy', approved=False)
        snapshot = {'id': row['id'], 'title': 'Public archival headline',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        for state in ('published', 'pending', 'rejected'):
            with self.subTest(state=state):
                self.db.update(row['id'], status=state)
                current = self.db.get_by_id(row['id'])
                self.assertFalse(is_editorial_override(self.db, current))
                self.assertEqual(overlay(self.db, [snapshot]), [snapshot])

    def test_editor_edit_resetting_approval_suppresses_the_old_public_copy(self):
        row = self.story('edited-pending')
        snapshot = {'id': row['id'], 'title': 'Earlier published headline',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        self.db.update(row['id'], approved_at=None, status='pending', fact_check_status='pending')
        self.db.log_activity('owner', 'news.edit', row['id'], 'Headline edited; fresh review required')
        self.assertTrue(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
        self.assertEqual(overlay(self.db, [snapshot]), [])

    def test_collector_logs_do_not_make_untouched_legacy_rows_authoritative(self):
        row = self.story('collected', approved=False, status='pending')
        snapshot = {'id': row['id'], 'title': 'Source-linked public headline',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        for action in ('collector.refresh', 'news.process', 'news.collection.update'):
            self.db.log_activity('collector', action, row['id'], 'Routine source processing')
        self.assertFalse(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
        self.assertEqual(overlay(self.db, [snapshot]), [snapshot])
        self.db.log_activity('editor', 'editorial.studio.save', row['id'], 'Editor saved a changed draft')
        self.assertTrue(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
        self.assertEqual(overlay(self.db, [snapshot]), [])

    def test_known_editorial_actions_override_and_unrelated_events_do_not(self):
        row = self.story('actions', approved=False, status='pending')
        snapshot = {'id': row['id'], 'title': 'Previously published source headline',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        self.db.log_activity('owner', 'news.edit', row['id'] + 1, 'Another story')
        self.assertEqual(overlay(self.db, [snapshot]), [snapshot])
        for action in ('news.update', 'news.verify_publish', 'archive.restore', 'news.manual.create'):
            with self.subTest(action=action):
                self.db.conn.execute('DELETE FROM admin_activity')
                self.db.conn.commit()
                self.db.log_activity('owner', action, row['id'], 'Editorial action')
                self.assertTrue(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
                self.assertEqual(overlay(self.db, [snapshot]), [])

    def test_assignment_claims_and_proposed_updates_do_not_withdraw_public_copy(self):
        row = self.story('editorial-review', approved=False)
        snapshot = {'id': row['id'], 'title': 'Existing source-linked public report',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        for action in ('editorial.assign', 'editorial.claim.create',
                       'editorial.claim.evidence', 'editorial.update.propose',
                       'editorial.event.sources'):
            with self.subTest(action=action):
                self.db.log_activity('editor', action, row['id'], 'Review work only')
                self.assertFalse(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
                self.assertEqual(overlay(self.db, [snapshot]), [snapshot])
        self.db.log_activity('publisher', 'editorial.update.publish', row['id'], 'Published correction')
        self.assertTrue(is_editorial_override(self.db, self.db.get_by_id(row['id'])))
        self.assertEqual(overlay(self.db, [snapshot]), [])

    def test_replacement_with_same_source_url_overrides_legacy_identity(self):
        row = self.story('restored')
        snapshot = dict(row, id=8822, title='Legacy public source copy')
        result = overlay(self.db, [snapshot])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], row['id'])
        self.db.update(row['id'], status='rejected')
        self.assertEqual(overlay(self.db, [snapshot]), [])

    def test_distinct_manual_story_does_not_replace_source_report_using_same_evidence_url(self):
        evidence = 'https://example.org/official-record'
        row = self.story('manual', source_type='manual', url=evidence)
        snapshot = {'id': 5522, 'title': 'Publisher report citing this official record',
                    'url': evidence, 'source_type': 'rss', 'status': 'published'}
        result = overlay(self.db, [snapshot])
        self.assertEqual({item['id'] for item in result}, {5522, row['id']})
        self.db.update(row['id'], status='rejected')
        self.assertEqual([item['id'] for item in overlay(self.db, [snapshot])], [5522])

    def test_newer_source_identity_does_not_replace_distinct_manual_snapshot(self):
        row = self.story('source')
        manual = {'id': 9981, 'title': 'Original manual article using source evidence',
                  'url': row['url'], 'source_type': 'manual', 'status': 'published'}
        self.db.update(row['id'], status='rejected')
        self.assertEqual(overlay(self.db, [manual]), [manual])

    def test_delivery_is_immediate_for_approved_native_identity_and_has_no_private_text(self):
        row = self.story('delivery', source_type='manual')
        result = delivery(self.db, row['id'])
        self.assertEqual(result['state'], 'synced')
        self.assertEqual(result['mode'], 'hosted')
        self.assertEqual(result['public_url'], SITE_ORIGIN + canonical_path(row))
        self.assertEqual(len(result['revision']), 64)
        self.assertNotIn('Private', json.dumps(result))
        self.assertEqual(delivery(self.db, 99999)['state'], 'failed')
        self.db.update(row['id'], status='pending')
        self.assertEqual(delivery(self.db, row['id'])['state'], 'failed')

    def test_invalid_public_source_cannot_leave_cloud_even_if_review_flags_exist(self):
        row = self.story('private-source')
        self.db.update(row['id'], public_source=0)
        self.assertEqual(overlay(self.db, []), [])
        self.assertEqual(delivery(self.db, row['id'])['state'], 'failed')

    def test_withheld_source_never_reappears_through_hosted_overlay_or_delivery(self):
        row = self.story('withheld-source')
        snapshot = {'id': row['id'], 'title': 'Earlier public copy',
                    'url': row['url'], 'source_type': 'rss', 'status': 'published'}
        with patch('app.hosted_publication.source_withheld', return_value=True) as withheld:
            self.assertEqual(overlay(self.db, [snapshot]), [])
            self.assertEqual(overlay(self.db, []), [])
            self.assertEqual(delivery(self.db, row['id'])['state'], 'failed')
            withheld.assert_called_with(row['url'])

    def test_version_changes_after_edit_and_withdrawal_without_returning_event_text(self):
        row = self.story('version')
        first = version(self.db)
        self.assertEqual(first, version(self.db))
        self.db.update(row['id'], title='A checked correction to an existing headline')
        self.db.log_activity('owner', 'news.edit', row['id'], 'Private revision information')
        edited = version(self.db)
        self.assertNotEqual(first, edited)
        self.db.update(row['id'], status='rejected')
        self.assertNotEqual(edited, version(self.db))
        self.assertEqual(len(first), 64)

    def test_snapshot_state_and_caller_limit_are_honored(self):
        snapshots = [{'id': 1, 'title': 'Public copy', 'status': 'published'},
                     {'id': 2, 'title': 'Private copy', 'status': 'pending'}]
        self.assertEqual([row['id'] for row in overlay(self.db, snapshots)], [1])
        self.assertEqual(overlay(self.db, snapshots, limit=0), [])

    def test_large_archive_matches_editorial_identities_in_few_queries(self):
        withdrawn = self.story('large-withdrawn')
        corrected = self.story('large-corrected')
        unchanged = self.story('large-legacy', approved=False)
        unrelated = self.story('large-unrelated', source_type='manual')
        self.db.update(withdrawn['id'], status='rejected')
        self.db.update(corrected['id'], title='Editor corrected this archived public headline')
        snapshots = [dict(row) for row in (withdrawn, corrected, unchanged)]
        snapshots.extend({'id': 10000 + index, 'title': 'Archived public report ' + str(index),
                          'url': 'https://example.org/archive/' + str(index),
                          'source_type': 'rss', 'status': 'published'}
                         for index in range(997))
        queries = []
        self.db.conn.set_trace_callback(queries.append)
        try:
            result = overlay(self.db, snapshots)
        finally:
            self.db.conn.set_trace_callback(None)
        selected = [statement for statement in queries if statement.lstrip().upper().startswith('SELECT')]
        self.assertLessEqual(len(selected), 5, selected)
        self.assertTrue(any('SELECT n.id,n.url,n.source_type' in statement for statement in selected))
        self.assertFalse(any('SELECT *' in statement for statement in selected))
        by_id = {row['id']: row for row in result}
        self.assertNotIn(withdrawn['id'], by_id)
        self.assertEqual(by_id[corrected['id']]['title'], 'Editor corrected this archived public headline')
        self.assertNotIn('bot_article', by_id[corrected['id']])
        self.assertNotIn('fact_check_notes', by_id[corrected['id']])
        self.assertEqual(by_id[unchanged['id']], unchanged)
        self.assertIn(unrelated['id'], by_id)

    def test_large_archive_keeps_old_tombstone_and_distinct_manual_source_copy(self):
        withdrawn = self.story('old-tombstone', approved=False, status='pending')
        self.db.log_activity('owner', 'news.update', withdrawn['id'], 'Editor withdrew old public story')
        manual = self.story('manual-shared', source_type='manual',
                            url='https://example.org/shared-evidence')
        self.db.update(manual['id'], status='rejected')
        snapshots = [dict(withdrawn, id=8812, status='published'),
                     {'id': 8813, 'title': 'Distinct source report using official evidence',
                      'url': manual['url'], 'source_type': 'rss', 'status': 'published'}]
        snapshots.extend({'id': 20000 + index, 'title': 'Historical source report',
                          'url': 'https://example.org/historical/' + str(index),
                          'source_type': 'rss', 'status': 'published'}
                         for index in range(600))
        result = overlay(self.db, snapshots)
        ids = {row['id'] for row in result}
        self.assertNotIn(8812, ids)
        self.assertIn(8813, ids)


if __name__ == '__main__':
    unittest.main()
