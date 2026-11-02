"""Deterministic operations engine for PoliticsHub upgrades 1-16.

No LLM/API dependency. All decisions are rule/score/hash based and persisted.
"""
from __future__ import annotations
from app.schema_cache import schema_once
import hashlib, json, re
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATES=("COLLECTED","RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED")
BREAKING_TERMS=("breaking","just in","urgent","alert","earthquake","attack","resigns","resignation","dead","dies","war","explosion","emergency","major","supreme court","prime minister","president","election result")
IMPORTANCE_TERMS=("election","government","parliament","supreme court","prime minister","president","war","conflict","economy","market","budget","policy","earthquake","cyclone","flood","security")
CATEGORY_WEIGHT={"politics":24,"india":20,"world":22,"business":17,"technology":14,"science":12,"sports":10,"health":15,"entertainment":8,"general":8}

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
    with schema_once(db, 'advanced-system-v1') as required:
        if not required:
            return
        stmts=[
          f"""CREATE TABLE IF NOT EXISTS ph_news_scores(item_id BIGINT PRIMARY KEY, score REAL NOT NULL, freshness REAL, coverage REAL, importance REAL, duplicate_risk REAL, verification REAL, breaking INTEGER DEFAULT 0, reason TEXT, updated_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_source_reliability(source_name TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0, successes INTEGER DEFAULT 0, broken_links INTEGER DEFAULT 0, corrections INTEGER DEFAULT 0, coverage_events INTEGER DEFAULT 0, last_seen_at TEXT, updated_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_events(event_id TEXT PRIMARY KEY, canonical_title TEXT NOT NULL, category TEXT, priority REAL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT DEFAULT 'active')""",
          """CREATE TABLE IF NOT EXISTS ph_event_items(event_id TEXT NOT NULL, item_id BIGINT PRIMARY KEY, relation TEXT NOT NULL, first_seen_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_bot_failures(id BIGSERIAL PRIMARY KEY, bot TEXT NOT NULL, item_id BIGINT, step TEXT NOT NULL, error TEXT, attempt INTEGER DEFAULT 1, action TEXT, resolved INTEGER DEFAULT 0, created_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_alerts(id BIGSERIAL PRIMARY KEY, severity TEXT NOT NULL, bot TEXT, step TEXT, item_id BIGINT, message TEXT NOT NULL, resolved INTEGER DEFAULT 0, created_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_publish_locks(item_id BIGINT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE, website_published INTEGER DEFAULT 0, locked_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_resource_snapshots(id BIGSERIAL PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_regression_runs(id BIGSERIAL PRIMARY KEY, commit_ref TEXT, status TEXT NOT NULL, results TEXT, created_at TEXT NOT NULL)""",
          """CREATE TABLE IF NOT EXISTS ph_event_updates(id BIGSERIAL PRIMARY KEY, event_id TEXT NOT NULL, item_id BIGINT, label TEXT NOT NULL, created_at TEXT NOT NULL)""",
        ]
        for s in stmts:
            if not getattr(db,"_postgres",False):
                s=s.replace("BIGSERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT")
            db.conn.execute(s)
        if not getattr(db,"_postgres",False): db.conn.commit()

def _words(text):
    return set(re.findall(r"[\w\u0900-\u097f]{3,}",str(text or "").casefold()))

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

def record_editorial_publication(db, row):
    """Record a completed editor publication, never claim a source was fetched."""
    from urllib.parse import urlsplit
    source = str(val(row, "source_name", "") or "").strip()
    try:
        url = urlsplit(str(val(row, "url", "") or ""))
        has_source = bool(source and url.scheme == "https" and url.hostname)
    except ValueError:
        has_source = False
    score = score_story(db, row, source_count=1 if has_source else 0,
                        verification="SINGLE SOURCE" if has_source else "UNVERIFIED")
    event_id = attach_event(db, int(val(row, "id")), str(val(row, "title", "")),
                            str(val(row, "category", "general")), source)
    return {"score": score, "event_id": event_id, "basis": "editor_publication",
            "independent_fact_check": False}

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
def mark_published(db,item_id,channel="website"):
    if channel != "website":raise ValueError("Unsupported publication channel")
    p=ph(db)
    db.conn.execute(f"UPDATE ph_publish_locks SET website_published=1 WHERE item_id={p}",(int(item_id),))
    if not getattr(db,"_postgres",False):db.conn.commit()

def is_published(db,item_id,channel="website"):
    if channel != "website":raise ValueError("Unsupported publication channel")
    ensure_schema(db); p=ph(db)
    row=q1(db,f"SELECT website_published FROM ph_publish_locks WHERE item_id={p}",(int(item_id),))
    return bool(val(row,"website_published",0))

