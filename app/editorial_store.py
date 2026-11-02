"""Durable event groups, claims, source evidence and published update history."""
from datetime import datetime,timezone
from .schema_cache import schema_once


def now():return datetime.now(timezone.utc).isoformat()
def ph(db):return '%s' if db._postgres else '?'

def ensure_editorial_schema(db):
    with schema_once(db,'editorial-studio-v1') as required:
        if not required:return
        serial='BIGSERIAL PRIMARY KEY' if db._postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        statements=[
            'CREATE TABLE IF NOT EXISTS ph_source_material (item_id BIGINT PRIMARY KEY,title TEXT,summary TEXT,url TEXT,publisher TEXT,captured_at TEXT)',
            'CREATE TABLE IF NOT EXISTS ph_studio_jobs (id TEXT PRIMARY KEY,item_id BIGINT NOT NULL,username TEXT NOT NULL,status TEXT NOT NULL,draft_json TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS ph_editorial_events (id TEXT PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS ph_editorial_event_items (event_id TEXT NOT NULL,item_id BIGINT NOT NULL,PRIMARY KEY(event_id,item_id))',
            f'CREATE TABLE IF NOT EXISTS ph_story_claims (id {serial},item_id BIGINT NOT NULL,statement TEXT NOT NULL,assessment TEXT NOT NULL,content_revision TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)',
            f'CREATE TABLE IF NOT EXISTS ph_claim_evidence (id {serial},claim_id BIGINT NOT NULL,source_url TEXT NOT NULL,publisher TEXT NOT NULL,excerpt TEXT NOT NULL,stance TEXT NOT NULL,recorded_by TEXT NOT NULL,created_at TEXT NOT NULL)',
            f'CREATE TABLE IF NOT EXISTS ph_editorial_updates (id {serial},item_id BIGINT NOT NULL,label TEXT NOT NULL,body TEXT NOT NULL,kind TEXT NOT NULL,source_url TEXT NOT NULL,status TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,published_by TEXT,published_at TEXT,base_revision TEXT NOT NULL)',
        ]
        for statement in statements:db.conn.execute(statement)
        db.conn.execute('CREATE INDEX IF NOT EXISTS idx_editorial_event_item ON ph_editorial_event_items(item_id)')
        db.conn.execute('CREATE INDEX IF NOT EXISTS idx_editorial_claim_story ON ph_story_claims(item_id)')
        db.conn.execute('CREATE INDEX IF NOT EXISTS idx_editorial_update_story ON ph_editorial_updates(item_id)')
        if not db._postgres:db.conn.commit()


def insert_id(db,sql,args):
    result=db.conn.execute(sql+(' RETURNING id' if db._postgres else ''),args)
    return result.fetchone()['id'] if db._postgres else result.lastrowid


def preserve_source(db,item):
    p=ph(db)
    db.conn.execute('INSERT INTO ph_source_material(item_id,title,summary,url,publisher,captured_at) VALUES ('+','.join([p]*6)+') ON CONFLICT(item_id) DO NOTHING',(item['id'],item.get('title'),item.get('summary') or '',item.get('url'),item.get('source_name'),now()))
    if not db._postgres:db.conn.commit()
