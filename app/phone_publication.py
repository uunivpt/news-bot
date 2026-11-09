"""Durable, immediate delivery of already-published phone stories to GitHub.

The HTTP action only records a queue entry and wakes one background worker.
It never waits for Git/SSH, collects news, or grants editorial approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone

from app.monetization import review_fingerprint
from app.seo_indexing import SITE_ORIGIN, canonical_path

_worker_lock = threading.Lock()
_wake = threading.Event()
_worker = None


def _now():
    return datetime.now(timezone.utc).isoformat()


def ensure_queue(database):
    database.conn.execute("""CREATE TABLE IF NOT EXISTS ph_public_delivery (
        item_id BIGINT PRIMARY KEY, revision TEXT NOT NULL, state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
        last_error TEXT, public_url TEXT, commit_sha TEXT)""")
    if not database._postgres:
        database.conn.commit()


def delivery_status(database, item_id):
    from app.admin_backend import hosted_enabled
    if hosted_enabled():
        from app.hosted_publication import delivery
        return delivery(database, item_id)
    ensure_queue(database)
    p = '%s' if database._postgres else '?'
    record = database.conn.execute('SELECT * FROM ph_public_delivery WHERE item_id='+p,
                                   (int(item_id),)).fetchone()
    if not record:
        return {'state': 'not_queued'}
    row = dict(record)
    from app.editorial_access import table_exists
    if table_exists(database,'ph_live_receipts'):
        receipt=database.conn.execute('SELECT * FROM ph_live_receipts WHERE item_id='+p,(int(item_id),)).fetchone()
        current=database.get_by_id(int(item_id))
        if receipt and current and dict(current).get('status')=='published' and receipt['revision']==review_fingerprint(dict(current)):
            return {'state':'synced','channel':'phone_bridge','public_url':receipt['public_url'],'checked_at':receipt['checked_at'],'archive_state':row.get('state'),'revision':receipt['revision']}
    from app.live_publication import phone_enabled,public_id
    if phone_enabled():
        current=database.get_by_id(int(item_id))
        if current and dict(current).get('status')=='published':
            return {'state':'verifying','channel':'phone_bridge','configured':True,'revision':review_fingerprint(dict(current)),'public_id':public_id(item_id),'archive_state':row.get('state')}
    return {key: row.get(key) for key in
            ('state', 'attempts', 'updated_at', 'last_error', 'public_url', 'commit_sha')}


def deliver_publication(item_id, *, database):
    """Call AFTER the publication transaction; retries never republish the DB row."""
    from app.admin_backend import hosted_enabled
    if hosted_enabled():
        from app.hosted_publication import delivery
        return delivery(database, item_id)
    try:
        record = database.get_by_id(int(item_id))
        if not record:
            return {'state': 'failed', 'last_error': 'Story unavailable'}
        row = dict(record)
        if row.get('status') != 'published' or not row.get('approved_at'):
            return {'state': 'failed', 'last_error': 'Story has not been approved for publication'}
        from app.live_publication import phone_enabled,promote,public_id
        live=phone_enabled()
        if live:promote(database,row)
        ensure_queue(database)
        revision = review_fingerprint(row)
        p = '%s' if database._postgres else '?'
        prior = database.conn.execute('SELECT revision,state FROM ph_public_delivery WHERE item_id='+p,
                                      (int(item_id),)).fetchone()
        if not live and prior and prior['revision'] == revision and prior['state'] == 'synced':
            return delivery_status(database, item_id)
        public_url = SITE_ORIGIN + canonical_path(row)
        database.conn.execute(
            f"INSERT INTO ph_public_delivery(item_id,revision,state,updated_at,public_url) VALUES ({p},{p},{p},{p},{p}) "
            "ON CONFLICT(item_id) DO UPDATE SET revision=excluded.revision,state=excluded.state,"
            "updated_at=excluded.updated_at,public_url=excluded.public_url,last_error=NULL,attempts=0",
            (int(item_id), revision, 'queued', _now(), public_url))
        if not database._postgres:
            database.conn.commit()
        configured = bool(os.getenv('POLITICSHUB_LOCAL_ADMIN') == '1' and
                          os.getenv('VERCEL') != '1' and
                          (Path.home()/'.ssh/politicshub_mobile_sync').is_file())
        if configured:
            start_delivery_worker()
        result = {**delivery_status(database, item_id), 'configured': configured}
        if live:
            status=delivery_status(database,item_id)
            return {**result,**status,'configured':True,'channel':'phone_bridge','revision':revision,'public_id':public_id(item_id),'state':'synced' if status.get('channel')=='phone_bridge' and status.get('state')=='synced' else 'verifying'}
        if not configured:
            result['state'] = 'not_configured'
            result['last_error'] = 'Published in the phone database; public sync needs the existing phone SSH identity'
        return result
    except Exception as exc:
        # The database publication is already committed. Don't turn delivery
        # trouble into a misleading failed publication or expose infrastructure.
        return {'state': 'failed', 'last_error': 'Delivery queue unavailable: '+type(exc).__name__}


def public_export(row, *, public_identity=False):
    fields = ('id', 'title', 'url', 'source_name', 'source_type', 'summary', 'bot_summary',
              'bot_article', 'published_at', 'published_at_site', 'category', 'image_url',
              'image_license', 'image_credit', 'status', 'approved_at', 'fact_check_status')
    result = {key: row.get(key) for key in fields}
    result['public_source'] = bool(row.get('public_source'))
    for key in ('phone_public_id','canonical_public_id','editorial_featured','editorial_featured_at'):
        if key in row:result[key]=row[key]
    if public_identity:
        from app.live_publication import public_id
        result['phone_public_id']=public_id(row['id'])
        if str(row.get('external_id') or '').startswith('archive-restored:'):result['canonical_public_id']=row['id']
    return result


def run_pending(database, uploader=None):
    """Process one bounded queue batch. Injectable uploader is used by tests."""
    if uploader is None:
        from scripts.mobile_sync_upload import upload_immediate
        uploader = upload_immediate
    ensure_queue(database)
    pending = [dict(row) for row in database.conn.execute(
        "SELECT * FROM ph_public_delivery WHERE state IN ('queued','failed','syncing') "
        "AND attempts<8 ORDER BY updated_at LIMIT 25").fetchall()]
    p = '%s' if database._postgres else '?'
    rows, revisions = [], {}
    batch_bytes = 0
    for queued in pending:
        record = database.get_by_id(queued['item_id'])
        if not record or dict(record).get('status') != 'published':
            database.conn.execute('DELETE FROM ph_public_delivery WHERE item_id='+p,
                                  (queued['item_id'],))
            continue
        row = dict(record)
        from app.live_publication import phone_enabled,primary
        top=primary(database)
        if top and top['item_id']==row['id']:row.update(editorial_featured=True,editorial_featured_at=top['featured_at'])
        exported = public_export(row,public_identity=phone_enabled())
        size = len(json.dumps(exported, ensure_ascii=False).encode())
        if rows and (len(rows) >= 10 or batch_bytes + size > 1_000_000):
            break
        revision = review_fingerprint(row)
        updated = database.conn.execute(
            f"UPDATE ph_public_delivery SET state='syncing',revision={p},attempts=attempts+1,updated_at={p} WHERE item_id={p} AND revision={p}",
            (revision, _now(), row['id'], queued['revision'])).rowcount
        if updated == 1:
            revisions[row['id']] = revision
            rows.append(exported)
            batch_bytes += size
    if not database._postgres:
        database.conn.commit()
    if not rows:
        return {'processed': 0}
    try:
        result = uploader(rows)
        for row in rows:
            url = result.get('public_urls', {}).get(str(row['id'])) or SITE_ORIGIN+canonical_path(row)
            database.conn.execute(
                f"UPDATE ph_public_delivery SET state='synced',updated_at={p},last_error=NULL,commit_sha={p},public_url={p} "
                f"WHERE item_id={p} AND revision={p}",
                (_now(), result.get('commit_sha'), url, row['id'], revisions[row['id']]))
        status = 'synced'
    except Exception as exc:
        for row in rows:
            database.conn.execute(
                f"UPDATE ph_public_delivery SET state='failed',updated_at={p},last_error={p} WHERE item_id={p} AND revision={p}",
                (_now(), 'Public sync failed: '+type(exc).__name__, row['id'], revisions[row['id']]))
        status = 'failed'
    if not database._postgres:
        database.conn.commit()
    return {'processed': len(rows), 'state': status}


def start_delivery_worker():
    """Wake a singleton phone-only worker; restart resumes durable queued rows."""
    global _worker
    if not (Path.home()/'.ssh/politicshub_mobile_sync').is_file():return
    if os.getenv('POLITICSHUB_LOCAL_ADMIN') != '1' or os.getenv('VERCEL') == '1':
        return
    from urllib.parse import urlsplit
    dsn = os.getenv('DATABASE_3URL') or os.getenv('DATABASE_URL') or ''
    try:
        if urlsplit(dsn).hostname not in {'localhost', '127.0.0.1'}:
            return
    except ValueError:
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            def loop():
                from app.database import NewsDatabase
                while True:
                    database = None
                    try:
                        database = NewsDatabase(database_url=dsn, connect_attempts=1)
                        run_pending(database)
                    except Exception:
                        pass
                    finally:
                        if database:
                            database.close()
                    _wake.wait(30)
                    _wake.clear()
            _worker = threading.Thread(target=loop, name='phone-public-delivery', daemon=True)
            _worker.start()
        _wake.set()
