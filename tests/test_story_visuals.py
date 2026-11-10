import unittest
from unittest.mock import patch
from app.story_visuals import extract,render,numeric
from api import index as api


def story(text):return {'id':991,'title':'Source report','article':text,'status':'published','source_name':'Example News','url':'https://example.org/news'}


class StoryVisualTests(unittest.TestCase):
    def test_only_explicit_data_is_used_and_unrelated_figures_do_not_appear(self):
        row=story('Seat tally: BJP: 132 seats; Congress: 99 seats; NCP: 41 seats.')
        data=extract(row)
        self.assertEqual(data['chart']['kind'],'bar')
        self.assertEqual([p['label']for p in data['chart']['points']],['BJP','Congress','NCP'])
        self.assertEqual([p['value']for p in data['chart']['points']],[132,99,41])
        self.assertNotIn('World Bank',render(row))
        self.assertEqual(render(story('A new policy was announced on 10 November 2026.')),'')
        self.assertNotIn('<svg',render(story('The reported AQI was 344 in Delhi.')))
        self.assertIn('344',render(story('The reported AQI was 344 in Delhi.')))

    def test_clear_comparison_measure_does_not_get_replaced_by_headline_topic(self):
        row={**story('Seat tally: Party A: 50 seats; Party B: 40 seats.'),'title':'Votes cast in the election'}
        self.assertEqual(extract(row)['chart']['kind'],'bar')

    def test_complete_vote_share_is_pie_but_missing_share_is_not_invented(self):
        complete=extract(story('Vote share: Party A: 55%; Party B: 45%.'))
        self.assertEqual(complete['chart']['kind'],'pie')
        partial=extract(story('Vote share: Party A: 55%; Party B: 30%.'))
        self.assertEqual(partial['chart']['kind'],'bar')
        self.assertEqual(sum(p['value']for p in partial['chart']['points']),85)
        self.assertNotIn('Other',render(story('Vote share: Party A: 55%; Party B: 30%.')))

    def test_year_table_renders_trend_and_retains_reported_precision(self):
        row=story('Year | GDP growth (%)\n2022 | 7.6001234%\n2023 | 7.2%\n2024 | 7.1%')
        self.assertEqual(extract(row)['chart']['kind'],'line')
        self.assertIn('7.6001234',render(row))
        self.assertIn('story-line',render(row))
        html=story('<table><tr><th>Year</th><th>GDP growth (%)</th></tr><tr><td>2023</td><td>7.2</td></tr><tr><td>2024</td><td>7.1</td></tr></table>')
        self.assertEqual(extract(html)['chart']['kind'],'line')

    def test_real_report_style_compares_regions_in_same_currency_unit(self):
        row=story('Chennai recorded liquor sales worth ₹95.85 crore, while the Tiruchi zone clocked ₹98.97 crore, followed by Madurai at ₹88.38 crore')
        data=extract(row)['chart']
        self.assertEqual(data['unit'],'₹ crore')
        self.assertEqual([p['label']for p in data['points']],['Chennai','Tiruchi zone','Madurai'])
        self.assertEqual([p['value']for p in data['points']],[95.85,98.97,88.38])

    def test_mixed_units_rates_ranges_and_inequalities_cannot_be_charted(self):
        for text in ['GDP growth: India: 7%; inflation: India: 4%.','Budget: Schools: ₹30 crore; hospitals: $40 million.','Rainfall: Mumbai: over 100 mm; Pune: about 80 mm.','GDP: 7-10 percent','Metric | Value (%)\nGDP growth | 7\nInflation | 4']:
            with self.subTest(text=text):self.assertIsNone((extract(story(text))or{}).get('chart'))
        self.assertIsNone(extract(story('Growth ranged from 7 to 10 percent.')))
        self.assertIsNone(numeric('1,,234'))
        self.assertEqual(numeric('1,23,456'),123456)

    def test_marathi_digits_units_and_escaped_context(self):
        row=story('जागा: पक्ष अ: ५० जागा; पक्ष ब: ४० जागा.')
        self.assertEqual([p['value']for p in extract(row)['chart']['points']],[50,40])
        row=story('Seat tally: <script>alert(1)</script>A: 50 seats; B: 40 seats.')
        self.assertNotIn('<script>',render(row))
        row['source_name']='<img src=x onerror=alert(1)>';row['url']='javascript:alert(1)'
        self.assertNotIn('href="javascript',render(row));self.assertNotIn('<img',render(row))

    def test_endpoint_follows_published_article_and_never_exposes_pending_copy(self):
        client=api.app.test_client()
        with patch.object(api,'article',return_value=(story('Seat tally: A: 20 seats; B: 10 seats.'),200)):
            self.assertIn('story-numbers',client.get('/api/article-visuals/991').json['html'])
        for status in ['pending','rejected']:
            with patch.object(api,'article',return_value=({**story('A: 20 seats; B: 10 seats.'),'status':status},200)):
                self.assertEqual(client.get('/api/article-visuals/991').json,{'html':''})
        with api.app.test_request_context('/'):
            html=api._article_html(story('Vote share: A: 55%; B: 45%.'))
        self.assertIn('story-slice',html)
