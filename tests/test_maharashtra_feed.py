import unittest
from unittest.mock import patch, Mock
from api import maharashtra_feed as mh

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Test</title><item><title>पुण्यात महत्त्वाची बातमी</title><link>https://www.tv9marathi.com/maharashtra/pune-1.html</link><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item><item><title>English Title</title><link>https://www.tv9marathi.com/maharashtra/english.html</link></item><item><title>दुसरी बातमी</title><link>https://malicious.example/bad</link></item></channel></rss>"""

class TestMaharashtraFeeds(unittest.TestCase):
 def test_publisher_rss_only_marathi_and_approved_source_domain(self):
  with patch.object(mh.requests,"get",return_value=Mock(content=SAMPLE,raise_for_status=lambda:None)):
   rows=mh._read_one("TV9 Marathi","https://www.tv9marathi.com/maharashtra/feed",("www.tv9marathi.com",))
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]["title"],"पुण्यात महत्त्वाची बातमी")
  self.assertEqual(rows[0]["category"],"maharashtra")
  self.assertTrue(rows[0]["published_at"])
 def test_timeout_or_block_does_not_fake_current_news(self):
  from requests import Timeout
  mh._cache={"expires":0,"result":None}
  with patch.object(mh,"_read_one",side_effect=Timeout("unavailable")):
   out=mh.get_feed()
  self.assertEqual(out["status"],"unavailable")
  self.assertEqual(out["items"],[])
  self.assertFalse(out["sources"]["TV9 Marathi"]["available"])

