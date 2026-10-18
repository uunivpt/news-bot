import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import index as api
from app.database import NewsDatabase, DatabaseUnavailable
from app import public_archive as archive


def story(number, date="2026-09-20T10:00:00Z", category="india"):
    return dict(id=number, title=f"Parliament public services report number {number}",
                summary="Discussion of public services and legislative changes across the country.",
                bot_article="Distinct archival phrase about public services. " * 12,
                category=category, url=f"https://example.com/{number}",
                published_at=date, source_name="Archive Source", source_type="rss",
                public_source=True, status="published")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.tmp.name) / "news.db"))
        self.client = api.app.test_client()
        api._PUBLIC_RATE.clear()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def context(self, records):
        return patch.object(archive, "_load", return_value=tuple(records))

    def live(self, row, status="published"):
        self.db.conn.execute("INSERT INTO news_items(id,title,url,normalized_url,url_hash,title_hash,source_name,source_type,summary,bot_article,category,status,published_at,collected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (row["id"], row["title"], row["url"], row["url"], str(row["id"]),str(row["id"]),row["source_name"],row["source_type"],row["summary"],row["bot_article"],row["category"],status,row["published_at"],row["published_at"]))
        self.db.conn.commit()

    def test_old_search_and_full_article_work_with_healthy_new_database(self):
        row=story(991)
        with self.context([row]), patch.object(api,"db",return_value=self.db), patch.object(self.db,"close"):
            result=self.client.get('/api/search?q=Distinct%20archival%20phrase')
            self.assertEqual([x['id'] for x in result.json],[991])
            article=self.client.get('/api/news/991')
            self.assertEqual(article.status_code,200)
            self.assertIn('Distinct archival phrase',article.json['article'])
            page=self.client.get('/india/991-parliament-public-services-report-number-991')
            self.assertEqual(page.status_code,200)
            self.assertIn(b'Distinct archival phrase',page.data)

    def test_pagination_does_not_merge_similar_reports_on_different_dates(self):
        records=[story(i) for i in range(1001,1066)]
        with self.context(records), patch.object(api,"db",return_value=self.db), patch.object(self.db,"close"):
            first=self.client.get('/api/search?q=Parliament&limit=50').json
            second=self.client.get('/api/search?q=Parliament&limit=50&offset=50').json
            self.assertEqual(len(first),50)
            self.assertEqual(len(second),15)
            self.assertEqual(len({r['id'] for r in first+second}),65)

    def test_category_is_filtered_before_limit(self):
        records=[story(i,category='world') for i in range(1001,1066)]+[story(990,category='india')]
        with self.context(records), patch.object(api,"db",return_value=self.db), patch.object(self.db,"close"):
            result=self.client.get('/api/search?q=Parliament&limit=50&category=india')
            self.assertEqual([r['id'] for r in result.json],[990])

    def test_live_unpublished_record_suppresses_saved_copy_by_url(self):
        row=story(991)
        self.live(dict(row,id=1000000000000001),status='pending')
        with self.context([row]), patch.object(api,"db",return_value=self.db), patch.object(self.db,"close"):
            self.assertEqual(self.client.get('/api/search?q=Parliament').json,[])
            self.assertEqual(self.client.get('/api/news/991').status_code,404)
            self.assertIsNone(api._archive_row(991,self.db))

    def test_live_published_version_wins_without_duplicate_search_result(self):
        row=story(991)
        self.live(dict(row,id=1000000000000001))
        with self.context([row]), patch.object(api,"db",return_value=self.db), patch.object(self.db,"close"):
            result=self.client.get('/api/search?q=Parliament').json
            self.assertEqual([r['id'] for r in result],[1000000000000001])
            self.assertEqual(self.client.get('/api/news/991').json['id'],1000000000000001)

    def test_database_outage_keeps_historical_search_and_article_readable(self):
        with self.context([story(991)]), patch.object(api,"db",side_effect=DatabaseUnavailable('down')),patch.object(api,"_snapshot_rows",return_value=[]):
            self.assertEqual(self.client.get('/api/search?q=Parliament').json[0]['id'],991)
            self.assertEqual(self.client.get('/api/news/991').status_code,200)

    def test_retention_preserves_old_dates_and_excludes_private_fields(self):
        path=Path(self.tmp.name)/'archive.json.gz'
        old=dict(story(991),password_hash='secret',instagram_access_token='secret')
        archive.retain_public_records([old],path)
        archive.retain_public_records([story(992),dict(story(993),status='pending')],path)
        data=json.loads(gzip.decompress(path.read_bytes()))
        self.assertEqual({r['id'] for r in data},{991,992})
        self.assertEqual(data[0]['published_at'],'2026-09-20T10:00:00Z')
        self.assertNotIn('secret',json.dumps(data))
        before=path.read_bytes()
        archive.retain_public_records([story(992)],path)
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
