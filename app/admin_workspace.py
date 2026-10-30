"""Small, explicit newsroom projections shared by live and recovery workspaces."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json

EDITORIAL_FIELDS = ('title', 'summary', 'bot_summary', 'category')


def editorial_revision(row):
    return hashlib.sha256(json.dumps([str(row.get(key) or '') for key in EDITORIAL_FIELDS],
                                    ensure_ascii=False).encode()).hexdigest()

LIST_FIELDS = ('id', 'title', 'url', 'category', 'source_name', 'source_type',
               'status', 'fact_check_status', 'published_at', 'published_at_site',
               'collected_at', 'image_url', 'summary', 'bot_summary', 'view_count')


def timestamp(row):
    raw = row.get('published_at_site') or row.get('published_at') or row.get('collected_at')
    try:
        dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def project_rows(rows, *, snapshot=False, now=None):
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    result = []
    for raw in rows:
        raw = dict(raw)
        row = {key: raw.get(key) for key in LIST_FIELDS}
        row['summary'] = str(raw.get('bot_summary') or raw.get('summary') or '')[:1600]
        row.pop('bot_summary', None)
        row['title'] = str(row.get('title') or 'Untitled')[:500]
        row['status'] = 'published' if snapshot else row.get('status') or 'pending'
        if snapshot:
            row['fact_check_status'] = None  # Public copies cannot establish moderation state.
            row['collected_at'] = None
        row['article_available'] = bool(raw.get('article_length') or raw.get('bot_article') or raw.get('article'))
        row['timestamp'] = timestamp(raw)
        row['quality_flags'] = []
        if not row['summary'].strip(): row['quality_flags'].append('Missing summary')
        if not row.get('image_url'): row['quality_flags'].append('No image')
        if not str(row.get('url') or '').startswith(('https://', 'http://')): row['quality_flags'].append('Missing source link')
        if not row['article_available']: row['quality_flags'].append('No article body')
        if row.get('fact_check_status') == 'needs_review': row['quality_flags'].append('Needs review')
        if row['timestamp'] is None: row['quality_flags'].append('Missing date')
        elif now - row['timestamp'] > 86400: row['quality_flags'].append('Older than 24 hours')
        result.append(row)
    return result


def coverage(rows):
    def grouped(key):
        return [{'name': name, 'count': count} for name, count in
                Counter(str(row.get(key) or 'Unknown') for row in rows).most_common()]
    return {'sources': grouped('source_name'), 'categories': grouped('category'),
            'quality': [{'name': name, 'count': count} for name, count in
                        Counter(flag for row in rows for flag in row['quality_flags']).most_common()],
            'sample_size': len(rows)}
