"""Deterministic operations engine for PoliticsHub upgrades 1-16.

No LLM/API dependency. All decisions are rule/score/hash based and persisted.
"""
from __future__ import annotations
import hashlib, json, re
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATES=("COLLECTED","RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED","INSTAGRAM_QUEUE","REEL_CREATED","INSTAGRAM_PUBLISHED")
BREAKING_TERMS=("breaking","just in","urgent","alert","earthquake","attack","resigns","resignation","dead","dies","war","explosion","emergency","major","supreme court","prime minister","president","election result")
IMPORTANCE_TERMS=("election","government","parliament","supreme court","prime minister","president","war","conflict","economy","market","budget","policy","earthquake","cyclone","flood","security")
CATEGORY_WEIGHT={"politics":24,"india":20,"world":22,"business":17,"technology":14,"science":12,"sports":10,"health":15,"entertainment":8,"general":8}
LAYOUT_FAMILIES={"politics":("editorial","split","quote","minimal","dark"),"india":("editorial","photo","minimal","magazine"),"world":("dark","photo","magazine","split"),"business":("data","magazine","editorial","minimal"),"technology":("data","split","minimal","dark"),"science":("data","photo","magazine","editorial"),"sports":("photo","split","minimal","editorial"),"entertainment":("photo","magazine","quote","minimal"),"health":("editorial","data","quote","photo"),"general":("editorial","minimal","magazine","photo")}
PALETTES=("light","mono","red","dark","blue","amber","teal","violet")

def now(): return datetime.now(timezone.utc).isoformat()
def ph(db): return "%s" if getattr(db,"_postgres",False) else "?"
def q1(db,sql,args=()):
    r=db.conn.execute(sql,args).fetchone()
    return r
def val(row,key,default=None):
    if row is None:return default
    try:return row[key]
    except Exception:return default

def ensure_schema(db):
    stmts=[
      f"""CREATE TABLE IF NOT EXISTS ph_news_scores(item_id BIGINT PRIMARY KEY, score REAL NOT NULL, freshness REAL, coverage REAL, importance REAL, duplicate_risk REAL, verification REAL, breaking INTEGER DEFAULT 0, reason TEXT, updated_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_source_reliability(source_name TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0, successes INTEGER DEFAULT 0, broken_links INTEGER DEFAULT 0, corrections INTEGER DEFAULT 0, coverage_events INTEGER DEFAULT 0, last_seen_at TEXT, updated_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_events(event_id TEXT PRIMARY KEY, canonical_title TEXT NOT NULL, category TEXT, priority REAL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT DEFAULT 'active')""",
      """CREATE TABLE IF NOT EXISTS ph_event_items(event_id TEXT NOT NULL, item_id BIGINT PRIMARY KEY, relation TEXT NOT NULL, first_seen_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_bot_failures(id BIGSERIAL PRIMARY KEY, bot TEXT NOT NULL, item_id BIGINT, step TEXT NOT NULL, error TEXT, attempt INTEGER DEFAULT 1, action TEXT, resolved INTEGER DEFAULT 0, created_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_alerts(id BIGSERIAL PRIMARY KEY, severity TEXT NOT NULL, bot TEXT, step TEXT, item_id BIGINT, message TEXT NOT NULL, resolved INTEGER DEFAULT 0, created_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_publish_locks(item_id BIGINT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE, website_published INTEGER DEFAULT 0, instagram_published INTEGER DEFAULT 0, reel_url TEXT, locked_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_resource_snapshots(id BIGSERIAL PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_reel_previews(item_id BIGINT PRIMARY KEY, video_path TEXT, preview_path TEXT, qa TEXT, layout_id TEXT, created_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_regression_runs(id BIGSERIAL PRIMARY KEY, commit_ref TEXT, status TEXT NOT NULL, results TEXT, created_at TEXT NOT NULL)""",
      """CREATE TABLE IF NOT EXISTS ph_event_updates(id BIGSERIAL PRIMARY KEY, event_id TEXT NOT NULL, item_id BIGINT, label TEXT NOT NULL, created_at TEXT NOT NULL)""",
    ]
    for s in stmts:
        if not getattr(db,"_postgres",False):
            s=s.replace("BIGSERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT")
        db.conn.execute(s)
    if not getattr(db,"_postgres",False): db.conn.commit()

