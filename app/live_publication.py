"""Signed, approved-only phone feed used directly by the public website.

The existing HTTPS admin bridge carries service reads, never a database port.
Public delivery is independent of the optional GitHub archival SSH identity.
"""
import hashlib
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from functools import lru_cache
from datetime import datetime,timezone
from urllib.request import Request,build_opener
from flask import g,has_request_context,jsonify,request,Response
from .seo_indexing import SITE_ORIGIN,canonical_path
from .source_http import public_http_url
from .monetization import review_fingerprint
from .editorial_access import table_exists

PREFIX=8_000_000_000_000_000
PUBLIC_RANGE=1_000_000_000_000_000
PUBLIC_ORIGIN=SITE_ORIGIN
_lock=threading.Lock()
_cache={'until':0.0,'payload':[],'last_good':0.0}


def public_id(private_id):
    value=int(private_id)
    if not 0<value<2**63:raise ValueError('Invalid publication ID')
    return PREFIX+int(hashlib.sha256(('phone-id:'+str(value)).encode()).hexdigest()[:12],16)


def is_public_id(value):
    try:return PREFIX<int(value)<PREFIX+PUBLIC_RANGE
    except (ValueError,TypeError):return False


def publication_key(row):
    value=row.get('phone_public_id')
    if is_public_id(value) and not row.get('canonical_public_id'):return 'phone:'+str(value)
    from .normalize import normalize_url
    return normalize_url(str(row.get('url') or ''))


def enabled():
    from .admin_backend import hosted_enabled
    if hosted_enabled():return False
    if os.getenv('VERCEL')!='1':return False
    try:
        from .remote_admin_bridge import bridge_config
        return bridge_config() is not None
    except ValueError:return False


def phone_enabled():
    from .admin_backend import hosted_enabled
    if hosted_enabled():return False
    return os.getenv('POLITICSHUB_LOCAL_ADMIN')=='1' and os.getenv('VERCEL')!='1' and len(os.getenv('POLITICSHUB_ADMIN_BRIDGE_SECRET',''))>=32


@lru_cache(maxsize=4)
def _withheld(path,modified):
    try:return set(json.loads(Path(path).read_text()))
    except (OSError,ValueError,TypeError):return set()

def source_withheld(url):
    file=Path(__file__).parent/'data/archive-withheld.json'
    if not file.exists():return False
    return hashlib.sha256(str(url or '').encode()).hexdigest() in _withheld(str(file),file.stat().st_mtime_ns)


def export_row(row,*,body=True,featured=None):
    if source_withheld(row.get('url')):return None
    if row.get('status')!='published' or not row.get('approved_at') or not row.get('public_source') or str(row.get('fact_check_status') or '').lower() not in {'reviewed','approved','verified','passed'} or not public_http_url(row.get('url')) or not str(row.get('url') or '').startswith('https://'):return None
    if not str(row.get('title') or '').strip() or not str(row.get('bot_summary') or row.get('summary') or '').strip():return None
    fields=('title','url','source_name','source_type','category','published_at','published_at_site','summary','bot_summary','image_url','image_license','image_credit')
    result={key:row.get(key) for key in fields}
    canonical=int(row['id']) if str(row.get('external_id') or '').startswith('archive-restored:') else public_id(row['id'])
    if canonical!=public_id(row['id']):result['canonical_public_id']=canonical
    result.update(id=canonical,phone_public_id=public_id(row['id']),status='published',public_source=True,public_revision=review_fingerprint(row))
    result['summary']=str(row.get('bot_summary') or row.get('summary') or '')[:6000]
    result.pop('bot_summary',None)
    if body:result['bot_article']=str(row.get('bot_article') or row.get('summary') or '')[:50000]
    if result.get('image_url') and (result.get('image_license') not in {'cc0','pdm','licensed','rights-owned'} or not result.get('image_credit')):result['image_url']=None
    if featured and int(featured['item_id'])==int(row['id']):result.update(editorial_featured=True,editorial_featured_at=featured['featured_at'])
    return result


def promote(db,row):
    from .schema_cache import schema_once
    p='%s' if db._postgres else '?'
    with schema_once(db,'home-primary-v1') as required:
        if required:
            db.conn.execute('CREATE TABLE IF NOT EXISTS ph_public_ids (item_id BIGINT PRIMARY KEY,public_id BIGINT NOT NULL UNIQUE)')
            db.conn.execute('CREATE TABLE IF NOT EXISTS ph_home_primary (slot INTEGER PRIMARY KEY,item_id BIGINT NOT NULL,revision TEXT NOT NULL,featured_at TEXT NOT NULL)')
            if not db._postgres:db.conn.commit()
    db.conn.execute('INSERT INTO ph_public_ids(item_id,public_id) VALUES ('+p+','+p+') ON CONFLICT(item_id) DO NOTHING',(row['id'],public_id(row['id'])))
    if not db._postgres:db.conn.commit()
    revision=review_fingerprint(row)
    current=db.conn.execute('SELECT * FROM ph_home_primary WHERE slot=1').fetchone()
    if current and current['item_id']==row['id'] and current['revision']==revision:return dict(current)
    stamp=datetime.now(timezone.utc).isoformat()
    db.conn.execute('INSERT INTO ph_home_primary(slot,item_id,revision,featured_at) VALUES (1,'+','.join([p]*3)+') ON CONFLICT(slot) DO UPDATE SET item_id=excluded.item_id,revision=excluded.revision,featured_at=excluded.featured_at',(row['id'],revision,stamp))
    if not db._postgres:db.conn.commit()
    return {'item_id':row['id'],'revision':revision,'featured_at':stamp}


