import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.image_acquisition import (
    _license_allowed,
    _score_candidate,
    build_image_queries,
    acquire_story_image,
)


class ImageAcquisitionTests(unittest.TestCase):
    def test_queries_use_headline_terms(self):
        queries = build_image_queries("India Pakistan border conflict", "Troops met near the border", "world")
        joined = " | ".join(queries).lower()
        self.assertIn("india", joined)
        self.assertIn("pakistan", joined)
        self.assertIn("conflict", joined)

    def test_license_filter(self):
        self.assertTrue(_license_allowed("cc0"))
        self.assertTrue(_license_allowed("by-sa"))
        self.assertFalse(_license_allowed("copyright"))
        self.assertFalse(_license_allowed(""))

    def test_candidate_score_prefers_relevant_image(self):
        item = {
            "title": "India Pakistan border conflict",
            "description": "Border meeting",
            "creator": "Test Photographer",
            "width": 1600,
            "height": 900,
            "license": "cc0",
        }
        score = _score_candidate(
            item,
            "India Pakistan border conflict",
            "Troops met near the border",
            "India Pakistan conflict",
        )
        self.assertGreaterEqual(score, 25)

    @patch("app.image_acquisition._openverse_search")
    @patch("app.image_acquisition.requests.get")
    def test_acquires_relevant_open_image(self, mock_get, mock_search):
        image = Image.new("RGB", (1280, 720), "black")
        payload = io.BytesIO()
        image.save(payload, format="JPEG")
        payload.seek(0)

        mock_search.return_value = [{
            "url": "https://images.example/test.jpg",
            "foreign_landing_url": "https://example.org/photo",
            "license": "cc0",
            "license_version": "1.0",
            "creator": "Test Creator",
            "provider": "Example",
            "title": "India Pakistan border conflict",
            "description": "Border conflict",
            "tags": [{"name": "India"}, {"name": "Pakistan"}, {"name": "border"}],
            "width": 1280,
            "height": 720,
        }]

        response = unittest.mock.Mock()
        response.raise_for_status.return_value = None
        response.content = payload.getvalue()
        mock_get.return_value = response

        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_story_image({
                "id": 42,
                "title": "India Pakistan border conflict",
                "summary": "Troops met near the border.",
                "category": "world",
            }, tmp)
            self.assertTrue(Path(result["image_local_path"]).exists())
            self.assertEqual(result["image_license"], "CC0 1.0")
            self.assertGreaterEqual(result["image_selection_score"], 25)


if __name__ == "__main__":
    unittest.main()
