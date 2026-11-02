from __future__ import annotations
from app.schema_cache import schema_once

import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def _now():
    return datetime.now(timezone.utc).isoformat()


def _ph(db):
    return "%s" if db._postgres else "?"


def ensure_advanced_schema(db):
    with schema_once(db, 'advanced-ops-v1') as required:
        if not required:
            return
        statements = [
            """CREATE TABLE IF NOT EXISTS ph_story_state (
                item_id BIGINT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL,
                error TEXT, attempt INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS ph_audit (
                id BIGSERIAL PRIMARY KEY, item_id BIGINT, stage TEXT NOT NULL,
                status TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS ph_verification (
                item_id BIGINT PRIMARY KEY, classification TEXT NOT NULL,
                source_count INTEGER NOT NULL DEFAULT 0, source_names TEXT,
                conflicts TEXT, checked_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS ph_performance (
                id BIGSERIAL PRIMARY KEY, captured_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )""",
        ]
        for sql in statements:
            if not db._postgres:
                sql = sql.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            db.conn.execute(sql)
        if not db._postgres:
            db.conn.commit()


def classify_verification(source_count, conflicts=False):
    count = int(source_count or 0)
    if conflicts and count >= 2:
        return "CONFLICTING"
    if count >= 2:
        return "CONFIRMED"
    if count == 1:
        return "SINGLE SOURCE"
    return "UNVERIFIED"


def record_verification(db, item_id, source_count, source_names=None, conflicts=None):
    ensure_advanced_schema(db)
    classification = classify_verification(source_count, bool(conflicts))
    p = _ph(db)
    values=(int(item_id),classification,int(source_count or 0),
            json.dumps(source_names or [], ensure_ascii=False),
            json.dumps(conflicts or [], ensure_ascii=False),_now())
    db.conn.execute(
        f"INSERT INTO ph_verification(item_id,classification,source_count,source_names,conflicts,checked_at) VALUES ({p},{p},{p},{p},{p},{p}) "
        + ("ON CONFLICT(item_id) DO UPDATE SET classification=EXCLUDED.classification,source_count=EXCLUDED.source_count,source_names=EXCLUDED.source_names,conflicts=EXCLUDED.conflicts,checked_at=EXCLUDED.checked_at"
           if db._postgres else
           "ON CONFLICT(item_id) DO UPDATE SET classification=excluded.classification,source_count=excluded.source_count,source_names=excluded.source_names,conflicts=excluded.conflicts,checked_at=excluded.checked_at"),
        values,
    )
    if not db._postgres:
        db.conn.commit()
    return classification


def audit_stage(db, item_id, stage, status="completed", details=None):
    ensure_advanced_schema(db)
    p=_ph(db)
    db.conn.execute(
        f"INSERT INTO ph_audit(item_id,stage,status,details,created_at) VALUES ({p},{p},{p},{p},{p})",
        (int(item_id),stage,status,json.dumps(details or {},ensure_ascii=False)[:8000],_now()),
    )
    if not db._postgres:
        db.conn.commit()


def duplicate_similarity(a, b):
    def words(v):
        return set(re.findall(r"[a-z0-9]{3,}", str(v or "").lower()))
    aw,bw=words(a),words(b)
    if not aw or not bw:
        return 0.0
    return len(aw & bw)/max(1,len(aw | bw))


def state_transition(db,item_id,state,error=None):
    ensure_advanced_schema(db)
    p=_ph(db)
    row=db.conn.execute(f"SELECT attempt FROM ph_story_state WHERE item_id={p}",(int(item_id),)).fetchone()
    attempt=int(row["attempt"] if row else 0)
    if state in {"RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED"}:
        attempt += 1 if state == "RESEARCHING" else 0
    values=(int(item_id),state,_now(),error,attempt)
    db.conn.execute(
        f"INSERT INTO ph_story_state(item_id,state,updated_at,error,attempt) VALUES ({p},{p},{p},{p},{p}) "
        + ("ON CONFLICT(item_id) DO UPDATE SET state=EXCLUDED.state,updated_at=EXCLUDED.updated_at,error=EXCLUDED.error,attempt=EXCLUDED.attempt"
           if db._postgres else
           "ON CONFLICT(item_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,error=excluded.error,attempt=excluded.attempt"),
        values,
    )
    if not db._postgres:
        db.conn.commit()
    audit_stage(db,item_id,state,"failed" if error else "completed",{"error":error} if error else {})


def snapshot_performance(db, days=1):
    ensure_advanced_schema(db)
    from app.phase_system import analytics
    payload=analytics(db,days)
    now=_now()
    p=_ph(db)
    db.conn.execute(f"INSERT INTO ph_performance(captured_at,payload) VALUES ({p},{p})",(now,json.dumps(payload,ensure_ascii=False)))
    if not db._postgres:
        db.conn.commit()
    return payload


def live_dashboard(db):
    ensure_advanced_schema(db)
    from app.phase_system import phase_analytics
    phase_data=phase_analytics(db,1)
    a=phase_data["agents"]
    phases=phase_data["phases"]
    p=_ph(db)
    counts={}
    for state in ("COLLECTED","RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED"):
        row=db.conn.execute(f"SELECT COUNT(*) AS count FROM ph_story_state WHERE state={p}",(state,)).fetchone()
        counts[state]=int(row["count"] if db._postgres else row[0])
    settings=db.get_settings()
    try:
        total=db.count()
        published=db.count_status("published")
        review_needed=db.count_status("published","needs_review")
        india_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        start = datetime.combine(india_today, datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc).isoformat()
        end = (datetime.combine(india_today, datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        stats={"total":total,"published":published,"review_needed":review_needed}
    except Exception:
        stats={"total":0,"published":0,"review_needed":0}
    recent=db.conn.execute("SELECT stage,status,item_id,details,created_at FROM ph_audit ORDER BY id DESC LIMIT 40").fetchall()
    return {"updated_at":_now(),"pipeline":counts,"agents":a,"phases":phases,"stats":stats,"settings":settings,"audit":[dict(x) for x in recent]}


def detailed_report(db, days=7):
    ensure_advanced_schema(db)
    from app.phase_system import analytics
    payload=analytics(db,days)
    p=_ph(db)
    q=db.conn.execute("SELECT classification,COUNT(*) AS count FROM ph_verification GROUP BY classification").fetchall()
    payload["verification_breakdown"]={str(x["classification"]):int(x["count"]) for x in q}
    q=db.conn.execute("SELECT state,COUNT(*) AS count FROM ph_story_state GROUP BY state").fetchall()
    payload["pipeline_state"]={str(x["state"]):int(x["count"]) for x in q}
    return payload


def find_duplicate_story(db, item_id, title, threshold=0.82):
    """Deterministic high-confidence duplicate detector; returns existing item or None."""
    rows=db.latest_identities(250)
    best=None
    for row in rows:
        rid=int(row["id"])
        if rid==int(item_id):
            continue
        score=duplicate_similarity(title,row["title"])
        if score>=threshold and (best is None or score>best[0]):
            best=(score,dict(row))
    return best
