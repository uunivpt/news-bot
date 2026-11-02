import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

from app.database import NewsDatabase
from app.models import NewsItem
from app.advanced_system import (
    admin_snapshot, ensure_schema, historical_analytics, record_editorial_publication,
    resource_usage, story_inventory,
)


class ActualTelemetryTests(unittest.TestCase):
    def test_sqlite_database_size_comes_from_connected_database_not_cwd_data_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(str(Path(folder) / 'phone.db'))
            try:
                resources = resource_usage(db, root=Path(folder) / 'missing-project-root')
                self.assertGreater(resources['database']['bytes'], 0)
                self.assertEqual(resources['database']['status'], 'available')
                self.assertIsNone(resources['media']['bytes'])
                self.assertEqual(resources['media']['status'], 'not_configured')
            finally:
                db.close()

    def test_failed_database_measurement_and_absent_media_are_not_zero(self):
        broken = SimpleNamespace(_postgres=True, conn=Mock())
        broken.conn.execute.side_effect = RuntimeError('private connection detail')
        with tempfile.TemporaryDirectory() as folder:
            resources = resource_usage(broken, root=folder)
        self.assertIsNone(resources['local_bytes']['db'])
        self.assertIsNone(resources['local_bytes']['media'])
        self.assertNotIn('private connection detail', str(resources))

    def test_snapshot_reports_actual_inventory_without_creating_telemetry_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(str(Path(folder) / 'phone.db'))
            try:
                for index in range(3):
                    db.insert(NewsItem(source_name='Recorded source', source_type='rss',
                        title='A district public service notice with details',
                        url='https://example.org/notice/'+str(index),
                        summary='The district published a notice explaining the revised service arrangements.',
                        public_source=True))
                db.update(1, status='published')
                ensure_schema(db)
                before = db.conn.total_changes
                first = admin_snapshot(db)
                second = admin_snapshot(db)
                self.assertEqual(db.conn.total_changes, before)
                self.assertEqual(first['inventory']['total'], 3)
                self.assertEqual(first['inventory']['pending'], 2)
                self.assertEqual(first['inventory']['published'], 1)
                self.assertEqual(first['inventory']['sources'][0]['records'], 3)
                self.assertEqual(first['counts']['scores'], 0)
                self.assertTrue(first['availability']['scores'])
                self.assertEqual(second['counts']['events'], 0)
                self.assertEqual(db.conn.execute('SELECT COUNT(*) FROM ph_resource_snapshots').fetchone()[0], 0)
            finally:
                db.close()

    def test_publication_records_real_score_event_without_claiming_source_fetch_success(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(str(Path(folder) / 'phone.db'))
            try:
                result = record_editorial_publication(db, dict(id=44,
                    title='जिल्हा प्रशासनाने पाणी पुरवठ्याबाबत नवीन सूचना दिली',
                    category='india', source_name='Cited publisher',
                    url='https://example.org/notice', summary='A source-linked notice.'))
                snapshot = admin_snapshot(db)
                self.assertEqual(snapshot['counts']['scores'], 1)
                self.assertEqual(snapshot['counts']['events'], 1)
                self.assertFalse(result['independent_fact_check'])
                self.assertEqual(snapshot['sources'], [])
                self.assertEqual(snapshot['scores'][0]['verification'], 55)
            finally:
                db.close()

    def test_missing_history_query_is_unavailable_not_a_false_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(str(Path(folder) / 'phone.db'))
            try:
                ensure_schema(db)
                connection = db.conn
                def execute(query, *args):
                    if 'COUNT(*) AS c FROM ph_news_scores' in query:
                        raise RuntimeError('failed query')
                    return connection.execute(query, *args)
                proxy = SimpleNamespace(_postgres=False, path=db.path,
                                        conn=SimpleNamespace(execute=execute))
                history = historical_analytics(proxy)
                self.assertIsNone(history['counts']['scores'])
                self.assertFalse(history['availability']['scores'])
                self.assertEqual(history['counts']['alerts'], 0)
            finally:
                db.close()

    @unittest.skipUnless(os.getenv('TEST_POSTGRES_URL'), 'Local PostgreSQL fixture is not configured')
    def test_postgres_database_size_is_measured_from_postgres(self):
        import psycopg
        from psycopg.rows import dict_row
        url = os.environ['TEST_POSTGRES_URL']
        self.assertIn(urlsplit(url).hostname, {'localhost', '127.0.0.1', 'postgres'})
        with psycopg.connect(url, row_factory=dict_row) as conn:
            database = SimpleNamespace(_postgres=True, conn=conn)
            resources = resource_usage(database, root='/does-not-exist')
        self.assertEqual(resources['database']['engine'], 'postgresql')
        self.assertEqual(resources['database']['status'], 'available')
        self.assertGreater(resources['database']['bytes'], 0)


if __name__ == '__main__':
    unittest.main()
