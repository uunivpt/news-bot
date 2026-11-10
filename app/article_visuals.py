"""Source-validated article data; no number extraction or request-time remote reads.

The public registry is bundled with the application. Editorially selected story
identities opt into a dataset; arbitrary feed fields can never supply markup.
"""
from datetime import date
from functools import lru_cache
from html import escape
import json
import math
from pathlib import Path
import re

from .news_numbers import news_number
from .source_http import public_http_url

REGISTRY = Path(__file__).resolve().parent / 'data' / 'article-visuals.json'


def text(value, limit=500):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def valid_url(value):
    return isinstance(value, str) and value.startswith('https://') and public_http_url(value)


def validate(raw):
    """Return a small positive projection, or reject the entire dataset."""
    if not isinstance(raw, dict) or raw.get('reviewed') is not True:
        return None
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,79}', str(raw.get('id', ''))):
        return None
    for key in ('title', 'series', 'measure', 'unit', 'difference_unit', 'description', 'note'):
        if not text(raw.get(key)):
            return None
    ids, points, source = raw.get('article_ids'), raw.get('points'), raw.get('source')
    if not isinstance(ids, list) or not 0 <= len(ids) <= 50 or (not ids and raw.get('desk_only') is not True) or any(not re.fullmatch(r'[1-9][0-9]{0,18}', str(x)) for x in ids):
        return None
    if not isinstance(points, list) or not 2 <= len(points) <= 24 or not isinstance(source, dict):
        return None
    if not all(valid_url(source.get(k)) for k in ('url', 'data_url', 'license_url')):
        return None
    if not all(text(source.get(k), 200) for k in ('name', 'license')):
        return None
    try:
        updated = date.fromisoformat(source['updated_on'])
        retrieved = date.fromisoformat(source['retrieved_on'])
        if updated > retrieved:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    clean, labels = [], set()
    for point in points:
        if not isinstance(point, dict) or not text(point.get('label'), 60):
            return None
        value, label = point.get('value'), point['label'].strip()
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e12 or label in labels:
            return None
        labels.add(label)
        clean.append({'label': label, 'value': value})
    return {**{k: raw[k] for k in ('id', 'title', 'series', 'measure', 'unit', 'difference_unit', 'description', 'note')},
            'article_ids': list(map(str, ids)), 'points': clean,
            'source': {k: source[k] for k in ('name', 'url', 'data_url', 'license', 'license_url', 'updated_on', 'retrieved_on')}}


@lru_cache(maxsize=1)
def registry():
    try:
        if REGISTRY.stat().st_size > 200_000:
            return {}
        raw = json.loads(REGISTRY.read_text(encoding='utf-8'))
        if raw.get('version') != 1 or not isinstance(raw.get('datasets'), list) or len(raw['datasets']) > 30:
            return {}
        result = {}
        for candidate in raw['datasets']:
            data = validate(candidate)
            if not data:
                continue
            if data['id'] in result:
                return {}
            result[data['id']] = data
            for identity in data['article_ids']:
                for key in (identity, news_number({'id': int(identity)})):
                    # Conflicting assignments are a registry error, not a choice
                    # between two inconsistent public charts.
                    if key in result:
                        return {}
                    result[key] = data
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def catalog():
    return list({data['id']: data for data in registry().values()}.values())


def for_article(identity):
    return registry().get(str(identity)) if str(identity).isdigit() else None


def number(value, signed=False):
    value = 0 if abs(value) < .005 else value
    return format(value, '+,.2f' if signed else ',.2f')


def freshness(data, today=None):
    """Never describe an unchecked snapshot as current during a refresh outage."""
    today = today or date.today()
    checked = date.fromisoformat(data['source']['retrieved_on'])
    overdue = (today - checked).days > 2 or checked > today
    label = 'Source check overdue' if overdue else 'Source checked'
    return label, overdue


