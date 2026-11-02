"""Read-only configured publisher inventory and complete storage coverage.

The newsroom queue is deliberately bounded. Source coverage is aggregated by
the database instead of inferred from that queue, and configuration never
implies that a feed has actually been fetched successfully.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .source_http import public_http_url

ROOT = Path(__file__).resolve().parents[1]


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _public_link(value):
    value = str(value or "")
    return value if public_http_url(value) else None


def _collection_checks(database):
    """An older phone may have no telemetry yet. Never create it on a GET."""
    if database._postgres:
        exists = database.conn.execute("SELECT to_regclass('ph_source_collection') AS name").fetchone()['name']
    else:
        exists = database.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ph_source_collection'").fetchone()
    if not exists:
        return {}
    return {(row['source_type'], row['source_name']): dict(row) for row in
            database.conn.execute("SELECT * FROM ph_source_collection").fetchall()}


def _config():
    # Keep parsing/default resolution identical to the actual collector.
    from .collector import load_sources
    return load_sources(str(ROOT / 'config/sources.json'))


def source_inventory(database=None, *, rows=None, config=None, now=None):
    now = now or datetime.now(timezone.utc)
    errors = []
    if config is None:
        try:
            config = _config()
        except (OSError, ValueError, TypeError):
            config = {}
            errors.append('Source configuration unavailable')
    checks = {}
    aggregates = {}
    categories = set()
    scope = 'database' if database is not None else 'snapshot' if rows is not None else 'unavailable'
    if database is not None:
        for raw in database.conn.execute("""SELECT source_name,COUNT(*) AS story_count,
            MAX(collected_at) AS latest_collected_at,
            MAX(CASE WHEN status='published' THEN COALESCE(NULLIF(published_at_site,''),published_at) END) AS latest_published_at
            FROM news_items GROUP BY source_name""").fetchall():
            aggregates[str(raw['source_name'] or 'Unknown')] = dict(raw)
        categories = {str(row['category'] or 'general') for row in
                      database.conn.execute('SELECT DISTINCT category FROM news_items').fetchall()}
        try:
            checks = _collection_checks(database)
        except Exception:
            # Collection telemetry is optional. A failed read must not erase
            # available database counts or mark a source as successfully checked.
            errors.append('Source collection history unavailable')
    elif rows is not None:
        for raw in rows:
            name = str(raw.get('source_name') or 'Unknown')
            aggregate = aggregates.setdefault(name, {'story_count': 0, 'latest_collected_at': None, 'latest_published_at': None})
            aggregate['story_count'] += 1
            categories.add(str(raw.get('category') or 'general'))
            stamp = raw.get('published_at_site') or raw.get('published_at')
            if _stamp(stamp) and (not _stamp(aggregate['latest_published_at']) or _stamp(stamp) > _stamp(aggregate['latest_published_at'])):
                aggregate['latest_published_at'] = stamp
    configured = {}
    for kind, sources in config.items():
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict) or not str(source.get('name') or '').strip():
                continue
            name = str(source['name']).strip()
            configured.setdefault(name, []).append((kind, source))
    items = []
    for name in sorted(set(configured) | set(aggregates), key=str.casefold):
        definitions = configured.get(name, [])
        kinds = sorted({kind for kind, _ in definitions})
        enabled = any(source.get('enabled', True) for _, source in definitions)
        source_categories = sorted({str(source.get('category') or 'general') for _, source in definitions})
        source = next((source for _, source in definitions if source.get('enabled', True)), definitions[0][1] if definitions else {})
        section = next(iter(source.get('sections') or []), None)
        link = _public_link(source.get('url') or section)
        if not link and source.get('domain'):
            link = _public_link('https://' + str(source['domain']))
        candidates = [checks[(kind, name)] for kind in kinds if (kind, name) in checks]
        check = max(candidates, key=lambda row: str(row.get('last_attempt_at') or ''), default={})
        status = 'unknown'
        if definitions and not enabled:
            status = 'disabled'
        elif scope != 'database':
            status = 'unknown'
        elif kinds == ['hindi_rss']:
            status = 'external_pipeline'
        elif definitions:
            status = str(check.get('status') or 'awaiting_collection')
            # A real historical check isn't a promise that the worker is still
            # running. Expose overdue checks without inventing a new failure.
            last_attempt = _stamp(check.get('last_attempt_at'))
            try:
                interval = max(20, int(source.get('check_every_minutes') or 20))
            except (TypeError, ValueError):
                interval = 20
            if last_attempt and status in {'healthy', 'checking'} and now - last_attempt > timedelta(minutes=max(60, interval * 3)):
                status = 'stale'
        aggregate = aggregates.get(name, {})
        items.append({
            'name': name, 'category': source_categories[0] if source_categories else None,
            'categories': source_categories, 'kind': ', '.join(kinds) if kinds else 'historical',
            'configured': bool(definitions), 'enabled': enabled,
            'story_count': int(aggregate.get('story_count') or 0) if scope != 'unavailable' else None,
            'latest_collected_at': aggregate.get('latest_collected_at'),
            'latest_published_at': aggregate.get('latest_published_at'),
            'url': link, 'feed_url': link if 'rss' in kinds or 'hindi_rss' in kinds else None,
            'collection_status': status, 'last_attempt_at': check.get('last_attempt_at'),
            'last_success_at': check.get('last_success_at'),
            'last_error': str(check.get('last_error') or '')[:160] or None,
            'items_found': check.get('item_count'), 'items_added': check.get('added_count'),
        })
    return {'scope': scope, 'total_stories': sum(int(row['story_count'] or 0) for row in items) if scope != 'unavailable' else None,
            'configured_count': len(configured), 'enabled_count': sum(row['enabled'] for row in items),
            'represented_count': sum(bool(row['story_count']) for row in items),
            'categories_count': len(categories), 'items': items, 'errors': errors}