def resource_usage(db, root=None):
    """Read actual database allocation; absence/failure is never a zero-byte DB."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    engine = "postgresql" if getattr(db, "_postgres", False) else "sqlite"
    database = {"engine": engine, "bytes": None, "status": "unavailable"}
    try:
        if engine == "postgresql":
            row = db.conn.execute("SELECT pg_database_size(current_database()) AS bytes").fetchone()
            size = val(row, "bytes")
        else:
            pages = db.conn.execute("PRAGMA page_count").fetchone()
            page_size = db.conn.execute("PRAGMA page_size").fetchone()
            size = int(pages[0]) * int(page_size[0])
        if size is None or int(size) < 0:
            raise ValueError("Database size unavailable")
        database.update(bytes=int(size), status="available")
    except Exception:
        pass  # Driver errors can include connection details; do not expose them.
    media = {"bytes": None, "status": "not_configured"}
    media_path = root / "data" / "media"
    if media_path.is_dir():
        try:
            media.update(bytes=sum(path.stat().st_size for path in media_path.rglob("*")
                                   if path.is_file() and not path.is_symlink()), status="available")
        except OSError:
            media.update(bytes=None, status="unavailable")
    return {"captured_at": now(), "database": database, "media": media,
            "local_bytes": {"db": database["bytes"], "media": media["bytes"]},
            "github_actions_minutes": None, "vercel_bytes": None,
            "note": "Database allocation is measured from the connected database. Unavailable or unconfigured storage is not reported as zero."}


def capture_resources(db, root=None):
    """Explicit worker capture. Dashboard GETs call resource_usage instead."""
    ensure_schema(db)
    payload = resource_usage(db, root)
    p = ph(db)
    db.conn.execute(f"INSERT INTO ph_resource_snapshots(captured_at,payload) VALUES ({p},{p})", (now(), json.dumps(payload)))
    if not getattr(db, "_postgres", False):
        db.conn.commit()
    return payload


def story_inventory(db):
    """Current stored content, not fabricated processing history."""
    result = {"status": "unavailable", "total": None, "pending": None,
              "published": None, "with_article": None, "source_count": None,
              "last_collected_at": None, "sources": [], "sources_available": False}
    try:
        row = db.conn.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) AS pending,
            COALESCE(SUM(CASE WHEN status='published' THEN 1 ELSE 0 END),0) AS published,
            COALESCE(SUM(CASE WHEN LENGTH(COALESCE(bot_article,''))>0 THEN 1 ELSE 0 END),0) AS with_article,
            COUNT(DISTINCT NULLIF(source_name,'')) AS source_count, MAX(collected_at) AS last_collected_at
            FROM news_items""").fetchone()
        result.update({key: int(val(row, key, 0) or 0) for key in ("total", "pending", "published", "with_article", "source_count")})
        result.update(status="available", last_collected_at=val(row, "last_collected_at"))
        result["sources"] = [dict(row) for row in db.conn.execute("""SELECT source_name AS source,
            COUNT(*) AS records, COALESCE(SUM(CASE WHEN status='published' THEN 1 ELSE 0 END),0) AS published,
            MAX(collected_at) AS last_collected_at FROM news_items GROUP BY source_name
            ORDER BY COUNT(*) DESC,source_name LIMIT 50""").fetchall()]
        result["sources_available"] = True
    except Exception:
        pass
    return result

def historical_analytics(db,days=30):
    ensure_schema(db)
    days=max(1,min(int(days),365))
    since=datetime.now(timezone.utc)-timedelta(days=days)
    p=ph(db)
    out={"days":days,"counts":{},"availability":{},"hour":{},"day":{},"week":{},"month":{}}
    sources=(
        ("scores","ph_news_scores","updated_at"),
        ("alerts","ph_alerts","created_at"),
        ("failures","ph_bot_failures","created_at"),
        ("events","ph_events","updated_at"),
    )
    for label,table,col in sources:
        try:
            row=q1(db,f"SELECT COUNT(*) AS c FROM {table} WHERE {col}>={p}",(since.isoformat(),))
            out["counts"][label]=int(val(row,"c",0) or 0)
            out["availability"][label]=True
        except Exception:
            out["counts"][label]=None
            out["availability"][label]=False
    for table,col in (
        ("ph_news_scores","updated_at"),
        ("ph_alerts","created_at"),
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
    queries = {
        "alerts": ("ph_alerts", " WHERE resolved=0", "id", 30),
        "failures": ("ph_bot_failures", "", "id", 30),
        "scores": ("ph_news_scores", "", "updated_at", 30),
        "events": ("ph_events", "", "updated_at", 30),
        "regression": ("ph_regression_runs", "", "id", 10),
    }
    result = {"updated_at": now(), "counts": {}, "availability": {}}
    for key, (table, where, order, limit) in queries.items():
        try:
            result[key] = [dict(row) for row in db.conn.execute(
                f"SELECT * FROM {table}{where} ORDER BY {order} DESC LIMIT {limit}").fetchall()]
            count = db.conn.execute(f"SELECT COUNT(*) AS count FROM {table}{where}").fetchone()
            result["counts"][key] = int(val(count, "count", 0) or 0)
            result["availability"][key] = True
        except Exception:
            result[key] = []
            result["counts"][key] = None
            result["availability"][key] = False
    try:
        result["sources"] = source_reliability(db)
        result["availability"]["sources"] = True
    except Exception:
        result["sources"] = []
        result["availability"]["sources"] = False
    result.update(resources=resource_usage(db), history=historical_analytics(db, 30), inventory=story_inventory(db))
    return result

def regression_record(db,commit_ref,status,results):
    ensure_schema(db); p=ph(db)
    db.conn.execute(f"INSERT INTO ph_regression_runs(commit_ref,status,results,created_at) VALUES ({p},{p},{p},{p})",(commit_ref,status,json.dumps(results,ensure_ascii=False),now()))
    if not getattr(db,"_postgres",False):db.conn.commit()
