import gzip
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.database import NewsDatabase
from app.models import NewsItem
from app.phone_publication import deliver_publication, delivery_status, run_pending
from scripts.mobile_sync_upload import sync_public_rows


NOW = datetime.now(timezone.utc)


def reviewed():
    return dict(id=455, title='Regional public transport authority announces revised commuter services',
                url='https://example.org/transport', source_name='Official source', source_type='manual',
                summary='The transport authority published its revised commuter service timetable and an explanation of the changes.',
                bot_article='The official timetable explains the revised service hours. ' * 20,
                category='india', published_at=NOW.isoformat(), published_at_site=NOW.isoformat(),
                status='published', public_source=True, approved_at=NOW.isoformat(), fact_check_status='reviewed')


class DurableDeliveryTests(unittest.TestCase):
    def test_failed_public_sync_preserves_database_publication_and_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            db = NewsDatabase(str(Path(folder)/'db.sqlite'))
            row = reviewed()
            db.insert(NewsItem(source_name=row['source_name'], source_type='manual', title=row['title'],
                               url=row['url'], summary=row['summary'], public_source=True))
            db.update(1, status='published', approved_at=row['approved_at'],
                      fact_check_status='reviewed', bot_article=row['bot_article'])
            with patch.dict('os.environ', {'POLITICSHUB_LOCAL_ADMIN':'0'}):
                queued = deliver_publication(1, database=db)
            self.assertEqual(queued['state'], 'not_configured')
            self.assertFalse(queued['configured'])
            result = run_pending(db, uploader=lambda rows: (_ for _ in ()).throw(OSError('private infrastructure')))
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(db.get_by_id(1)['status'], 'published')
            self.assertNotIn('private infrastructure', delivery_status(db, 1)['last_error'])
            db.close()
            db = NewsDatabase(str(Path(folder)/'db.sqlite'))
            result = run_pending(db, uploader=lambda rows: {'commit_sha':'a'*40, 'public_urls':{'1':'https://www.politicshub.in/india/1-report?v='+'a'*40}})
            self.assertEqual(result['state'], 'synced')
            receipt = delivery_status(db, 1)
            self.assertEqual(receipt['attempts'], 2)
            self.assertEqual(receipt['commit_sha'], 'a'*40)
            self.assertEqual(deliver_publication(1, database=db)['state'], 'synced')
            self.assertEqual(run_pending(db, uploader=lambda rows: self.fail('already synced'))['processed'], 0)
            db.close()


class RealGitDeliveryTests(unittest.TestCase):
    def git(self, directory, *args):
        return subprocess.check_output(['git','-C',str(directory),*args], text=True, stderr=subprocess.DEVNULL).strip()

    def test_one_push_preserves_full_manuscript_feed_archive_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); remote=root/'remote.git'; seed=root/'seed'; managed=root/'delivery'
            subprocess.run(['git','init','--bare','--initial-branch=main',str(remote)], check=True, capture_output=True)
            subprocess.run(['git','init','--initial-branch=main',str(seed)], check=True, capture_output=True)
            (seed/'public').mkdir(); (seed/'public/news-data.json').write_text('[]\n')
            self.git(seed,'add','public/news-data.json')
            self.git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.org','commit','-m','seed')
            self.git(seed,'remote','add','origin',str(remote)); self.git(seed,'push','origin','main')
            first=sync_public_rows([{**reviewed(),'internal_access_token':'private fixture'}],managed,str(remote),now=NOW)
            self.assertEqual(len(first['commit_sha']),40)
            self.assertIn('?v='+first['commit_sha'],first['public_urls']['455'])
            current=self.git(remote,'show','main:public/news-data.json')
            self.assertEqual(json.loads(current)[0]['bot_article'],reviewed()['bot_article'].strip())
            self.assertNotIn('internal_access_token',self.git(remote,'show','main:public/mobile-reviewed.json'))
            archived=json.loads(gzip.decompress(subprocess.check_output(['git','-C',str(remote),'show','main:app/data/public-archive.json.gz'])))
            self.assertEqual(archived[0]['id'],455)
            self.assertNotIn('approved_at',archived[0])
            second=sync_public_rows([reviewed()],managed,str(remote),now=NOW)
            self.assertEqual(second['commit_sha'],first['commit_sha'])
            edited={**reviewed(),'bot_article':reviewed()['bot_article']+' Editor added a checked explanatory paragraph.'}
            third=sync_public_rows([edited],managed,str(remote),now=NOW)
            self.assertNotEqual(third['commit_sha'],first['commit_sha'])
            final=json.loads(self.git(remote,'show','main:public/news-data.json'))
            self.assertIn('Editor added',final[0]['bot_article'])

    def test_unknown_existing_directory_is_never_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'private.txt').write_text('local file')
            with self.assertRaises(ValueError):
                sync_public_rows([reviewed()],Path(folder),'/not/a/remote',now=NOW)
            self.assertEqual((Path(folder)/'private.txt').read_text(),'local file')

    def test_existing_public_identity_is_kept_in_feed_archive_and_export(self):
        for archive_only in (False, True):
            with self.subTest(archive_only=archive_only), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); remote=root/'remote.git'; seed=root/'seed'; managed=root/'delivery'
                subprocess.run(['git','init','--bare','--initial-branch=main',str(remote)], check=True, capture_output=True)
                subprocess.run(['git','init','--initial-branch=main',str(seed)], check=True, capture_output=True)
                (seed/'public').mkdir()
                old={**reviewed(),'id':900,'bot_article':'An earlier public manuscript. '*30}
                (seed/'public/news-data.json').write_text(json.dumps([] if archive_only else [old]))
                (seed/'app/data').mkdir(parents=True)
                (seed/'app/data/public-archive.json.gz').write_bytes(gzip.compress(json.dumps([old]).encode()))
                self.git(seed,'add','.')
                self.git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.org','commit','-m','seed')
                self.git(seed,'remote','add','origin',str(remote)); self.git(seed,'push','origin','main')
                result=sync_public_rows([reviewed()],managed,str(remote),now=NOW)
                self.assertIn('/900-',result['public_urls']['455'])
                exported=json.loads(self.git(remote,'show','main:public/mobile-reviewed.json'))
                self.assertEqual(exported[0]['id'],900)
                public=json.loads(self.git(remote,'show','main:public/news-data.json'))
                self.assertEqual(public[0]['id'],900)
