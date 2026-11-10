import unittest

from app.article_format import render_inline_markdown
from api.index import _article_html


class ArticleBoldFormattingTests(unittest.TestCase):
    def test_bold_dateline_and_paragraphs_in_server_render(self):
        row = {
            "id": 88, "title": "Test newsroom report", "category": "world",
            "summary": "Summary of a public news event.",
            "bot_article": "**Washington, November 9, 2026:** The White House was temporarily closed." + chr(10)*2 +
                           "The **Secret Service** responded.",
            "source_name": "PoliticsHub", "source_type": "manual",
        }
        rendered = _article_html(row)
        self.assertIn("<strong>Washington, November 9, 2026:</strong>", rendered)
        self.assertIn("The <strong>Secret Service</strong> responded.", rendered)
        self.assertNotIn("**Washington", rendered)

    def test_safe_html_and_ampersands(self):
        value = "**A & B** <img src=x onerror=alert(1)>"
        self.assertEqual(render_inline_markdown(value),
                         "<strong>A &amp; B</strong> &lt;img src=x onerror=alert(1)&gt;")
        self.assertNotIn("<img", render_inline_markdown(value))

    def test_plain_and_unmatched_markers_stay_plain(self):
        self.assertEqual(render_inline_markdown("Nothing to format."), "Nothing to format.")
        self.assertEqual(render_inline_markdown("**not closed"), "**not closed")
        self.assertEqual(render_inline_markdown("****"), "****")
        self.assertEqual(render_inline_markdown("** bold**"), "** bold**")

    def test_summary_markdown_formatted_without_changing_metadata(self):
        row = {
            "id": 90, "title": "News report", "category": "india",
            "summary": "**Key update:** Officials respond.",
            "bot_article": "A separate full paragraph explains this story.",
            "source_name": "Source", "source_type": "manual",
        }
        result = _article_html(row)
        self.assertIn('<p class="dek"><strong>Key update:</strong> Officials respond.</p>', result)
        self.assertIn('content="**Key update:** Officials respond."', result)


if __name__ == "__main__":
    unittest.main()
