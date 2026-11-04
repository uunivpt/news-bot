import unittest
from app.editorial_verification import assess_automatic_publication

def research(a, b):
    return {"sources": [
        {"url": "https://publisher-one.example/a", "excerpt": a},
        {"url": "https://publisher-two.example/b", "excerpt": b},
    ], "evidence_words": 1100}

class AutomatedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.source = " ".join("verified context detail evidence background research government policy report updated information".split() * 80)
        self.article = self.source[:]
        self.summary = "Verified context about an announced policy with clear background details"

    def test_requires_two_domains(self):
        r = research(self.source, self.source)
        r["sources"][1]["url"] = "https://publisher-one.example/b"
        checked = assess_automatic_publication("Government policy update", self.summary, self.article, r)
        self.assertIn("two_substantive_publisher_sources_required", checked["errors"])

    def test_blocks_unsupported_numbers(self):
        r = research(self.source, self.source)
        checked = assess_automatic_publication("Government policy update", self.summary, self.article + " The amount is 987654.", r)
        self.assertIn("unsupported_numbers", checked["errors"])

    def test_sensitive_claims_held(self):
        r = research(self.source, self.source)
        checked = assess_automatic_publication("Election news announcement", self.summary, self.article, r)
        self.assertIn("sensitive_claims_need_manual_or_official_confirmation", checked["errors"])

    def test_well_supported_non_sensitive_draft_passes_screen(self):
        r = research(self.source, self.source)
        checked = assess_automatic_publication("Government policy update", self.summary, self.article, r)
        self.assertTrue(checked["passed"], checked["errors"])

if __name__ == "__main__":
    unittest.main()