def render(data):
    """Semantic HTML, a true-zero SVG axis, and an accessible exact-value table."""
    if not data:
        return ''
    e = lambda value: escape(str(value), quote=True)
    points, source, key = data['points'], data['source'], data['id']
    check_label, overdue = freshness(data)
    freshness_note = ('Showing the last verified annual observations; a newer provider release may be available.' if overdue
                      else 'Annual observations; the observation year is separate from the source check date.')
    latest, previous = points[-1], points[-2]
    unit = data['unit']
    change = latest['value'] - previous['value']
    change_label = format(change, '+.3f') if 1e-6 <= abs(change) < .005 else number(change, True)
    cards = [(latest['label'] + ' · newest stored observation', number(latest['value']) + unit, data['measure']),
             (previous['label'] + ' · previous observation', number(previous['value']) + unit, data['measure']),
             ('Change between these observations', change_label, data['difference_unit'])]
    metrics = ''.join('<div class="article-data-metric"><span>' + e(label) + '</span><strong>' + e(value) + '</strong><small>' + e(context) + '</small></div>' for label, value, context in cards)
    values = [p['value'] for p in points]
    low, high = min(0, min(values)), max(0, max(values))
    span = max(high - low, 1e-9) if high != low else 1
    power = 10 ** math.floor(math.log10(span / 4))
    step = next((n * power for n in (1, 2, 5, 10) if n * power >= span / 4), 10 * power)
    low, high = math.floor(low / step) * step, math.ceil(high / step) * step
    if low == high:
        high = low + step
    y = lambda value: 270 - (value - low) / (high - low) * 240
    baseline = y(0)
    ticks = []
    for index in range(round((high - low) / step) + 1):
        value = low + step * index
        ticks.append(f'<line x1="62" x2="700" y1="{y(value):.2f}" y2="{y(value):.2f}" class="data-grid"/><text x="52" y="{y(value) + 4:.2f}" text-anchor="end">{e(f"{value:g}")}</text>')
    bars = []
    slot = 638 / len(points)
    for index, point in enumerate(points):
        value = point['value']
        x = 62 + slot * index + slot * .18
        width, top = slot * .64, min(y(value), baseline)
        height = abs(y(value) - baseline)
        label = f"{point['label']} · {data['series']}: {number(value)}{unit}"
        bars.append(f'<g><rect class="data-bar {"data-negative" if value < 0 else ""}" x="{x:.2f}" y="{top:.2f}" width="{width:.2f}" height="{max(height, 1):.2f}" rx="4" tabindex="0" role="img" aria-label="{e(label)}" data-label="{e(point["label"])}" data-value="{e(number(value) + unit)}"><title>{e(label)}</title></rect><text x="{x + width / 2:.2f}" y="{top - 9 if value >= 0 else top + height + 17:.2f}" text-anchor="middle" class="data-value">{e(number(value))}</text><text x="{x + width / 2:.2f}" y="310" text-anchor="middle">{e(point["label"])}</text></g>')
    rows = ''.join('<tr><th scope="row">' + e(p['label']) + '</th><td>' + e(p['value']) + '</td></tr>' for p in points)
    crowded = ' data-crowded' if len(points) > 8 else ''
    return f'''<section class="article-data" aria-labelledby="{key}-title">
<p class="article-data-eyebrow">THE NUMBERS / DATA IN CONTEXT</p><h2 id="{key}-title">{e(data['title'])}</h2>
<p class="article-data-description">{e(data['description'])}</p><div class="article-data-metrics">{metrics}</div>
<figure><figcaption id="{key}-caption">{e(data['series'])} · {e(data['measure'])}</figcaption>
<div class="article-data-chart{crowded}"><svg viewBox="0 0 720 340" role="group" aria-labelledby="{key}-caption"><g>{''.join(ticks)}</g><line class="data-zero" x1="62" x2="700" y1="{baseline:.2f}" y2="{baseline:.2f}"/>{''.join(bars)}</svg><div class="article-data-tooltip" hidden aria-hidden="true"></div></div>
<p class="article-data-scroll-hint">Swipe horizontally to see every observation.</p><p class="article-data-note">{e(data['note'])}</p></figure>
<p class="article-data-freshness" role="status">{e(check_label)}: {e(source['retrieved_on'])}. {e(freshness_note)}</p>
<p class="article-data-source">Source: <a href="{e(source['url'])}" target="_blank" rel="noopener noreferrer">{e(source['name'])}</a> · Data updated {e(source['updated_on'])} · Retrieved {e(source['retrieved_on'])}. <a href="{e(source['data_url'])}" target="_blank" rel="noopener noreferrer">Original data</a> · <a href="{e(source['license_url'])}">{e(source['license'])}</a></p>
<details class="article-data-table"><summary>View exact values and data table</summary><div><table><caption>{e(data['measure'])} · {e(data['series'])}</caption><thead><tr><th scope="col">Observation</th><th scope="col">Value ({e(unit)})</th></tr></thead><tbody>{rows}</tbody></table></div></details></section>'''
