import unittest

from app.category_routing import normalize_category
from scripts.repair_news_categories import classify


class EditorialCategoryRoutingTests(unittest.TestCase):
    def test_nana_patekar_always_goes_to_india(self):
        self.assertEqual(normalize_category("entertainment", "Nana Patekar dies at 75"), "india")
        self.assertEqual(normalize_category("entertainment", "Tributes continue", "Nana Patekar in Goa"), "india")

    def test_indian_cultural_obituaries_go_to_india(self):
        self.assertEqual(normalize_category("entertainment", "Bollywood actor dies at 82"), "india")
        self.assertEqual(normalize_category("entertainment", "Singer passes away", "The Indian film industry mourns."), "india")
        self.assertEqual(normalize_category("entertainment", "Funeral for Marathi film star"), "india")

    def test_normal_entertainment_stays_in_entertainment(self):
        self.assertEqual(normalize_category("entertainment", "Bollywood film releases tomorrow"), "entertainment")
        self.assertEqual(normalize_category("entertainment", "Nana's latest concert releases"), "entertainment")

    def test_foreign_obituary_not_assigned_india_without_indian_connection(self):
        self.assertEqual(normalize_category("entertainment", "Hollywood actor dies at 88"), "entertainment")

    def test_legacy_repair_obeys_india_rule(self):
        self.assertEqual(classify("Bollywood actor passes away", "Indian cinema mourns"), "india")

    def test_does_not_override_unrelated_category(self):
        self.assertEqual(normalize_category("sports", "Indian cricket match today"), "sports")
        self.assertEqual(normalize_category("politics", "Election votes counted in India"), "politics")


if __name__ == "__main__":
    unittest.main()
