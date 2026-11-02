import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.database import NewsDatabase
from app.models import NewsItem
from app.source_inventory import source_inventory


CONFIG = {
    'rss': [
        {'name': 'TV9 Marathi - Maharashtra', 'category': 'india', 'enabled': True,
         'url': 'https://www.tv9marathi.com/maharashtra/feed'},
        {'name': 'ABP Majha - Maharashtra', 'category': 'india', 'enabled': True,
         'url': 'https://marathi.abplive.com/news/maharashtra/feed'},
        {'name': 'The Hindu - India', 'category': 'india', 'enabled': True,
         'url': 'https://www.thehindu.com/news/national/feeder/default.rss'},
    ],
    'telegram': [{'name': 'Disabled channel', 'enabled': False, 'category': 'world'}],
    'hindi_rss': [{'name': 'Hindi publisher', 'enabled': True, 'category': 'hindi'}],
}


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.temp.name) / 'inventory.db'))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_configured_publishers_are_visible_without_stories_or_fake_fetches(self):
        before = self.db.conn.total_changes
        inventory = source_inventory(self.db, config=CONFIG)
        self.assertEqual(inventory['configured_count'], 5)
        self.assertEqual(inventory['enabled_count'], 4)
        self.assertEqual(inventory['total_stories'], 0)
        items = {item['name']: item for item in inventory['items']}
        for name in ('TV9 Marathi - Maharashtra', 'ABP Majha - Maharashtra', 'The Hindu - India'):
            self.assertEqual(items[name]['story_count'], 0)
            self.assertEqual(items[name]['collection_status'], 'awaiting_collection')
            self.assertIsNone(items[name]['last_success_at'])
        self.assertEqual(items['Disabled channel']['collection_status'], 'disabled')
        self.assertEqual(items['Hindi publisher']['collection_status'], 'external_pipeline')
        self.assertEqual(self.db.conn.total_changes, before)
        self.assertIsNone(self.db.conn.execute("SELECT name FROM sqlite_master WHERE name='ph_source_collection'").fetchone())

    def test_all_database_records_count_including_older_and_unconfigured_publishers(self):
        for index in range(205):
            self.db.insert(NewsItem(source_name='The Hindu - India' if index < 3 else 'Historical publisher',
                source_type='rss', title=f'Report {index}', url=f'https://example.org/{index}',
                summary='Source report', category='india' if index < 3 else 'world'))
        inventory = source_inventory(self.db, config=CONFIG)
        items = {item['name']: item for item in inventory['items']}
        self.assertEqual(inventory['total_stories'], 205)
        self.assertEqual(inventory['represented_count'], 2)
        self.assertEqual(inventory['categories_count'], 2)
        self.assertEqual(items['The Hindu - India']['story_count'], 3)
        self.assertEqual(items['Historical publisher']['story_count'], 202)
        self.assertFalse(items['Historical publisher']['configured'])
        self.assertEqual(items['Historical publisher']['collection_status'], 'unknown')
        self.assertIsNotNone(items['Historical publisher']['latest_collected_at'])
        # Having stored rows never establishes that a current fetch succeeded.
        self.assertEqual(items['The Hindu - India']['collection_status'], 'awaiting_collection')

    def test_actual_telemetry_distinguishes_failed_empty_and_overdue_checks(self):
        self.db.conn.execute('''CREATE TABLE ph_source_collection (
            source_type TEXT,source_name TEXT,last_attempt_at TEXT,last_success_at TEXT,
            last_error TEXT,status TEXT,item_count INTEGER,added_count INTEGER,duplicate_count INTEGER)''')
        for name, status, attempted, success, error in (
            ('TV9 Marathi - Maharashtra', 'failed', '2026-11-02T10:00:00Z', None, 'HTTPError (HTTP 503)'),
            ('ABP Majha - Maharashtra', 'healthy', '2026-11-02T10:00:00Z', '2026-11-02T10:00:00Z', None),
            ('The Hindu - India', 'healthy', '2026-11-01T10:00:00Z', '2026-11-01T10:00:00Z', None),
        ):
            self.db.conn.execute('INSERT INTO ph_source_collection VALUES (?,?,?,?,?,?,0,0,0)',
                ('rss', name, attempted, success, error, status))
        self.db.conn.commit()
        inventory = source_inventory(self.db, config=CONFIG, now=datetime(2026, 11, 2, 10, 5, tzinfo=timezone.utc))
        items = {item['name']: item for item in inventory['items']}
        self.assertEqual(items['TV9 Marathi - Maharashtra']['collection_status'], 'failed')
        self.assertEqual(items['TV9 Marathi - Maharashtra']['last_error'], 'HTTPError (HTTP 503)')
        self.assertEqual(items['ABP Majha - Maharashtra']['collection_status'], 'healthy')
        self.assertEqual(items['ABP Majha - Maharashtra']['items_found'], 0)
        self.assertEqual(items['The Hindu - India']['collection_status'], 'stale')

    def test_snapshot_cannot_claim_private_collection_health(self):
        inventory = source_inventory(rows=[{'source_name': 'The Hindu - India', 'category': 'india',
            'published_at': '2026-11-01T10:00:00Z'}], config=CONFIG)
        items = {item['name']: item for item in inventory['items']}
        self.assertEqual(inventory['scope'], 'snapshot')
        self.assertEqual(inventory['total_stories'], 1)
        self.assertEqual(items['The Hindu - India']['collection_status'], 'unknown')
        self.assertIsNone(items['The Hindu - India']['latest_collected_at'])
        self.assertEqual(items['TV9 Marathi - Maharashtra']['story_count'], 0)
        unavailable = source_inventory(config=CONFIG)
        self.assertEqual(unavailable['scope'], 'unavailable')
        self.assertIsNone(unavailable['total_stories'])
        self.assertTrue(all(item['story_count'] is None for item in unavailable['items']))

    def test_unsafe_configuration_links_are_never_returned(self):
        config = {'rss': [{'name': 'Private', 'url': 'https://user:password@example.org/feed'},
                          {'name': 'Loopback', 'url': 'http://127.0.0.1/feed'}]}
        inventory = source_inventory(self.db, config=config)
        self.assertTrue(all(item['url'] is None and item['feed_url'] is None for item in inventory['items']))


if __name__ == '__main__':
    unittest.main()
