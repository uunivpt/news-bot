"""Immediate, reviewed-only website delivery from the hosted newsroom.

The rotating GitHub feed remains the source of current collected headlines.
Editor-approved cloud records overlay that feed. An editor-touched unpublished
record can suppress its former public copy. Untouched collector/import records
cannot remove existing public stories merely because they lack modern review
metadata. This module neither contacts a phone nor writes Git.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.admin_workspace import editorial_revision
from app.live_publication import source_withheld
from app.seo_indexing import SITE_ORIGIN, canonical_path
from app.source_http import public_http_url


APPROVED_STATES = frozenset({'reviewed', 'approved', 'verified', 'passed'})
MAX_RECENT_APPROVED = 1000
# Listing overlays never read manuscripts, AI material or private review notes.
LIST_FIELDS = (
    'id', 'title', 'summary', 'bot_summary', 'source_name', 'source_type', 'url',
    'published_at', 'published_at_site', 'category', 'status', 'image_url',
    'image_source', 'image_license', 'public_source', 'view_count', 'approved_at',
    'fact_check_status',
)

EDITORIAL_ACTIONS = (
    'news.edit', 'news.update', 'news.verify_publish', 'archive.restore',
    'news.manual.create', 'editorial.studio.save', 'editorial.update.publish',
)


def _touch_predicate(alias='n'):
    # Keep the activity boundary explicit: routine collection, processing or
    # monitoring logs do not establish an editor's decision about public copy.
    actions = ','.join("'" + action + "'" for action in EDITORIAL_ACTIONS)
    return ("((" + alias + ".approved_at IS NOT NULL AND " + alias + ".approved_at <> '') "
            "OR " + alias + ".source_type='manual' "
            "OR " + alias + ".id IN (SELECT a.item_id FROM admin_activity a "
            "WHERE a.item_id IS NOT NULL AND a.action IN (" + actions + ")))")


def is_editorial_override(database, row):
    """Whether this cloud identity may override an older public saved copy."""
    if row is None:
        return False
    row = dict(row)
    if row.get('approved_at') or row.get('source_type') == 'manual':
        return True
    try:
        item_id = int(row.get('id'))
    except (TypeError, ValueError):
        return False
    p = '%s' if database._postgres else '?'
    actions = ','.join([p] * len(EDITORIAL_ACTIONS))
    return bool(database.conn.execute(
        'SELECT 1 FROM admin_activity WHERE item_id=' + p +
        ' AND action IN (' + actions + ') LIMIT 1',
        (item_id, *EDITORIAL_ACTIONS)
    ).fetchone())


def is_publication(row):
    """The persisted editorial decision is required in addition to status."""
    return bool(
        row.get('status') == 'published'
        and row.get('approved_at')
        and str(row.get('fact_check_status') or '').lower() in APPROVED_STATES
        and row.get('public_source') in (True, 1, '1')
        and str(row.get('title') or '').strip()
        and str(row.get('url') or '').startswith('https://')
        and public_http_url(row.get('url'))
        and not source_withheld(row.get('url'))
    )


def _candidate_overrides(database, snapshots):
    """Read indexed identities in bounded groups, including rejected rows."""
    p = '%s' if database._postgres else '?'
    fields = ','.join(LIST_FIELDS)
    if len(snapshots) > 500:
        # Full-archive and sitemap reads can contain 100,000 saved reports.
        # Enumerate only the cloud's actual editorial overrides once instead
        # of issuing hundreds of candidate queries over the public archive.
        # No cap: older withdrawals must remain effective after newer edits.
        ids = {str(row.get('id')) for row in snapshots}
        urls = {str(row['url']) for row in snapshots
                if row.get('url') and row.get('source_type') != 'manual'}
        identities = database.conn.execute(
            'SELECT n.id,n.url,n.source_type FROM news_items n WHERE ' +
            _touch_predicate()
        ).fetchall()
        matched = [int(row['id']) for row in identities
                   if str(row['id']) in ids or
                   (row['source_type'] != 'manual' and row['url'] in urls)]
        found = []
        for start in range(0, len(matched), 200):
            batch = matched[start:start + 200]
            found.extend(dict(row) for row in database.conn.execute(
                'SELECT ' + fields + ' FROM news_items WHERE id IN (' +
                ','.join([p] * len(batch)) + ')', tuple(batch)
            ).fetchall())
        return found
    found = {}
    for start in range(0, len(snapshots), 200):
        batch = snapshots[start:start + 200]
        ids = [int(row['id']) for row in batch if str(row.get('id') or '').isdigit()]
        # A separately written manual article may cite the same evidence URL.
        urls = list({str(row.get('url')) for row in batch
                     if row.get('url') and row.get('source_type') != 'manual'})
        clauses, params = [], []
        if ids:
            clauses.append('n.id IN (' + ','.join([p] * len(ids)) + ')')
            params.extend(ids)
        if urls:
            clauses.append("(n.source_type <> 'manual' AND n.url IN (" + ','.join([p] * len(urls)) + '))')
            params.extend(urls)
        if not clauses:
            continue
        rows = database.conn.execute('SELECT ' + fields + ' FROM news_items n WHERE (' +
                                     ' OR '.join(clauses) + ') AND ' + _touch_predicate(),
                                     tuple(params)).fetchall()
        for record in rows:
            row = dict(record)
            found[str(row['id'])] = row
    return list(found.values())


def overlay(database, snapshot_rows, limit=None):
    """Merge the public snapshot with bounded, editor-approved cloud reports.

    Matching editor-touched cloud identities are authoritative, including
    records now pending/rejected. Untouched legacy imports remain independent
    of the public snapshot. Only approved records can supply cloud content.
    The caller ranks candidates and applies its public response projection.
    """
    snapshots = [dict(row) for row in snapshot_rows]
    p = '%s' if database._postgres else '?'
    fields = ','.join(LIST_FIELDS)
    approved = [dict(row) for row in database.conn.execute(
        'SELECT ' + fields + " FROM news_items WHERE status='published' "
        "AND approved_at IS NOT NULL AND approved_at <> '' "
        "AND LOWER(fact_check_status) IN ('reviewed','approved','verified','passed') "
        'ORDER BY approved_at DESC,id DESC LIMIT ' + p, (MAX_RECENT_APPROVED,)
    ).fetchall()]
    overrides = _candidate_overrides(database, snapshots)
    by_id = {str(row['id']): row for row in overrides}
    by_url = {}
    # Prefer a deterministic newest identity when an older source URL recurs.
    for row in sorted(overrides, key=lambda item: int(item['id'])):
        if row.get('source_type') != 'manual' and row.get('url'):
            by_url[str(row['url'])] = row
    result, seen_ids = [], set()
    for snapshot in snapshots:
        key = str(snapshot.get('id'))
        cloud = by_id.get(key)
        if cloud is None and snapshot.get('source_type') != 'manual':
            cloud = by_url.get(str(snapshot.get('url') or ''))
        row = cloud if cloud is not None else snapshot
        if cloud is not None:
            if not is_publication(cloud):
                continue
        elif snapshot.get('status', 'published') != 'published':
            continue
        row_key = str(row.get('id'))
        if row_key not in seen_ids:
            result.append(dict(row))
            seen_ids.add(row_key)
    for row in approved:
        key = str(row['id'])
        if key not in seen_ids and is_publication(row):
            result.append(row)
            seen_ids.add(key)
    return result if limit is None else result[:max(0, int(limit))]


def delivery(database, item_id):
    """Report durable publication through the hosted database, without a queue."""
    record = database.get_by_id(int(item_id))
    row = dict(record) if record else None
    if row is None or not is_publication(row):
        return {'state': 'failed', 'mode': 'hosted', 'configured': True,
                'code': 'publication_unavailable',
                'last_error': 'This story has not been approved for public delivery.'}
    return {'state': 'synced', 'mode': 'hosted', 'channel': 'hosted_database',
            'configured': True, 'public_url': SITE_ORIGIN + canonical_path(row),
            'revision': editorial_revision(row),
            'checked_at': datetime.now(timezone.utc).isoformat()}


def version(database):
    """Return a small opaque change marker; no stories or private events leave DB."""
    publication = dict(database.conn.execute(
        "SELECT COUNT(*) AS approved_count,MAX(approved_at) AS latest_approval,"
        "COALESCE(SUM(CASE WHEN status='published' THEN 1 ELSE 0 END),0) AS published_count "
        "FROM news_items WHERE approved_at IS NOT NULL AND approved_at <> ''"
    ).fetchone())
    activity = dict(database.conn.execute(
        'SELECT MAX(id) AS last_event,MAX(created_at) AS last_change FROM admin_activity'
    ).fetchone())
    return hashlib.sha256(json.dumps([publication, activity], sort_keys=True,
                                     default=str).encode()).hexdigest()
