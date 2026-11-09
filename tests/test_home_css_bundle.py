"""The committed homepage bundle must track source edits without adding imports."""
import tempfile
import unittest
from pathlib import Path

from scripts.build_home_css import OUTPUT, SOURCES, build_bundle


class HomepageCSSBundleTests(unittest.TestCase):
    def test_source_edits_require_regeneration_and_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            (assets / 'site.css').write_text("@import url('https://fonts.googleapis.com/css2?family=Example:wght@400;700');\nbody{color:red}\n")
            (assets / 'editorial.css').write_text('body{color:blue}\n')
            (assets / 'polish.css').write_text('body{color:green}\n')
            self.assertFalse(build_bundle(assets, check=True))
            self.assertFalse((assets / OUTPUT).exists())
            build_bundle(assets)
            original = (assets / OUTPUT).read_bytes()
            text = original.decode('utf-8')
            self.assertNotIn('@import', text)
            self.assertLess(text.index('color:red'), text.index('color:blue'))
            self.assertLess(text.index('color:blue'), text.index('color:green'))
            self.assertTrue(build_bundle(assets, check=True))
            for index, source in enumerate(SOURCES):
                with self.subTest(source=source):
                    path = assets / source
                    path.write_text(path.read_text() + f'.new-rule-{index}{{display:block}}\n')
                    self.assertFalse(build_bundle(assets, check=True))
                    self.assertEqual((assets / OUTPUT).read_bytes(), original)
                    build_bundle(assets)
                    self.assertTrue(build_bundle(assets, check=True))
                    original = (assets / OUTPUT).read_bytes()
                    self.assertIn(f'.new-rule-{index}', original.decode('utf-8'))

    def test_unreviewed_import_does_not_overwrite_the_existing_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            for source in SOURCES:
                (assets / source).write_text('body{color:red}\n')
            build_bundle(assets)
            original = (assets / OUTPUT).read_bytes()
            (assets / 'polish.css').write_text('@import url("https://example.org/new.css");\n')
            with self.assertRaisesRegex(ValueError, 'polish.css: unsupported @import'):
                build_bundle(assets)
            self.assertEqual((assets / OUTPUT).read_bytes(), original)
