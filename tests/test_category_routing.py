import unittest

from app.category_routing import normalize_category, is_political_headline
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

    def test_politics_topical_headlines_preserve_original_india_category(self):
        for title in (
            "Naidu asks NDA leaders to focus on local body polls",
            "Congress seeks arrest over remarks on Mahatma Gandhi",
            "Three AAP MLAs join BJP in Punjab",
            "राष्ट्रवादीचे आमदार विधानसभेत पोहोचले",
            "India Parliament passes a significant new public services law",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_political_headline(title))
                self.assertEqual(normalize_category("india", title), "india")
        self.assertFalse(is_political_headline("Government notifies new grievance rules"))
        self.assertFalse(is_political_headline("Services of nurses invaluable, says Minister"))
        self.assertEqual(normalize_category("world", "Congress meets in Europe"), "world")

    def test_marathi_publishers_do_not_mix_into_india_listing(self):
        from api import index as api
        marathi = {"id": 101, "category": "india", "source_name": "TV9 Marathi - Maharashtra",
                   "title": "Maharashtra assembly news"}
        abp = dict(marathi, id=102, source_name="ABP Majha - Maharashtra")
        national = dict(marathi, id=103, source_name="The Hindu - India")
        self.assertTrue(api._matches_public_desk(marathi, "maharashtra"))
        self.assertTrue(api._matches_public_desk(abp, "maharashtra"))
        self.assertFalse(api._matches_public_desk(marathi, "india"))
        self.assertFalse(api._matches_public_desk(abp, "india"))
        self.assertTrue(api._matches_public_desk(national, "india"))
        self.assertFalse(api._matches_public_desk(marathi, "all"))
        self.assertEqual(api.article_path(marathi), api.article_path(dict(marathi)))

    def test_home_only_english_india_and_world(self):
        from api import index as api
        english_india={"category":"india","title":"India Parliament passes a bill","source_name":"The Hindu"}
        english_world={"category":"world","title":"Global trade summit begins","source_name":"Reuters"}
        hindi={"category":"india","title":"भारत में बड़ी खबर","source_name":"Hindi publisher"}
        marathi={"category":"india","title":"महाराष्ट्रातील बातमी","language":"mr","source_name":"Local"}
        regional_english={"category":"maharashtra","title":"Maharashtra local update"}
        self.assertTrue(api._matches_public_desk(english_india,"all"))
        self.assertTrue(api._matches_public_desk(english_world,"all"))
        for item in (hindi,marathi,regional_english):
            self.assertFalse(api._matches_public_desk(item,"all"))
            self.assertFalse(api._matches_public_desk(item,"india"))
        self.assertTrue(api._matches_public_desk(hindi,"hindi"))
        self.assertTrue(api._matches_public_desk(marathi,"maharashtra"))

    def test_existing_active_categories_unaffected(self):
        self.assertEqual(normalize_category("world", "Indian trade delegation visits USA"), "world")
        self.assertEqual(normalize_category("politics", "Election votes counted"), "politics")
        self.assertEqual(normalize_category("hindi", "भारत की ताजा खबरें"), "hindi")


if __name__ == "__main__":
    unittest.main()
