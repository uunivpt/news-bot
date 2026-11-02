import unittest
from app.editorial_research import Evidence, build_research_brief

class EditorialResearchTests(unittest.TestCase):
    def test_empty_evidence_cannot_be_drafted(self):
        report = build_research_brief("A headline", [])
        self.assertFalse(report["ready_for_longform_draft"])
        self.assertTrue(report["requires_human_verification"])

    def test_duplicate_url_does_not_inflate_evidence(self):
        text = " ".join(f"fact{i}" for i in range(520))
        reports = [Evidence("Publisher", "https://example.org/story", text),
                   Evidence("Publisher", "https://example.org/story#section", text)]
        report = build_research_brief("A headline", reports)
        self.assertEqual(report["source_count"], 1)
        self.assertEqual(report["distinct_hosts"], 1)
        self.assertTrue(report["ready_for_longform_draft"])

    def test_short_excerpt_is_not_padded(self):
        report = build_research_brief("Headline", [Evidence("News", "https://news.example/a", "Small summary.")])
        self.assertFalse(report["ready_for_longform_draft"])
        self.assertEqual(report["evidence_words"], 2)

if __name__ == "__main__":
    unittest.main()