def _words(text):
    return set(re.findall(r"[a-z0-9]{3,}",str(text or "").lower()))

def similarity(a,b):
    x,y=_words(a),_words(b)
    return len(x&y)/max(1,len(x|y)) if x and y else 0.0

def _age_hours(row):
    # NewsDatabase stores collection time as collected_at; some RSS feeds use RFC-822 dates.
    for k in ("published_at","published_at_site","collected_at"):
        raw=val(row,k)
        if not raw:
            continue
        text=str(raw).strip()
        try:
            d=datetime.fromisoformat(text.replace("Z","+00:00"))
        except Exception:
            try:
                d=parsedate_to_datetime(text)
            except Exception:
                continue
        try:
            d=d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            return max(0,(datetime.now(timezone.utc)-d.astimezone(timezone.utc)).total_seconds()/3600)
        except Exception:
            continue
    return 72.0

def score_story(db,row,source_count=0,verification="UNVERIFIED",duplicate_risk=0.0):
    ensure_schema(db)
    age=_age_hours(row)
    freshness=max(0.0,100.0-(age*4.0))
    coverage=min(100.0,int(source_count or 0)*28)
    category=str(val(row,"category","general") or "general").lower()
    text=f"{val(row,'title','')} {val(row,'summary','')}".lower()
    importance=min(100.0,CATEGORY_WEIGHT.get(category,8)+sum(10 for k in IMPORTANCE_TERMS if k in text))
    if verification=="CONFIRMED": verify=100.0
    elif verification=="CONFLICTING": verify=25.0
    elif verification=="SINGLE SOURCE": verify=55.0
    else: verify=15.0
    duplicate_risk=max(0,min(100,float(duplicate_risk)))
    score=round(.25*freshness+.20*coverage+.20*importance+.20*verify+.15*(100-duplicate_risk),2)
    breaking=int(score>=78 and (any(k in text for k in BREAKING_TERMS) or freshness>=92 and importance>=30))
    reason=json.dumps({"freshness":round(freshness,2),"coverage":round(coverage,2),"importance":round(importance,2),"verification":verify,"duplicate_risk":duplicate_risk},ensure_ascii=False)
    p=ph(db)
    db.conn.execute(f"""INSERT INTO ph_news_scores(item_id,score,freshness,coverage,importance,duplicate_risk,verification,breaking,reason,updated_at)
      VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
      ON CONFLICT(item_id) DO UPDATE SET score=EXCLUDED.score,freshness=EXCLUDED.freshness,coverage=EXCLUDED.coverage,importance=EXCLUDED.importance,duplicate_risk=EXCLUDED.duplicate_risk,verification=EXCLUDED.verification,breaking=EXCLUDED.breaking,reason=EXCLUDED.reason,updated_at=EXCLUDED.updated_at""",
      (int(val(row,"id")),score,freshness,coverage,importance,duplicate_risk,verify,breaking,reason,now()))
    if not getattr(db,"_postgres",False): db.conn.commit()
    return {"score":score,"breaking":bool(breaking),"freshness":freshness,"coverage":coverage,"importance":importance,"duplicate_risk":duplicate_risk,"verification":verify}