def primary(db):
    if not table_exists(db,'ph_home_primary'):return None
    row=db.conn.execute("SELECT h.* FROM ph_home_primary h JOIN news_items n ON n.id=h.item_id WHERE h.slot=1 AND n.status='published' AND n.approved_at IS NOT NULL AND n.public_source=1").fetchone()
    return dict(row) if row else None


def proof(secret,nonce,body):return hmac.new(secret.encode(),(nonce+'\n').encode()+body,hashlib.sha256).hexdigest()


def register_phone_public(app,factory):
    def authorize():
        if not phone_enabled():return False
        if getattr(g,'phone_bridge_verified',False):return True
        from .remote_admin_bridge import verify_phone_bridge
        return verify_phone_bridge(request,os.environ['POLITICSHUB_ADMIN_BRIDGE_SECRET'])
    def respond(payload,status=200):
        content=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        return Response(content,status=status,mimetype='application/json',headers={'Cache-Control':'private, no-store','X-PH-Public-Signature':proof(os.environ['POLITICSHUB_ADMIN_BRIDGE_SECRET'],request.headers.get('X-PH-Bridge-Nonce',''),content)})
    @app.get('/api/phone-public/feed')
    @app.get('/api/phone-public/version')
    @app.get('/api/phone-public/article/<int:item_id>')
    def phone_public(item_id=None):
        if not authorize():return jsonify({'error':'Signed publication gateway required'}),403
        db=factory()
        try:
            featured=primary(db)
            version=(str(public_id(featured['item_id']))+':'+featured['revision']+':'+featured['featured_at']) if featured else 'none'
            if request.path.endswith('/version'):return respond({'version':1,'publication_version':version})
            if item_id is not None:
                private_id=None
                if is_public_id(item_id):
                    if table_exists(db,'ph_public_ids'):
                        p='%s' if db._postgres else '?'
                        match=db.conn.execute('SELECT item_id FROM ph_public_ids WHERE public_id='+p,(item_id,)).fetchone()
                        if match:private_id=match['item_id']
                    if private_id is None:
                        matches=[r['id'] for r in db.conn.execute("SELECT id FROM news_items WHERE status='published' AND approved_at IS NOT NULL AND public_source=1").fetchall() if public_id(r['id'])==item_id]
                        if len(matches)==1:private_id=matches[0]
                row=db.get_by_id(private_id) if private_id is not None else None
                exported=export_row(dict(row),featured=featured) if row else None
                return respond({'version':1,'story':exported},200 if exported else 404)
            # Never export private manuscripts, users, evidence or moderation notes.
            columns='id,title,url,source_name,source_type,category,published_at,published_at_site,summary,bot_summary,image_url,image_license,image_credit,status,approved_at,public_source,fact_check_status,bot_article,external_id'
            rows=[dict(r) for r in db.conn.execute('SELECT '+columns+" FROM news_items WHERE status='published' AND approved_at IS NOT NULL AND public_source=1 ORDER BY approved_at DESC,id DESC LIMIT 100").fetchall()]
            if featured and not any(r['id']==featured['item_id'] for r in rows):
                row=db.get_by_id(featured['item_id'])
                if row:rows.insert(0,dict(row))
            exported=[safe for row in rows if (safe:=export_row(row,body=False,featured=featured))]
            if len({r['id'] for r in exported})!=len(exported):return respond({'error':'Public identity conflict'},503)
            return respond({'version':1,'publication_version':version,'stories':exported})
        finally:db.close()
    @app.post('/api/phone-public/receipt')
    def phone_public_receipt():
        if not authorize():return jsonify({'error':'Signed publication gateway required'}),403
        body=request.get_json(silent=True) or {};db=factory()
        try:
            try:item_id=int(body.get('item_id'));row=db.get_by_id(item_id)
            except (ValueError,TypeError):return respond({'error':'Invalid receipt'},400)
            exported=export_row(dict(row)) if row else None
            if not exported or exported['public_revision']!=body.get('revision'):return respond({'error':'Publication changed'},409)
            store_receipt(db,item_id,exported)
            return respond({'ok':True})
        finally:db.close()


