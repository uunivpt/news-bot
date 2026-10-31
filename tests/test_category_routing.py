import unittest

from app.category_routing import normalize_category
from scripts.repair_news_categories import classify


class EditorialCategoryRoutingTests(unittest.TestCase):
    def test_entertainment_preserved_as_news_under_active_desk(self):
        self.assertEqual(normalize_category("entertainment", "Bollywood film releases tomorrow"), "india")
        self.assertEqual(normalize_category("entertainment", "Hollywood film releases tomorrow"), "world")
        self.assertEqual(normalize_category("entertainment", "Actor campaigns in election"), "politics")
        self.assertEqual(normalize_category("entertainment", "Deepika Padukone and Ranveer Singh"), "india")

    def test_other_retired_desks_do_not_disappear(self):
        self.assertEqual(normalize_category("technology", "Indian startup launches smartphone"), "india")
        self.assertEqual(normalize_category("business", "US company reports global earnings"), "world")
        self.assertEqual(normalize_category("sports", "Election campaign debate"), "politics")
        self.assertEqual(normalize_category("health", "State hospital upgrades services"), "india")

    def test_nana_patekar_and_legacy_repair(self):
        self.assertEqual(normalize_category("entertainment", "Nana Patekar dies at 75"), "india")
        self.assertEqual(classify("Bollywood actor passes away", "Indian cinema mourns"), "india")

    def test_existing_active_categories_unaffected(self):
        self.assertEqual(normalize_category("world", "Indian trade delegation visits USA"), "world")
        self.assertEqual(normalize_category("politics", "Election votes counted"), "politics")
        self.assertEqual(normalize_category("hindi", "भारत की ताजा खबरें"), "hindi")


if __name__ == "__main__":
    unittest.main()
