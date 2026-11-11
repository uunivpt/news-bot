"""Download only the observations already shown in a public article or dataset."""
import csv
import io
import re

from .source_http import public_http_url

COLUMNS = ('observation', 'value', 'unit', 'measure', 'context', 'source_name',
           'source_url', 'original_data_url', 'source_updated_on', 'source_retrieved_on',
           'licence', 'licence_url', 'article_title', 'article_url', 'article_published_at')


def text_cell(value):
    """Quote spreadsheet formulas as text; numeric observations use a separate path."""
    value = str(value or '')
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def serialize(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([str(row.get(key, '')) if key == 'value' else text_cell(row.get(key, ''))
                         for key in COLUMNS])
    # Excel and other spreadsheet readers can recognize Marathi/Hindi as UTF-8.
    return '\ufeff' + output.getvalue()


def dataset_csv(data):
    source = data['source']
    context = {
        'unit': data['unit'], 'measure': data['measure'],
        'context': data['description'] + ' ' + data['note'],
        'source_name': source['name'], 'source_url': source['url'],
        'original_data_url': source['data_url'], 'source_updated_on': source['updated_on'],
        'source_retrieved_on': source['retrieved_on'], 'licence': source['license'],
        'licence_url': source['license_url'],
    }
    return serialize([{**context, 'observation': point['label'], 'value': point['value']}
                      for point in data['points']])


def article_csv(row, canonical_url):
    from .story_visuals import extract, numeric, NUM
    data = extract(row)
    if not data:
        return None
    source_url = str(row.get('url') or '')
    if not source_url.startswith('https://') or not public_http_url(source_url):
        source_url = ''
    metadata = {
        'source_name': row.get('source_name') or 'Original report', 'source_url': source_url,
        'licence': 'Original publisher rights apply', 'article_title': row.get('title'),
        'article_url': canonical_url,
        'article_published_at': row.get('published_at_iso') or row.get('published_at') or '',
    }
    chart = data['chart']
    observations = chart['points'] if chart else data['facts']
    rows = []
    for point in observations:
        # Only the extractor's validated numeric token bypasses formula escaping.
        raw = point.get('reported', str(point['value']))
        value = raw if re.fullmatch(NUM, raw) and numeric(raw) == point['value'] else str(point['value'])
        rows.append({**metadata, 'observation': point['label'] or 'Reported figure', 'value': value,
                     'unit': chart['unit'] if chart else point['unit'],
                     'measure': chart['measure'] if chart else point['label'] or 'Reported figure',
                     'context': chart['context'] if chart else point['context']})
    return serialize(rows)
