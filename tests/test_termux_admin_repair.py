import unittest

from scripts.termux_admin_repair import module_file, dependencies


class TermuxAdminRepairTests(unittest.TestCase):
    def test_module_paths(self):
        self.assertEqual(module_file("api.index"), "api/index.py")
        self.assertEqual(module_file("app.newsletter"), "app/newsletter.py")
        self.assertEqual(module_file("app"), "app/__init__.py")
        self.assertIsNone(module_file("requests"))

    def test_resolves_absolute_and_relative_imports(self):
        source = """
from app.database import NewsDatabase
from app import public_archive
from .public_sessions import PublicSessionInterface
from urllib.request import urlopen
"""
        self.assertEqual(set(dependencies("app.web", source)),
                         {"app", "app.database", "app.public_archive", "app.public_sessions"})

    def test_detects_api_modules(self):
        source = "from api.maharashtra_feed import get_feed\n"
        self.assertIn("api.maharashtra_feed", set(dependencies("api.index", source)))


if __name__ == "__main__":
    unittest.main()
