import unittest
from app.editorial_gate import longform_review, word_count

class LongformGateTests(unittest.TestCase):
    def test_short_excerpt_is_held_even_with_automated_screen(self):
        result = longform_review({
            "bot_article": "News update. " * 30,
            "summary": "This is a sufficiently detailed summary of a report.",
        }, verification={"passed": True})
        self.assertFalse(result["passed"])
        self.assertIn("insufficient_original_longform_material", result["errors"])

    def test_eight_hundred_words_with_no_evidence_screen_is_held(self):
        article = " ".join("detail%s" % i for i in range(820))
        result = longform_review({
            "bot_article": article,
            "summary": "An independently verified and relevant factual report.",
        })
        self.assertFalse(result["passed"])
        self.assertIn("automated_evidence_check_required", result["errors"])

    def test_automatic_screened_substantive_report_passes_structural_gate(self):
        article = " ".join("detail%s" % i for i in range(820))
        result = longform_review({
            "bot_article": article,
            "summary": "An independently researched and sourced report about developments.",
        }, verification={"passed": True})
        self.assertTrue(result["passed"])
        self.assertEqual(result["words"], 820)

    def test_unicode_word_count(self):
        self.assertEqual(word_count("महाराष्ट्र बातम्या and news"), 4)

if __name__ == "__main__":
    unittest.main()
