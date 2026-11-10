import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from app import article_visuals as visuals
from app.data_desk import page, highlights
from api import index as api


class DataDeskTests(unittest.TestCase):
    def setUp(self):
        registry_patch = patch.object(visuals, 'REGISTRY', Path(__file__).parent / 'fixtures' / 'article-visuals-2024.json')
        registry_patch.start()
        visuals.registry.cache_clear()
        self.addCleanup(visuals.registry.cache_clear)
        self.addCleanup(registry_patch.stop)

    def test_three_reviewed_series_are_distinct_and_new_series_do_not_attach_to_stories(self):
        data=visuals.catalog()
        self.assertEqual(len(data),3)
        self.assertEqual([d['points'][-1]['value']for d in data],[7.09927893176518,4.9530355097366,4.173])
        self.assertEqual(data[1]['article_ids'],[])
        self.assertEqual(data[2]['article_ids'],[])
        self.assertIsNone(visuals.for_article(data[1]['id']))
        self.assertIn('+0.001',visuals.render(data[2]))
        raw=copy.deepcopy(data[1]);raw['reviewed']=True
        self.assertIsNone(visuals.validate(raw))  # Empty associations need an explicit desk_only marker.
        raw['desk_only']=True
        self.assertIsNotNone(visuals.validate(raw))

    def test_public_pages_never_require_storage_or_remote_data(self):
        client=api.app.test_client()
        with patch.object(api,'db',side_effect=AssertionError('Public data must not need private storage')):
            response=client.get('/data/')
            cards=client.get('/api/data-desk/cards')
        self.assertEqual(response.status_code,200)
        self.assertIn('s-maxage=300',response.headers['Cache-Control'])
        self.assertEqual(response.text.count('class="data-bar '),18)
        self.assertEqual(cards.json['html'].count('class="data-bar '),6)
        self.assertIn('modeled ILO',response.text)
        self.assertIn('not live readings',response.text)
        self.assertIn('World Bank',response.text)
        self.assertIn('4.9530355097366',response.text)

    def test_empty_registry_keeps_honest_fallback_and_source_strings_are_escaped(self):
        with patch('app.data_desk.catalog',return_value=[]):
            self.assertEqual(highlights(),'')
            self.assertIn('temporarily unavailable',page('https://www.politicshub.in'))
        data=copy.deepcopy(visuals.catalog()[0]);data['measure']='<script>alert(1)</script>';data['id']='safe-unknown'
        with patch('app.data_desk.catalog',return_value=[data]):
            self.assertNotIn('<script>alert(1)',highlights())
            self.assertIn('&lt;script&gt;',highlights())
