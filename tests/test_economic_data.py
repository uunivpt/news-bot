import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from app import article_visuals as visuals
from app.economic_data import INDICATORS, data_url, observations, refresh, refresh_dataset

FIXTURE = Path(__file__).parent / 'fixtures' / 'article-visuals-2024.json'
TODAY = date(2026, 11, 10)


def payload(indicator, latest=2025):
    return [{'page': 1, 'pages': 1, 'total': 8, 'sourceid': '2', 'lastupdated': '2026-10-08'}, [
        {'countryiso3code': 'IND', 'indicator': {'id': indicator}, 'date': str(year),
         'value': None if year == latest + 1 else 4.123456789 + (year - latest) / 10}
        for year in range(latest + 1, latest - 7, -1)]]


class EconomicDataTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(FIXTURE.read_text())
        self.gdp = self.raw['datasets'][0]
        self.indicator = INDICATORS[self.gdp['id']]

    def test_latest_non_null_year_and_revisions_replace_fixed_window_without_losing_identity(self):
        data = refresh_dataset(self.gdp, payload(self.indicator), TODAY)
        self.assertEqual([p['label'] for p in data['points']], list(map(str, range(2020, 2026))))
        self.assertEqual(data['points'][-1]['value'], 4.123456789)
        self.assertNotEqual(data['points'][-2]['value'], self.gdp['points'][-1]['value'])
        self.assertEqual(data['id'], self.gdp['id'])
        self.assertEqual(data['article_ids'], self.gdp['article_ids'])
        self.assertEqual(data['source']['retrieved_on'], '2026-11-10')
        self.assertNotIn('date=', data['source']['data_url'])
        self.assertNotIn('2024', data['source']['data_url'])
        # Future runs discover the next release without a code/config year edit.
        advanced = refresh_dataset(data, payload(self.indicator, latest=2026), date(2027, 1, 2))
        self.assertEqual(advanced['points'][-1]['label'], '2026')

    def test_rejects_incomplete_wrong_country_wrong_series_bad_dates_and_values(self):
        good = payload(self.indicator)
        mutations = [
            lambda p: p[0].update(pages=2),
            lambda p: p[0].update(total=9),
            lambda p: p[0].update(sourceid='1'),
            lambda p: p[0].update(lastupdated='2027-01-01'),
            lambda p: p[1][1].update(countryiso3code='USA'),
            lambda p: p[1][1]['indicator'].update(id='WRONG'),
            lambda p: p[1][1].update(date=p[1][2]['date']),
            lambda p: p[1][1].update(date='2027'),
            lambda p: p[1][1].update(value=True),
            lambda p: p[1][1].update(value='4.1'),
            lambda p: p[1][1].update(value=float('nan')),
            lambda p: p[1][1].update(value=float('inf')),
            lambda p: p[1][1].update(value=1001),
            lambda p: p[1].__setitem__(slice(1, 4), [dict(r, value=None) for r in p[1][1:4]]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                broken = copy.deepcopy(good); mutate(broken)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    observations(broken, self.indicator, TODAY)
        with self.assertRaises(ValueError):
            observations({'message': 'provider unavailable'}, self.indicator, TODAY)
        unemployment = payload('SL.UEM.TOTL.ZS'); unemployment[1][1]['value'] = -1
        with self.assertRaises(ValueError):
            observations(unemployment, 'SL.UEM.TOTL.ZS', TODAY)

    def test_old_provider_response_cannot_rollback_latest_year_or_release_date(self):
        for candidate in (payload(self.indicator, latest=2023), payload(self.indicator)):
            if candidate[1][1]['date'] == '2025':
                candidate[0]['lastupdated'] = '2026-10-07'
            with self.assertRaises(ValueError):
                refresh_dataset(self.gdp, candidate, TODAY)

    def test_partial_failure_preserves_failed_series_and_check_date_but_updates_other_series(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registry.json'; path.write_text(json.dumps(self.raw))
            def fetch(url):
                indicator = next(i for i in INDICATORS.values() if i in url)
                if indicator == 'SL.UEM.TOTL.ZS':
                    raise TimeoutError('provider timeout')
                return payload(indicator)
            checked_day = date(2026, 11, 11)
            changed, results, errors = refresh(path, today=checked_day, fetch=fetch)
            saved = json.loads(path.read_text())
            self.assertTrue(changed); self.assertEqual(len(results), 2); self.assertEqual(len(errors), 1)
            self.assertEqual(saved['datasets'][2], self.raw['datasets'][2])
            self.assertEqual(saved['datasets'][0]['points'][-1]['label'], '2025')
            # Same successful responses/day do not generate another deployment.
            self.assertFalse(refresh(path, today=checked_day, fetch=fetch)[0])
            # The following day's successful source check records a truthful date.
            refresh(path, today=date(2026, 11, 12), fetch=lambda url: payload(next(i for i in INDICATORS.values() if i in url)))
            self.assertEqual(json.loads(path.read_text())['datasets'][2]['source']['retrieved_on'], '2026-11-12')

    def test_freshness_warns_after_missed_checks_without_claiming_a_new_observation(self):
        data = visuals.validate(self.gdp)
        self.assertFalse(visuals.freshness(data, TODAY)[1])
        self.assertTrue(visuals.freshness(data, date(2026, 11, 13))[1])
        self.assertTrue(visuals.freshness(data, date(2026, 11, 9))[1])
        from unittest.mock import patch
        with patch('app.article_visuals.freshness', return_value=('Source check overdue', True)):
            rendered = visuals.render(data)
        self.assertIn('a newer provider release may be available', rendered)
        self.assertIn('newest stored observation', rendered)
        self.assertIn('2024', rendered)

    def test_registry_on_disk_remains_valid_and_source_url_is_not_year_limited(self):
        actual = json.loads(visuals.REGISTRY.read_text())
        for data in actual['datasets']:
            self.assertIsNotNone(visuals.validate(data))
            self.assertEqual(len(data['points']), 6)
            self.assertEqual(data['source']['data_url'], data_url(INDICATORS[data['id']]))
