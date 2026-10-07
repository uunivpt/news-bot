import unittest
from app.remotion_reel_renderer import build_story_props


class RemotionStoryPropsTests(unittest.TestCase):
    def test_maps_newsroom_fields_to_template_contract(self):
        props = build_story_props({
            "title": "A complete PoliticsHub headline",
            "category": "politics",
            "published_at": "2026-10-07T03:30:00+00:00",
            "source_name": "Example Newswire",
            "summary": "The essential verified context for the story.",
            "image_url": "/tmp/story.jpg",
        })
        self.assertEqual(props["HEADLINE"], "A complete PoliticsHub headline")
        self.assertEqual(props["CATEGORY"], "politics")
        self.assertEqual(props["DATE"], "07 OCT 2026")
        self.assertEqual(props["LOCATION"], "NEWS DESK")
        self.assertEqual(props["SOURCE"], "Example Newswire")
        self.assertEqual(props["IMAGE"], "/tmp/story.jpg")
        self.assertFalse(props["AUDIO"])

    def test_never_emits_empty_required_template_fields(self):
        props = build_story_props({})
        for key in ("HEADLINE", "CATEGORY", "DATE", "LOCATION", "SOURCE", "SUMMARY"):
            self.assertTrue(props[key])


if __name__ == "__main__":
    unittest.main()
