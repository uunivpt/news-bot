"""Refresh the existing annual indicators from their exact WDI series only."""
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path
import tempfile

from .article_visuals import validate
from .source_http import fetch_source

# Stable IDs preserve existing article associations and saved /data/ anchors.
INDICATORS = {
    'india-gdp-growth-2019-2024': 'NY.GDP.MKTP.KD.ZG',
    'india-consumer-price-inflation-2019-2024': 'FP.CPI.TOTL.ZG',
    'india-unemployment-2019-2024': 'SL.UEM.TOTL.ZS',
}


def data_url(indicator):
    return f'https://api.worldbank.org/v2/country/IND/indicator/{indicator}?format=json&per_page=100&source=2'


def observations(payload, indicator, today):
    """Reject wrong series, incomplete pages, missing/invalid data and regressions."""
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError('Expected a World Bank metadata/observations response')
    meta, rows = payload
    if (not isinstance(meta, dict) or str(meta.get('sourceid')) != '2'
            or meta.get('page') != 1 or meta.get('pages') != 1
            or not isinstance(rows, list) or not rows or len(rows) > 100
            or meta.get('total') != len(rows)):
        raise ValueError('Incomplete or unexpected WDI response')
    updated = date.fromisoformat(meta['lastupdated'])
    if updated > today:
        raise ValueError('Provider update date is in the future')
    points, years = [], set()
    for row in rows:
        if (not isinstance(row, dict) or row.get('countryiso3code') != 'IND'
                or not isinstance(row.get('indicator'), dict)
                or row['indicator'].get('id') != indicator):
            raise ValueError('Country or indicator mismatch')
        year = row.get('date')
        if not isinstance(year, str) or len(year) != 4 or not year.isascii() or not year.isdigit():
            raise ValueError('Invalid annual observation label')
        if year in years or not 1960 <= int(year) <= today.year:
            raise ValueError('Duplicate or future annual observation')
        years.add(year)
        value = row.get('value')
        if value is None:
            continue  # Unreleased years are missing, never zero.
        if type(value) not in (int, float) or not math.isfinite(value) or not -100 <= value <= 1000:
            raise ValueError('Invalid annual rate')
        if indicator == 'SL.UEM.TOTL.ZS' and not 0 <= value <= 100:
            raise ValueError('Invalid unemployment percentage')
        points.append({'label': year, 'value': value})
    points.sort(key=lambda p: p['label'])
    if len(points) < 6:
        raise ValueError('Not enough published annual observations')
    return points[-6:], updated.isoformat()


def refresh_dataset(raw, payload, today):
    indicator = INDICATORS[raw['id']]
    points, updated = observations(payload, indicator, today)
    if points[-1]['label'] < max(p['label'] for p in raw['points']):
        raise ValueError('Provider response would roll back the latest observation')
    if updated < raw['source']['updated_on']:
        raise ValueError('Provider response is older than the stored release')
    candidate = deepcopy(raw)
    candidate['points'] = points
    candidate['source'].update(data_url=data_url(indicator), updated_on=updated, retrieved_on=today.isoformat())
    if not validate(candidate):
        raise ValueError('Refreshed dataset failed registry validation')
    return candidate


def refresh(path, *, today=None, fetch=None):
    """Keep each last good series on error; atomically save verified successes."""
    today = today or date.today()
    fetch = fetch or (lambda url: json.loads(fetch_source(
        url, allowed_hosts=['api.worldbank.org'], timeout=30, max_bytes=500_000).content))
    path = Path(path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('version') != 1 or not isinstance(raw.get('datasets'), list):
        raise ValueError('Unsupported registry')
    ids = [d.get('id') for d in raw['datasets']]
    if any(ids.count(key) != 1 for key in INDICATORS):
        raise ValueError('Expected exactly one of each configured annual indicator')
    errors, results = [], []
    for index, data in enumerate(raw['datasets']):
        if data.get('id') not in INDICATORS:
            continue
        try:
            if not validate(data):
                raise ValueError('Existing registry entry is invalid')
            candidate = refresh_dataset(data, fetch(data_url(INDICATORS[data['id']])), today)
            raw['datasets'][index] = candidate
            results.append(f"{data['id']}: latest {candidate['points'][-1]['label']}, checked {today}")
        except Exception as error:
            errors.append(f"{data['id']}: {type(error).__name__}: {error}")
    content = json.dumps(raw, ensure_ascii=False, indent=2) + '\n'
    changed = content != path.read_text(encoding='utf-8')
    if changed:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return changed, results, errors