def select_layout(category,title,item_id,breaking=False,has_image=True):
    cat=str(category or "general").lower()
    families=LAYOUT_FAMILIES.get(cat,LAYOUT_FAMILIES["general"])
    if breaking: families=("dark","editorial","split","minimal")+families
    seed=int(hashlib.sha256(f"{item_id}|{title}|{cat}|{int(breaking)}".encode()).hexdigest(),16)
    family=families[seed%len(families)]
    palette=PALETTES[(seed//len(families))%len(PALETTES)]
    base=seed%8
    variant=(base*len(PALETTES)+PALETTES.index(palette))%64
    if not has_image: variant=(variant+17)%64
    return {"id":f"{family}_{palette}_{variant:02d}","family":family,"palette":palette,"variant":variant,"breaking":bool(breaking)}

def record_source(db,source_name,success=True,broken=False,correction=False,coverage=True):
    if not source_name:return
    ensure_schema(db); p=ph(db); n=now()
    db.conn.execute(f"""INSERT INTO ph_source_reliability(source_name,attempts,successes,broken_links,corrections,coverage_events,last_seen_at,updated_at)
      VALUES ({p},1,{p},{p},{p},{p},{p},{p})
      ON CONFLICT(source_name) DO UPDATE SET attempts=ph_source_reliability.attempts+1,
      successes=ph_source_reliability.successes+EXCLUDED.successes,broken_links=ph_source_reliability.broken_links+EXCLUDED.broken_links,
      corrections=ph_source_reliability.corrections+EXCLUDED.corrections,coverage_events=ph_source_reliability.coverage_events+EXCLUDED.coverage_events,
      last_seen_at=EXCLUDED.last_seen_at,updated_at=EXCLUDED.updated_at""",
      (str(source_name),int(bool(success)),int(bool(broken)),int(bool(correction)),int(bool(coverage)),n,n))
    if not getattr(db,"_postgres",False):db.conn.commit()

def source_reliability(db,source_name=None):
    ensure_schema(db)
    sql="SELECT * FROM ph_source_reliability"
    args=()
    if source_name: sql+=f" WHERE source_name={ph(db)}"; args=(source_name,)
    rows=db.conn.execute(sql,args).fetchall()
    out=[]
    for r in rows:
        a=max(1,int(val(r,"attempts",0) or 0)); s=int(val(r,"successes",0) or 0)
        out.append({"source":val(r,"source_name"),"success_rate":round(100*s/a,2),"broken_links":int(val(r,"broken_links",0) or 0),"correction_frequency":round(100*int(val(r,"corrections",0) or 0)/a,2),"coverage_consistency":round(100*int(val(r,"coverage_events",0) or 0)/a,2)})
    return out[0] if source_name and out else (out if not source_name else None)

def event_key(title,category="general"):
    words=sorted(_words(title))[:18]
    return hashlib.sha1((str(category).lower()+"|"+" ".join(words)).encode()).hexdigest()[:20]

def attach_event(db,item_id,title,category="general",source_name=""):
    ensure_schema(db); key=event_key(title,category); p=ph(db); n=now()
    row=q1(db,f"SELECT event_id FROM ph_events WHERE event_id={p}",(key,))
    if not row:
        db.conn.execute(f"INSERT INTO ph_events(event_id,canonical_title,category,created_at,updated_at) VALUES ({p},{p},{p},{p},{p})",(key,title,category,n,n))
    else:
        db.conn.execute(f"UPDATE ph_events SET updated_at={p} WHERE event_id={p}",(n,key))
    db.conn.execute(f"INSERT INTO ph_event_items(event_id,item_id,relation,first_seen_at) VALUES ({p},{p},{p},{p}) ON CONFLICT(item_id) DO UPDATE SET event_id=EXCLUDED.event_id",(key,int(item_id),"source_update",n))
    db.conn.execute(f"INSERT INTO ph_event_updates(event_id,item_id,label,created_at) VALUES ({p},{p},{p},{p})",(key,int(item_id),f"Source update: {source_name or 'unknown'}",n))
    if not getattr(db,"_postgres",False):db.conn.commit()
    return key

def event_timeline(db,event_id):
    ensure_schema(db); p=ph(db)
    rows=db.conn.execute(f"SELECT item_id,label,created_at FROM ph_event_updates WHERE event_id={p} ORDER BY id",(event_id,)).fetchall()
    return [dict(r) for r in rows]

def should_breaking(score):
    return bool(score and (score.get("breaking") or float(score.get("score",0))>=86))

def self_heal(db,bot,step,error,item_id=None,attempt=1):
    ensure_schema(db)
    if attempt<=1: action="retry"
    elif attempt==2: action="alternate_method"
    elif attempt==3: action="fallback_bot"
    else: action="alert_admin"
    p=ph(db); n=now()
    db.conn.execute(f"INSERT INTO ph_bot_failures(bot,item_id,step,error,attempt,action,created_at) VALUES ({p},{p},{p},{p},{p},{p},{p})",(bot,item_id,step,str(error)[:4000],attempt,action,n))
    if action=="alert_admin":
        alert(db,"CRITICAL",bot,step,item_id,f"Self-healing exhausted after {attempt} attempts: {error}")
    if not getattr(db,"_postgres",False):db.conn.commit()
    return action

def alert(db,severity,bot,step,item_id,message):
    ensure_schema(db); p=ph(db)
    db.conn.execute(f"INSERT INTO ph_alerts(severity,bot,step,item_id,message,created_at) VALUES ({p},{p},{p},{p},{p},{p})",(severity,bot,step,item_id,str(message)[:5000],now()))
    if not getattr(db,"_postgres",False):db.conn.commit()

def publish_lock(db,item_id,story_key):
    ensure_schema(db); p=ph(db); n=now()
    if getattr(db,"_postgres",False):
        row=db.conn.execute(
            f"INSERT INTO ph_publish_locks(item_id,story_key,locked_at) VALUES ({p},{p},{p}) ON CONFLICT DO NOTHING RETURNING item_id",
            (int(item_id),story_key,n),
        ).fetchone()
        return bool(row)
    cur=db.conn.execute(
        "INSERT OR IGNORE INTO ph_publish_locks(item_id,story_key,locked_at) VALUES (?,?,?)",
        (int(item_id),story_key,n),
    )
    db.conn.commit()
    return cur.rowcount==1
def mark_published(db,item_id,channel,reel_url=None):
    p=ph(db); col="website_published" if channel=="website" else "instagram_published"
    extra=", reel_url="+p if reel_url else ""
    args=[]
    if reel_url:args.append(reel_url)
    args.append(int(item_id))
    db.conn.execute(f"UPDATE ph_publish_locks SET {col}=1{extra} WHERE item_id={p}",args)
    if not getattr(db,"_postgres",False):db.conn.commit()

def is_published(db,item_id,channel):
    ensure_schema(db); p=ph(db); row=q1(db,f"SELECT website_published,instagram_published FROM ph_publish_locks WHERE item_id={p}",(int(item_id),))
    if not row:return False
    return bool(val(row,"website_published" if channel=="website" else "instagram_published",0))

def capture_resources(db,root="."):
    ensure_schema(db); root=Path(root); sizes={}
    for name,path in (("db","data"),("media","data/media"),("cloudinary_cache","data/cloudinary")):
        p=root/path
        if p.exists():
            total=sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
            sizes[name]=total
        else:sizes[name]=0
    payload={"captured_at":now(),"local_bytes":sizes,"github_actions_minutes":None,"vercel_bytes":None,"cloudinary_bytes":None,"note":"External provider usage requires its authenticated API/connector; local metrics are always available."}
    p=ph(db); db.conn.execute(f"INSERT INTO ph_resource_snapshots(captured_at,payload) VALUES ({p},{p})",(now(),json.dumps(payload)))
    if not getattr(db,"_postgres",False):db.conn.commit()
    return payload

def record_preview(db,item_id,video_path,preview_path,qa,layout_id):
    ensure_schema(db); p=ph(db); n=now()
    db.conn.execute(f"""INSERT INTO ph_reel_previews(item_id,video_path,preview_path,qa,layout_id,created_at) VALUES ({p},{p},{p},{p},{p},{p})
      ON CONFLICT(item_id) DO UPDATE SET video_path=EXCLUDED.video_path,preview_path=EXCLUDED.preview_path,qa=EXCLUDED.qa,layout_id=EXCLUDED.layout_id,created_at=EXCLUDED.created_at""",(int(item_id),str(video_path),str(preview_path or ""),json.dumps(qa),layout_id,n))
    if not getattr(db,"_postgres",False):db.conn.commit()

def historical_analytics(db,days=30):
    ensure_schema(db)
    days=max(1,min(int(days),365))
    since=datetime.now(timezone.utc)-timedelta(days=days)
    p=ph(db)
    out={"days":days,"counts":{},"hour":{},"day":{},"week":{},"month":{}}
    sources=(
        ("scores","ph_news_scores","updated_at"),
        ("alerts","ph_alerts","created_at"),
        ("previews","ph_reel_previews","created_at"),
        ("failures","ph_bot_failures","created_at"),
        ("events","ph_events","updated_at"),
    )
    for label,table,col in sources:
        try:
            row=q1(db,f"SELECT COUNT(*) AS c FROM {table} WHERE {col}>={p}",(since.isoformat(),))
            out["counts"][label]=int(val(row,"c",0) or 0)
        except Exception:
            out["counts"][label]=0
    for table,col in (
        ("ph_news_scores","updated_at"),
        ("ph_alerts","created_at"),
        ("ph_reel_previews","created_at"),
        ("ph_bot_failures","created_at"),
    ):
        try:
            rows=db.conn.execute(f"SELECT {col} AS ts FROM {table} WHERE {col}>={p}",(since.isoformat(),)).fetchall()
            for row in rows:
                raw=val(row,"ts","")
                try:
                    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
                    dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                for unit,bucket in {
                    "hour":dt.strftime("%Y-%m-%dT%H"),
                    "day":dt.strftime("%Y-%m-%d"),
                    "week":dt.strftime("%Y-W%W"),
                    "month":dt.strftime("%Y-%m"),
                }.items():
                    out[unit][bucket]=out[unit].get(bucket,0)+1
        except Exception:
            continue
    return out
def admin_snapshot(db):
    ensure_schema(db)
    p=ph(db)
    alerts=[dict(r) for r in db.conn.execute("SELECT * FROM ph_alerts WHERE resolved=0 ORDER BY id DESC LIMIT 30").fetchall()]
    failures=[dict(r) for r in db.conn.execute("SELECT * FROM ph_bot_failures ORDER BY id DESC LIMIT 30").fetchall()]
    scores=[dict(r) for r in db.conn.execute("SELECT * FROM ph_news_scores ORDER BY updated_at DESC LIMIT 30").fetchall()]
    events=[dict(r) for r in db.conn.execute("SELECT * FROM ph_events ORDER BY updated_at DESC LIMIT 30").fetchall()]
    previews=[dict(r) for r in db.conn.execute("SELECT * FROM ph_reel_previews ORDER BY created_at DESC LIMIT 20").fetchall()]
    regression=[dict(r) for r in db.conn.execute("SELECT * FROM ph_regression_runs ORDER BY id DESC LIMIT 10").fetchall()]
    return {"updated_at":now(),"alerts":alerts,"failures":failures,"scores":scores,"events":events,"previews":previews,"regression":regression,"sources":source_reliability(db),"resources":capture_resources(db),"history":historical_analytics(db,30)}
def regression_record(db,commit_ref,status,results):
    ensure_schema(db); p=ph(db)
    db.conn.execute(f"INSERT INTO ph_regression_runs(commit_ref,status,results,created_at) VALUES ({p},{p},{p},{p})",(commit_ref,status,json.dumps(results,ensure_ascii=False),now()))
    if not getattr(db,"_postgres",False):db.conn.commit()
