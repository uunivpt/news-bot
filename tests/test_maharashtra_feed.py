import unittest
from unittest.mock import patch, Mock
from api import maharashtra_feed as mh

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Test</title><item><title>पुण्यात महत्त्वाची बातमी</title><link>https://www.tv9marathi.com/maharashtra/pune-1.html</link><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item><item><title>English Title</title><link>https://www.tv9marathi.com/maharashtra/english.html</link></item><item><title>दुसरी बातमी</title><link>https://malicious.example/bad</link></item></channel></rss>""".encode("utf-8")

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


 def test_english_mode_filters_non_maharashtra_and_devanagari(self):
  xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>English</title><item><title>Nagpur voter turnout reported</title><link>https://www.thehindu.com/news/national/maharashtra/nagpur-test.ece</link></item><item><title>Politics in Delhi today</title><link>https://www.thehindu.com/news/national/delhi-test.ece</link></item></channel></rss>""".encode("utf-8")
  with patch.object(mh.requests,"get",return_value=Mock(content=xml,raise_for_status=lambda:None)):
   rows=mh._read_one("The Hindu","https://www.thehindu.com/news/national/feeder/default.rss",("www.thehindu.com",),language="en")
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]["language"],"en")
 def test_languages_are_separate_and_not_fabricated_translations(self):
  mh._cache={}
  with patch.object(mh,"_read_one",return_value=[]):
   english=mh.get_feed("en")
  self.assertEqual(english["language"],"en")
  self.assertEqual(english["items"],[])
  self.assertIn("not automatic translations",english["editorial_note"])

 def test_language_route_exposes_separate_publisher_feeds(self):
  from api.index import app
  from unittest.mock import patch
  with patch("api.maharashtra_feed.get_feed",return_value={"language":"en","items":[],"sources":{}}) as fake:
   response=app.test_client().get("/api/maharashtra?lang=en")
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.json["language"],"en")
  fake.assert_called_once_with("en")

 def test_decommissioned_sections_redirect_without_deleting_articles(self):
  from api.index import app
  client=app.test_client()
  for section in ("business","technology","sports","entertainment","science","health"):
   response=client.get("/"+section+"/")
   self.assertEqual(response.status_code,301)
   self.assertEqual(response.headers["Location"],"/")
