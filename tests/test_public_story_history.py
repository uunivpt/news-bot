import sqlite3
import unittest
from datetime import datetime,timezone
from app.public_story_history import public_updates,newest_modified,render_history
class DB:
    _postgres=False
    def __init__(self):
        self.conn=sqlite3.connect(':memory:')
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('CREATE TABLE ph_editorial_updates (id INTEGER PRIMARY KEY,item_id INTEGER,kind TEXT,label TEXT,source_url TEXT,status TEXT,published_at TEXT)')
    def close(self):self.conn.close()
class PublicUpdateHistoryTests(unittest.TestCase):
    def test_pending_rows_and_editor_details_are_not_returned(self):
        db=DB()
        db.conn.execute("INSERT INTO ph_editorial_updates VALUES (1,10,'correction','Corrected district','https://example.org/notice','published','2026-10-16T09:00:00+00:00')")
        db.conn.execute("INSERT INTO ph_editorial_updates VALUES (2,10,'update','Confidential draft','https://example.org/internal','pending',NULL)")
        history=public_updates({'id':10,'source_type':'manual','status':'published'},lambda:db)
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['label'],'Corrected district')
        self.assertNotIn('Confidential draft',str(history))
        markup=render_history(history)
        self.assertIn('Published updates &amp; corrections',markup)
        self.assertNotIn('Confidential draft',markup)
        self.assertEqual(newest_modified(history,'2026-10-15T09:00:00+00:00'),'2026-10-16T09:00:00+00:00')
    def test_no_history_without_published_editorial_identity(self):
        self.assertEqual(public_updates({'id':10,'source_type':'rss'},lambda:(_ for _ in ()).throw(AssertionError())),[])
        self.assertEqual(render_history([]),'')
        self.assertIsNone(newest_modified([], '2026-10-15T09:00:00+00:00'))
