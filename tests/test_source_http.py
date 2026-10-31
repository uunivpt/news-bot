import socket
import unittest
from unittest.mock import Mock, patch

import requests
from app.source_http import fetch_source, public_http_url, UnsafeSourceURL, SourceDocument
from app.source_text import source_text
from app.article_fetcher import extract_public_article
from api import index as api


def response(body=b"a source response", *, status=200, headers=None, chunks=None):
    result = Mock(status_code=status, headers=headers or {"Content-Type": "text/html"})
    result.iter_content.return_value = iter(chunks if chunks is not None else [body])
    result.raise_for_status.return_value = None
    return result


class SourceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch("app.source_http.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def test_private_credentials_ports_and_malformed_destinations_are_blocked(self):
        values = ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/",
                  "http://10.0.0.1/", "http://192.168.0.1/", "http://localhost/", "http://service.internal/",
                  "https://user:password@example.com/", "https://@example.com/", "https://example.com:8443/",
                  "https://example.com\\@127.0.0.1/", "https://example.com/\nheader", "ftp://example.com/",
                  "http://[::ffff:127.0.0.1]/", "http://100.64.0.1/", "http://[::]/",
                  "http://224.0.0.1/", "http://[fec0::1]/"]
        for url in values:
            with self.subTest(url=url), patch("app.source_http.requests.get") as get:
                self.assertFalse(public_http_url(url))
                with self.assertRaises(UnsafeSourceURL):
                    fetch_source(url)
                get.assert_not_called()

    def test_dns_resolving_private_address_is_blocked_before_http(self):
        for addresses in (["127.0.0.1"], ["8.8.8.8", "10.0.0.1"]):
            with patch("app.source_http.socket.getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]), \
                 patch("app.source_http.requests.get") as get:
                with self.assertRaises(UnsafeSourceURL):
                    fetch_source("https://source.example.org/")
                get.assert_not_called()

    def test_redirect_is_validated_before_next_request_and_response_is_closed(self):
        first = response(status=302, headers={"Location": "http://169.254.169.254/"})
        with patch("app.source_http.requests.get", return_value=first) as get:
            with self.assertRaises(UnsafeSourceURL):
                fetch_source("http://example.org/")
        self.assertEqual(get.call_count, 1)
        first.close.assert_called_once()

    def test_allowed_host_boundary_blocks_cross_publisher_redirects(self):
        first = response(status=301, headers={"Location": "https://example.org.evil.com/"})
        with patch("app.source_http.requests.get", return_value=first) as get:
            with self.assertRaises(UnsafeSourceURL):
                fetch_source("https://example.org/", allowed_hosts={"example.org"})
        self.assertEqual(get.call_count, 1)

    def test_public_same_publisher_redirect_succeeds_without_automatic_redirects(self):
        first = response(status=301, headers={"Location": "https://www.example.org/feed"})
        second = response(body=b"<rss/>")
        with patch("app.source_http.requests.get", side_effect=[first, second]) as get:
            result = fetch_source("https://example.org/feed", timeout=7, allowed_hosts={"example.org"})
        self.assertEqual(result.url, "https://www.example.org/feed")
        self.assertEqual(result.content, b"<rss/>")
        for call in get.call_args_list:
            self.assertTrue(call.kwargs["stream"])
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertLessEqual(call.kwargs["timeout"], 7)
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_https_cannot_be_downgraded(self):
        first = response(status=302, headers={"Location": "http://example.org/feed"})
        with patch("app.source_http.requests.get", return_value=first) as get:
            with self.assertRaises(UnsafeSourceURL):
                fetch_source("https://example.org/feed")
        self.assertEqual(get.call_count, 1)

    def test_both_declared_and_streamed_size_are_bounded(self):
        for result in [response(headers={"Content-Length": "1000"}), response(chunks=[b"1234", b"5678"])]:
            with patch("app.source_http.requests.get", return_value=result):
                with self.assertRaisesRegex(ValueError, "size limit"):
                    fetch_source("https://example.org/feed", max_bytes=7)
            result.close.assert_called_once()

    def test_redirect_loop_does_not_repeat_requests(self):
        first = response(status=302, headers={"Location": "/feed"})
        with patch("app.source_http.requests.get", return_value=first) as get:
            with self.assertRaisesRegex(UnsafeSourceURL, "loop"):
                fetch_source("https://example.org/feed")
        self.assertEqual(get.call_count, 1)

    def test_slow_stream_hits_deadline_and_closes_the_response(self):
        result = response()
        with patch("app.source_http.requests.get", return_value=result), \
             patch("app.source_http.time.monotonic", side_effect=[0, 0, 2]):
            with self.assertRaises(requests.Timeout):
                fetch_source("https://example.org/feed", timeout=1)
        result.close.assert_called_once()

    def test_redirect_chain_cannot_exceed_five_requests(self):
        replies = [response(status=302, headers={"Location": f"/step/{index}"}) for index in range(5)]
        with patch("app.source_http.requests.get", side_effect=replies) as get:
            with self.assertRaisesRegex(UnsafeSourceURL, "redirect limit"):
                fetch_source("https://example.org/feed")
        self.assertEqual(get.call_count, 5)
        self.assertTrue(all(reply.close.call_count == 1 for reply in replies))

    def test_article_enrichment_refuses_internal_urls(self):
        with patch("app.source_http.requests.get") as get:
            self.assertIsNone(extract_public_article("http://127.0.0.1/private"))
        get.assert_not_called()


class SourceTextTests(unittest.TestCase):
    def test_encoded_markup_and_script_content_do_not_become_reader_copy(self):
        value = '&lt;p class="publisher"&gt;महाराष्ट्र &lt;strong&gt;news&lt;/strong&gt;&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;'
        self.assertEqual(source_text(value), "महाराष्ट्र news")

    def test_article_paragraphs_survive_cleanup(self):
        self.assertEqual(source_text("<p>First <b>report</b>.</p><p>Second report.</p>", paragraphs=True),
                         "First report.\nSecond report.")
        self.assertEqual(source_text("First paragraph.\nSecond paragraph.", paragraphs=True),
                         "First paragraph.\nSecond paragraph.")

    def test_public_api_and_article_markup_are_plain_text(self):
        row = {"id": 44, "title": "Public source report on a new government announcement", "category": "india",
               "source_name": "Example", "url": "https://example.com/report", "status": "published",
               "summary": "&lt;p class=\"publisher\"&gt;Original source summary.&lt;/p&gt;",
               "bot_article": "<p>First report.</p><p>Second report.</p>"}
        with api.app.test_request_context("/"):
            result = api._publicize(row)
            self.assertEqual(result["summary"], "Original source summary.")
            self.assertEqual(result["article"], "First report.\nSecond report.")
            rendered = api._article_html(result)
        self.assertNotIn("&lt;p", rendered)
        self.assertIn("<p>First report.</p><p>Second report.</p>", rendered)


class PublicImageSafetyTests(unittest.TestCase):
    def image_response(self, content_type):
        database = Mock()
        database.get_by_id.return_value = {"id": 1, "status": "published", "source_type": "rss",
            "image_url": "https://images.example.com/photo.png", "image_source": "article-source", "image_license": "CC0"}
        document = SourceDocument("https://images.example.com/photo.png", b"image bytes", content_type)
        with patch.object(api, "db", return_value=database), patch.object(api, "fetch_source", return_value=document) as fetch:
            result = api.app.test_client().get("/api/image/1")
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["max_bytes"], 8 * 1024 * 1024)
        return result

    def test_public_proxy_refuses_svg_and_html_active_documents(self):
        for content_type in ("image/svg+xml", "text/html"):
            self.assertEqual(self.image_response(content_type).status_code, 404)

    def test_public_proxy_preserves_raster_image_cache_and_nosniff(self):
        result = self.image_response("image/png")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.mimetype, "image/png")
        self.assertEqual(result.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("s-maxage=86400", result.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
