import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import public_archive
from app.news_numbers import news_number, number_index
from app.seo_indexing import canonical_path
from api import index as api

class NewsNumberTests(unittest.TestCase):
 def test_number_is_stable_when_title_or_category_changes(self):
  row={'id':17484337268349,'url':'https://example.org/news','title':'Original'}
  self.assertRegex(news_number(row),r'^\d{12}$')
  self.assertEqual(news_number(row),news_number(dict(row,title='Edited',category='world')))
 def test_aliases_survive_multiple_exports_and_open_as_canonical(self):
  with tempfile.TemporaryDirectory() as directory:
   file=Path(directory)/'archive.gz'
   row={'id':100,'url':'https://example.org/news','title':'A historical public news report title','summary':'A factual source summary. '*6,'bot_article':'The full original article remains readable. '*20,'public_source':True,'source_name':'Example','source_type':'rss','category':'india','published_at':'2026-10-01T10:00:00Z'}
   public_archive.retain_public_records([row],file)
   public_archive.retain_public_records([dict(row,id=200)],file)
   with patch.object(public_archive,'ARCHIVE_PATH',file),patch.object(api,'db',side_effect=RuntimeError('offline')),patch.object(api,'_hindi_rows',return_value=[]),patch.object(api,'_snapshot_rows',return_value=[]):
    public_archive._load.cache_clear()
    saved=public_archive.by_id(100)
    self.assertEqual(saved['id'],200)
    self.assertEqual(public_archive.by_id(news_number(row))['id'],200)
    client=api.app.test_client()
    old=client.get('/entertainment/100-old-headline')
    self.assertEqual(old.status_code,301)
    self.assertTrue(old.headers['Location'].endswith(canonical_path(saved)))
    page=client.get(old.headers['Location'])
    self.assertEqual(page.status_code,200)
    self.assertIn('News No. '+news_number(saved),page.text)
   public_archive._load.cache_clear()
 def test_ambiguous_number_prevents_publication(self):
  with patch('app.news_numbers.news_number',return_value='123456789012'):
   with self.assertRaises(ValueError):number_index([{'id':1,'url':'https://a.test'},{'id':2,'url':'https://b.test'}])
