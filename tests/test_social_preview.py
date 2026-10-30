"""Regression tests for multilingual WhatsApp/OG image generation."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from PIL import Image
from app.social_preview import _safe_preview_title, render_story


class SocialPreviewTests(unittest.TestCase):
    def test_devanagari_missing_font_never_renders_boxes(self):
        with patch("app.social_preview._devanagari_font_path", return_value=None):
            title = _safe_preview_title("Maharashtra Rain: महाराष्ट्रात अवकाळी पाऊस")
            self.assertNotIn("महाराष्ट्रात", title)
            self.assertIn("Maharashtra Rain", title)
            self.assertIn("Read the full story", title)

    def test_marathi_and_hindi_fallback_still_produce_valid_png(self):
        with patch("app.social_preview._devanagari_font_path", return_value=None):
            for title, category in [
                ("महाराष्ट्रात मुसळधार पाऊस", "India"),
                ("Maharashtra Rain: महाराष्ट्रात अवकाळी पाऊस", "India"),
                ("दिल्ली में भारी बारिश", "हिंदी"),
            ]:
                with self.subTest(title=title):
                    payload = render_story(title, category)
                    image = Image.open(io.BytesIO(payload))
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (1200, 630))
                    self.assertGreater(len(payload), 5000)


if __name__ == "__main__":
    unittest.main()
