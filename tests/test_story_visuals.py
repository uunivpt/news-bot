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

    def test_index_ranges_are_not_presented_as_exact_metric_cards(self):
        for text in ['The AQI was 300–400 in Delhi.', 'AQI: 300-400.',
                     'Nifty was 24,100 to 24,200 points during trading.',
                     'Sensex: 80,000—81,000 points.', 'AQI: 300 or more.']:
            with self.subTest(text=text):
                self.assertIsNone(extract(story(text)))
                self.assertEqual(render(story(text)), '')

    def test_qualified_figures_and_both_range_endpoints_are_not_exact_observations(self):
        for text in [
            'Vote share: Party A: at least 55%; Party B: at most 45%.',
            'Vote share: Party A: roughly 55%; Party B: approximately 45%.',
            'Vote share: Party A: ≥55%; Party B: ≤45%.',
            'Rainfall: Mumbai: 100 mm to 120 mm; Pune: 80 mm to 90 mm.',
            'Vote share: Party A: between 50% and 55%; Party B: between 30% and 35%.',
            'Rainfall ranged from 100–120 mm in Mumbai.',
            'Growth was between 7 and 10 percent.',
            'Growth values were 7 and 10 percent.',
            'जागा: पक्ष अ: किमान ५० जागा; पक्ष ब: कमाल ४० जागा.',
            'पाऊस: मुंबई: १०० मिमी ते १२० मिमी.',
        ]:
            with self.subTest(text=text):
                self.assertIsNone(extract(story(text)))

    def test_uncertain_figures_do_not_turn_remaining_observations_into_a_partial_chart(self):
        data = extract(story('Seat tally: A: 50 seats; B: 40 seats; C: at least 10 seats.'))
        self.assertIsNone(data['chart'])
        self.assertEqual([p['value'] for p in data['facts']], [50, 40])
        data = extract(story('AQI was 300–400 in Delhi.\n\nThe AQI was 220 in Mumbai.'))
        self.assertEqual([p['value'] for p in data['facts']], [220])

    def test_exact_indices_currency_and_negative_observations_still_work(self):
        for text, values in [
            ('AQI was 344 in Delhi.', [344]),
            ('Nifty 50 was 24,100.50 points.', [24100.5]),
            ('Budget: Schools: ₹30 crore; Hospitals: ₹40 crore.', [30, 40]),
            ('GDP growth: Region A: -2.5%; Region B: 3.5%.', [-2.5, 3.5]),
        ]:
            with self.subTest(text=text):
                self.assertEqual([p['value'] for p in extract(story(text))['facts']], values)

    def test_index_names_and_component_counts_are_not_readings(self):
        for text in ['The Nifty 50 index rose in early trade.',
                     'Nifty 50 was around 24,100 points in early trade.',
                     'Nifty 50: at least 24,100 points.',
                     'Nifty 50 constituents were reviewed.',
                     'Sensex 30 stocks were discussed.',
                     'Sensex was 30 stocks in this comparison.',
                     'Nifty 50 was 300 points higher in early trade.',
                     'Sensex was 200 points lower in early trade.',
                     'Nifty 50 was 24,100 points or more.',
                     'Nifty 50 was 24,100 points to 24,200 points.',
                     'AQI was 300 AQI to 400 AQI.']:
            with self.subTest(text=text):
                self.assertIsNone(extract(story(text)))
                self.assertEqual(render(story(text)), '')

    def test_index_percentage_changes_remain_percentages_without_invented_levels(self):
        for text in ['The Nifty 50 fell 0.5 percent on Monday.',
                     'Nifty was 0.5% higher in early trade.',
                     'Sensex was 0.5 per cent higher in early trade.']:
            with self.subTest(text=text):
                facts = extract(story(text))['facts']
                self.assertEqual([(p['value'], p['unit']) for p in facts], [(0.5, '%')])

    def test_explicit_index_levels_keep_full_numeric_tokens_and_sentence_punctuation(self):
        for text, label, raw in [
            ('Nifty 50 was 24,100.500012 points.', 'Nifty 50', '24,100.500012'),
            ('Nifty 50 index stood at 24,100.5 points.', 'Nifty 50', '24,100.5'),
            ('Sensex: 80,123.45.', 'Sensex', '80,123.45'),
            ('The AQI was 344.', 'AQI', '344'),
            ('AQI ३४४ in Delhi.', 'AQI', '344'),
            ('AQI was 344.123456.', 'AQI', '344.123456'),
        ]:
            with self.subTest(text=text):
                facts = extract(story(text))['facts']
                self.assertEqual(len(facts), 1)
                self.assertEqual(facts[0]['label'], label)
                self.assertEqual(facts[0]['reported'], raw)
                self.assertEqual(facts[0]['value'], numeric(raw))
        for text in ['AQI: 344.5.6 in Delhi.', 'Sensex: 80,123abc in early trade.']:
            with self.subTest(text=text):
                self.assertIsNone(extract(story(text)))

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