def store_receipt(db,item_id,exported):
    p='%s' if db._postgres else '?'
    db.conn.execute('CREATE TABLE IF NOT EXISTS ph_live_receipts (item_id BIGINT PRIMARY KEY,revision TEXT NOT NULL,public_url TEXT NOT NULL,checked_at TEXT NOT NULL)')
    url=SITE_ORIGIN+canonical_path(exported)
    db.conn.execute('INSERT INTO ph_live_receipts(item_id,revision,public_url,checked_at) VALUES ('+','.join([p]*4)+') ON CONFLICT(item_id) DO UPDATE SET revision=excluded.revision,public_url=excluded.public_url,checked_at=excluded.checked_at',(item_id,exported['public_revision'],url,datetime.now(timezone.utc).isoformat()))
    if not db._postgres:db.conn.commit()


def signed_read(path,body=None):
    from .remote_admin_bridge import bridge_config,bridge_headers,_NoRedirect
    config=bridge_config()
    if not config:raise RuntimeError('Publication bridge unavailable')
    origin,secret=config;payload=json.dumps(body,separators=(',',':')).encode() if body is not None else b''
    headers=bridge_headers(secret,'POST' if body is not None else 'GET',path,payload);headers['Accept']='application/json';headers['Cache-Control']='no-store'
    if body is not None:headers['Content-Type']='application/json'
    from urllib.error import HTTPError
    try:response=build_opener(_NoRedirect).open(Request(origin+path,data=payload if body is not None else None,headers=headers,method='POST' if body is not None else 'GET'),timeout=5)
    except HTTPError as error:response=error
    with response:
        content=response.read(2_800_001)
        if len(content)>2_800_000 or not hmac.compare_digest(response.headers.get('X-PH-Public-Signature',''),proof(secret,headers['X-PH-Bridge-Nonce'],content)):raise ValueError('Invalid publication proof')
        data=json.loads(content)
        if not isinstance(data,dict):raise ValueError('Invalid publication response')
        return data,response.status


def read_feed():
    if not enabled():return []
    if has_request_context() and hasattr(g,'phone_public_feed'):return g.phone_public_feed
    try:
        data,status=signed_read('/api/phone-public/feed')
        if status!=200 or data.get('version')!=1 or not isinstance(data.get('stories'),list):raise ValueError('Invalid feed')
        rows=[r for r in data['stories'] if isinstance(r,dict) and is_public_id(r.get('phone_public_id') or r.get('id')) and r.get('status')=='published' and r.get('public_source') and r.get('title') and re.fullmatch(r'[0-9a-f]{64}',str(r.get('public_revision') or ''))]
        with _lock:_cache.update(payload=rows,last_good=time.monotonic())
    except Exception:
        with _lock:rows=_cache['payload'] if time.monotonic()-_cache['last_good']<3600 else []
    if has_request_context():g.phone_public_feed=rows
    return rows


def lookup(item_id):
    if not enabled():return False,None
    if not is_public_id(item_id):
        match=next((r for r in read_feed() if str(r.get('id'))==str(item_id) and is_public_id(r.get('phone_public_id'))),None)
        if not match:return False,None
        item_id=match['phone_public_id']
    try:
        data,status=signed_read('/api/phone-public/article/'+str(int(item_id)))
        if status==404 and data.get('version')==1:return True,None
        row=data.get('story')
        if status==200 and isinstance(row,dict) and str(row.get('phone_public_id') or row.get('id'))==str(item_id) and row.get('status')=='published' and row.get('public_source'):return True,row
    except Exception:pass
    return False,None


def confirm_publication(payload,database=None):
    """A real anonymous public API read must see this exact revision first."""
    delivery=payload.get('public_delivery') or {}
    if delivery.get('channel')!='phone_bridge' or not payload.get('id'):return payload
    item_id=int(payload['id']);expected=delivery.get('revision');pid=public_id(item_id)
    try:
        url=PUBLIC_ORIGIN+'/api/news/'+str(pid)+'?publication_check='+str(time.time_ns())
        with build_opener().open(Request(url,headers={'Accept':'application/json','Cache-Control':'no-cache','User-Agent':'Mozilla/5.0 PoliticsHubPublicationCheck/1'}),timeout=7) as response:
            raw=response.read(900_001)
            if response.status!=200 or len(raw)>900_000:raise ValueError('Public article unavailable')
            row=json.loads(raw)
        if str(row.get('phone_public_id') or row.get('id'))!=str(pid) or row.get('public_revision')!=expected:raise ValueError('Public article revision unavailable')
        if database is not None:store_receipt(database,item_id,row)
        else:
            receipt,status=signed_read('/api/phone-public/receipt',{'item_id':item_id,'revision':expected})
            if status!=200 or not receipt.get('ok'):raise ValueError('Receipt not saved')
        delivery.update(state='synced',public_url=SITE_ORIGIN+canonical_path(row),checked_at=datetime.now(timezone.utc).isoformat())
    except Exception:
        delivery.update(state='verifying',last_error='Website visibility has not been confirmed yet. Retry the website check; the saved article will not be duplicated.')
    return dict(payload,public_delivery=delivery)
