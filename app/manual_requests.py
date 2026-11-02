"""Idempotent CMS creation, including retries after a lost publish response."""
import hashlib
import json
import re


def reserve(db,username,body):
    key=body.get('request_id')
    if not key:return None,None
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',key):raise ValueError('Invalid creation request ID')
    db.conn.execute('CREATE TABLE IF NOT EXISTS ph_manual_requests (username TEXT NOT NULL,request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,item_id BIGINT,PRIMARY KEY(username,request_id))')
    digest=hashlib.sha256(json.dumps({k:v for k,v in body.items() if k!='request_id'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    p='%s' if db._postgres else '?'
    db.conn.execute('INSERT INTO ph_manual_requests(username,request_id,payload_hash) VALUES ('+','.join([p]*3)+') ON CONFLICT(username,request_id) DO NOTHING',(username,key,digest))
    row=db.conn.execute('SELECT payload_hash,item_id FROM ph_manual_requests WHERE username='+p+' AND request_id='+p+(' FOR UPDATE' if db._postgres else ''),(username,key)).fetchone()
    if row['payload_hash']!=digest:raise ValueError('This creation request already belongs to different article content. Start a new draft.')
    return key,row['item_id']


def complete(db,username,key,item_id):
    if key:
        p='%s' if db._postgres else '?'
        db.conn.execute('UPDATE ph_manual_requests SET item_id='+p+' WHERE username='+p+' AND request_id='+p,(item_id,username,key))
