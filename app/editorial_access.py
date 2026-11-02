"""Owner-controlled per-account powers, desks and story ownership."""
import json
from datetime import datetime, timezone
from .admin_roles import PRIMARY_OWNER, ALL
from .schema_cache import schema_once

DESKS = {'general','india','world','politics','business','technology','sports','entertainment','science','health','hindi','maharashtra'}


def ensure_access_schema(db):
    with schema_once(db,'editorial-access-v1') as required:
        if not required:return
        db.conn.execute('CREATE TABLE IF NOT EXISTS ph_staff_policy (username TEXT PRIMARY KEY, permissions TEXT NOT NULL, categories TEXT NOT NULL, own_only INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)')
        db.conn.execute('CREATE TABLE IF NOT EXISTS ph_story_owners (item_id BIGINT PRIMARY KEY,username TEXT NOT NULL)')
        if not db._postgres:db.conn.commit()


def table_exists(db,name):
    if db._postgres:return bool(db.conn.execute('SELECT to_regclass(%s) AS name',(name,)).fetchone()['name'])
    return bool(db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def policy_for(db,username):
    if username==PRIMARY_OWNER or not table_exists(db,'ph_staff_policy'):return None
    p='%s' if db._postgres else '?'
    row=db.conn.execute('SELECT * FROM ph_staff_policy WHERE username='+p,(username,)).fetchone()
    if not row:return None
    try:
        powers=json.loads(row['permissions']);categories=json.loads(row['categories'])
        if not isinstance(powers,list) or not isinstance(categories,list):raise ValueError()
        return {'permissions':sorted(set(powers)&(ALL-{'users.manage'})), 'categories':sorted(set(categories)&DESKS), 'own_only':bool(row['own_only'])}
    except (ValueError,TypeError):
        # A malformed restriction cannot expand a staff account's access.
        return {'permissions':[],'categories':[],'own_only':True}


def validate_policy(body):
    powers=body.get('permissions');categories=body.get('categories',[]);own=body.get('own_only',False)
    if not isinstance(powers,list) or not all(isinstance(x,str) for x in powers) or set(powers)-(ALL-{'users.manage'}):raise ValueError('Select valid staff permissions. Staff cannot receive account-management power.')
    if not isinstance(categories,list) or not all(isinstance(x,str) for x in categories) or set(categories)-DESKS:raise ValueError('Select valid desks.')
    if not isinstance(own,bool):raise ValueError('Own stories must be a boolean.')
    if 'news.read' not in powers:raise ValueError('An enabled staff account needs newsroom reading access. Use Disable access to revoke all access.')
    # Global diagnostics and settings concern all desks; keep these powers with
    # unrestricted operational staff rather than leaking data around a scope.
    if (categories or own) and set(powers)&{'operations.read','reports.read','activity.read','settings.manage','training.manage'}:raise ValueError('Global operations/report/settings powers require access to all desks and stories.')
    return sorted(set(powers)),sorted(set(categories)),own


def save_policy(db,username,body,*,commit=True):
    if username==PRIMARY_OWNER:raise ValueError('The primary owner cannot be restricted.')
    powers,categories,own=validate_policy(body);ensure_access_schema(db)
    p='%s' if db._postgres else '?'
    db.conn.execute('INSERT INTO ph_staff_policy(username,permissions,categories,own_only,updated_at) VALUES ('+','.join([p]*5)+') ON CONFLICT(username) DO UPDATE SET permissions=excluded.permissions,categories=excluded.categories,own_only=excluded.own_only,updated_at=excluded.updated_at',(username,json.dumps(powers),json.dumps(categories),int(own),datetime.now(timezone.utc).isoformat()))
    if commit and not db._postgres:db.conn.commit()


def scope_sql(db,policy,username,alias=''):
    if not policy:return '',[]
    p='%s' if db._postgres else '?';prefix=alias+'.' if alias else '';clauses=[];params=[]
    if policy['categories']:
        clauses.append(prefix+'category IN ('+','.join([p]*len(policy['categories']))+')');params.extend(policy['categories'])
    if policy['own_only']:
        if not table_exists(db,'ph_story_owners'):clauses.append('1=0')
        else:
            clauses.append(prefix+'id IN (SELECT item_id FROM ph_story_owners WHERE username='+p+')');params.append(username)
    return ' AND '.join(clauses),params


def allowed_story(db,item_id,policy,username):
    if not policy:return True
    restriction,args=scope_sql(db,policy,username)
    p='%s' if db._postgres else '?'
    return bool(db.conn.execute('SELECT id FROM news_items WHERE id='+p+(' AND '+restriction if restriction else ''),(item_id,*args)).fetchone())


def assign_story(db,item_id,username,*,commit=True):
    ensure_access_schema(db);p='%s' if db._postgres else '?'
    db.conn.execute('INSERT INTO ph_story_owners(item_id,username) VALUES ('+p+','+p+') ON CONFLICT(item_id) DO UPDATE SET username=excluded.username',(item_id,username))
    if commit and not db._postgres:db.conn.commit()
