"""The declared language must match Hindi reading content before JavaScript runs."""
import json
import re
import unittest
from unittest.mock import patch

from api import index as api


class ReadingLanguageTests(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()
        self.row = {
            'id': 88001, 'title': 'रेल सेवाओं में बदलाव के बारे में नई सूचना',
            'category': 'hindi', 'summary': 'रेलवे ने नई समय सारिणी की जानकारी दी।',
            'source_name': 'Fixture RSS', 'url': 'https://example.org/report',
            'published_at': '2026-11-01T10:00:00+00:00',
            'status': 'published', 'public_source': True,
        }

    def test_hindi_article_html_and_structured_data_declare_hindi(self):
        with patch.object(api, '_public_row_by_id', return_value=self.row):
            response = self.client.get('/api/seo-article' + api.article_path(self.row))
        self.assertEqual(response.status_code, 200)
        document = response.get_data(as_text=True)
        self.assertIn('<html lang="hi">', document)
        data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', document).group(1))
        self.assertEqual(data['inLanguage'], 'hi')
        self.assertEqual(data['headline'], self.row['title'])
        self.assertEqual(data['datePublished'], self.row['published_at'])
        self.assertIn(self.row['url'], document)
        self.assertIn(self.row['source_name'], document)

    def test_english_article_retains_english_language(self):
        row = dict(self.row, category='india', title='Public transport timetable update')
        document = api._article_html(row)
        self.assertIn('<html lang="en">', document)
        data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', document).group(1))
        self.assertEqual(data['inLanguage'], 'en')

    def test_server_rendered_hindi_desk_declares_hindi(self):
        with patch.object(api, '_public_rows_for_section', return_value=[self.row]):
            response = self.client.get('/api/seo-section/hindi')
        self.assertEqual(response.status_code, 200)
        document = response.get_data(as_text=True)
        self.assertIn('<html lang="hi"', document)
        self.assertIn(self.row['title'], document)

    def test_other_desks_keep_english_language(self):
        for category in ('all', 'india', 'world'):
            with self.subTest(category=category), patch.object(api, '_public_rows_for_section', return_value=[]):
                self.assertIn('<html lang="en"', api._section_html(category))
