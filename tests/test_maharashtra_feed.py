import json
import socket
import unittest
from unittest.mock import Mock, patch

from api import maharashtra_feed as mh
from app.source_http import SourceDocument, UnsafeSourceURL

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Test</title><item><title>पुण्यात महत्त्वाची बातमी</title><link>https://www.tv9marathi.com/maharashtra/pune-1.html</link><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item><item><title>English headline</title><link>https://www.tv9marathi.com/maharashtra/english.html</link></item><item><title>दुसरी बातमी</title><link>https://malicious.example/bad</link></item></channel></rss>""".encode("utf-8")


class MaharashtraFeedTests(unittest.TestCase):
    def setUp(self):
        mh._cache.clear()

    def test_source_feed_remains_marathi_and_allowlisted(self):
        with patch.object(mh, "fetch_source", return_value=SourceDocument("https://www.tv9marathi.com/maharashtra/feed", SAMPLE, "application/rss+xml")) as fetch:
            rows = mh._read_one("TV9 Marathi", "https://www.tv9marathi.com/maharashtra/feed", ("www.tv9marathi.com",))
        self.assertEqual(fetch.call_args.kwargs['allowed_hosts'], ('www.tv9marathi.com',))
        self.assertEqual(fetch.call_args.kwargs['max_bytes'], 2_000_000)
        self.assertEqual(fetch.call_args.kwargs['timeout'], 10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "पुण्यात महत्त्वाची बातमी")
        self.assertEqual(rows[0]["category"], "maharashtra")
        self.assertEqual(rows[0]["source_name"], "TV9 Marathi")

    def test_source_redirects_cannot_leave_publisher_boundary(self):
        for target in ('https://127.0.0.1/private', 'https://other.example/feed', 'http://www.tv9marathi.com/feed'):
            response = Mock(status_code=302, headers={'Location': target}, content=SAMPLE)
            response.raise_for_status.return_value = None
            response.iter_content.return_value = iter([SAMPLE])
            with self.subTest(target=target), \
                 patch('app.source_http.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
                 patch('requests.get', return_value=response) as get:
                with self.assertRaises(UnsafeSourceURL):
                    mh._read_one('TV9 Marathi', 'https://www.tv9marathi.com/maharashtra/feed', ('www.tv9marathi.com',))
                self.assertEqual(get.call_count, 1)
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                response.close.assert_called_once()

    def test_source_body_is_bounded_before_reading_it_all(self):
        class StreamingResponse:
            status_code = 200
            headers = {'Content-Type': 'application/rss+xml'}
            consumed = 0
            closed = False
            @property
            def content(self):
                raise AssertionError('Maharashtra RSS must not eagerly read the full response')
            def raise_for_status(self):
                pass
            def iter_content(self, chunk_size):
                for chunk in (b'x' * 1_000_000, b'y' * 1_000_000, b'z', b'unread'):
                    self.consumed += 1
                    yield chunk
            def close(self):
                self.closed = True
        response = StreamingResponse()
        with patch('app.source_http.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
             patch('requests.get', return_value=response):
            with self.assertRaises(ValueError):
                mh._read_one('TV9 Marathi', 'https://www.tv9marathi.com/maharashtra/feed', ('www.tv9marathi.com',))
        self.assertEqual(response.consumed, 3)
        self.assertTrue(response.closed)

    def test_permitted_redirect_keeps_publisher_metadata(self):
        redirect = Mock(status_code=302, headers={'Location': '/canonical-feed'}, content=SAMPLE)
        final = Mock(status_code=200, headers={'Content-Type': 'application/rss+xml'}, content=SAMPLE)
        final.iter_content.return_value = iter([SAMPLE])
        with patch('app.source_http.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
             patch('requests.get', side_effect=[redirect, final]) as get:
            rows = mh._read_one('TV9 Marathi', 'https://www.tv9marathi.com/maharashtra/feed', ('www.tv9marathi.com',))
        self.assertEqual([call.args[0] for call in get.call_args_list], ['https://www.tv9marathi.com/maharashtra/feed', 'https://www.tv9marathi.com/canonical-feed'])
        self.assertEqual(rows[0]['title'], 'पुण्यात महत्त्वाची बातमी')
        self.assertEqual(rows[0]['url'], 'https://www.tv9marathi.com/maharashtra/pune-1.html')
        self.assertEqual(rows[0]['published_at'], '2026-10-27T12:00:00+00:00')
        redirect.close.assert_called_once()
        final.close.assert_called_once()

    def test_same_publisher_and_url_after_translation(self):
        original = [
            {"title": "पुण्यात महत्त्वाची बातमी", "url": "https://www.tv9marathi.com/maharashtra/a", "source_name": "TV9 Marathi", "language": "mr", "published_at": "2026-10-27T12:00:00Z"},
            {"title": "नागपूर जिल्ह्यात बातमी", "url": "https://marathi.abplive.com/news/maharashtra/b", "source_name": "ABP माझा", "language": "mr", "published_at": "2026-10-27T13:00:00Z"},
        ]
        mh._cache["original"] = {"result": {"items": original, "sources": {"TV9 Marathi": {"available": True}, "ABP माझा": {"available": True}}, "last_checked": "2026-10-27T13:00:00Z", "status": "ok", "refresh_minutes": 20}, "expires": mh.time.monotonic() + 1000}
        with patch.object(mh, "_translate_batch", return_value={0:"Important news from Pune",1:"News from Nagpur district"}) as translator:
            marathi = mh.get_feed("mr")
            english = mh.get_feed("en")
        self.assertEqual([r["url"] for r in marathi["items"]], [r["url"] for r in english["items"]])
        self.assertEqual([r["source_name"] for r in marathi["items"]], [r["source_name"] for r in english["items"]])
        self.assertEqual([r["published_at"] for r in marathi["items"]], [r["published_at"] for r in english["items"]])
        self.assertEqual(english["items"][0]["title"], "Important news from Pune")
        self.assertEqual(english["items"][1]["title"], "News from Nagpur district")
        self.assertEqual(english["translation_status"], "complete")
        translator.assert_called_once()

    def test_no_translation_preserves_marathi_without_inventing_english_sources(self):
        original = [{"title":"पुण्यात महत्त्वाची बातमी", "url":"https://www.tv9marathi.com/maharashtra/a", "source_name":"TV9 Marathi", "language":"mr"}]
        mh._cache["original"] = {"result":{"items":original,"sources":{"TV9 Marathi":{"available":True}},"refresh_minutes":20},"expires":mh.time.monotonic()+1000}
        with patch.object(mh, "_translate_batch", return_value={}):
            result = mh.get_feed("en")
        self.assertEqual(result["items"][0]["title"], original[0]["title"])
        self.assertEqual(result["items"][0]["url"], original[0]["url"])
        self.assertEqual(result["items"][0]["source_name"], "TV9 Marathi")
        self.assertEqual(result["translation_status"],"unavailable")
        self.assertFalse(result["items"][0]["translation_available"])

    def test_source_poll_shared_across_both_language_views(self):
        with patch.object(mh, "_read_one", return_value=[]) as read:
            with patch.object(mh, "_translate_batch", return_value={}):
                english = mh.get_feed("en")
                marathi = mh.get_feed("mr")
        self.assertEqual(read.call_count, 2)
        self.assertEqual(list(english["sources"]), ["TV9 Marathi", "ABP माझा"])
        self.assertEqual(english["sources"], marathi["sources"])

    def test_critical_vote_numbers_must_not_change(self):
        self.assertTrue(mh._valid_translation("पुणे २५ मतदान केंद्रे", "Pune has 25 polling centres"))
        self.assertFalse(mh._valid_translation("पुणे २५ मतदान केंद्रे", "Pune has 35 polling centres"))
        self.assertFalse(mh._valid_translation("पुणे २५ मतदान केंद्रे", "पुणे २५ मतदान केंद्रे"))

    def test_unavailable_rss_does_not_invent_items(self):
        from requests import Timeout
        with patch.object(mh, "_read_one", side_effect=Timeout("blocked")):
            result = mh.get_feed("mr")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["status"], "unavailable")

    def test_temporary_source_failure_preserves_dated_headlines(self):
        from requests import Timeout
        original = {'items':[{'title':'पुण्यात महत्त्वाची बातमी','url':'https://www.tv9marathi.com/maharashtra/a','source_name':'TV9 Marathi','published_at':'2026-10-27T12:00:00Z'}],
                    'sources':{},'last_checked':'2026-10-27T13:00:00Z','status':'ok','refresh_minutes':20}
        for error in (Timeout('temporary'), UnsafeSourceURL('blocked redirect fixture')):
            with self.subTest(error=type(error).__name__):
                mh._cache['original']={'result':original,'expires':0}
                with patch.object(mh,'_read_one',side_effect=error):
                    result=mh.get_feed('mr')
                self.assertEqual(result['items'],original['items'])
                self.assertEqual(result['status'],'stale')
                self.assertEqual(result['last_checked'],original['last_checked'])
                self.assertFalse(result['sources']['TV9 Marathi']['available'])

    def test_failed_translations_back_off_instead_of_retrying_per_reader(self):
        original=[{'title':'पुण्यात महत्त्वाची बातमी','url':'https://www.tv9marathi.com/maharashtra/a','source_name':'TV9 Marathi'}]
        mh._cache['original']={'result':{'items':original,'sources':{},'refresh_minutes':20},'expires':mh.time.monotonic()+1000}
        with patch.object(mh,'_translate_batch',return_value={}) as translator:
            for _ in range(10):
                self.assertEqual(mh.get_feed('en')['translation_status'],'unavailable')
        translator.assert_called_once()

    def test_route_forwards_language(self):
        from api.index import app
        with patch("api.maharashtra_feed.get_feed", return_value={"language":"en","items":[],"sources":{}}) as fake:
            response = app.test_client().get("/api/maharashtra?lang=en")
        self.assertEqual(response.status_code, 200)
        fake.assert_called_once_with("en")

    def test_retired_category_landings_redirect(self):
        from api.index import app
        for category in ("business","technology","sports","entertainment","science","health"):
            response = app.test_client().get("/"+category+"/")
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.headers["Location"], "/")
