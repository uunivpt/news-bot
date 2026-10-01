from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

LAYOUTS = [
    {"id": "editorial", "base": 0, "family": "editorial", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "static"},
    {"id": "editorial_compact", "base": 0, "family": "editorial", "palette": "mono", "font_scale": .92, "crop": "center", "motion": "fade"},
    {"id": "editorial_accent", "base": 0, "family": "editorial", "palette": "red", "font_scale": 1.06, "crop": "top", "motion": "push"},
    {"id": "split", "base": 1, "family": "split", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "static"},
    {"id": "split_mono", "base": 1, "family": "split", "palette": "mono", "font_scale": .94, "crop": "center", "motion": "slide"},
    {"id": "split_accent", "base": 1, "family": "split", "palette": "red", "font_scale": 1.05, "crop": "right", "motion": "fade"},
    {"id": "photo", "base": 2, "family": "photo", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "zoom"},
    {"id": "photo_dark", "base": 2, "family": "photo", "palette": "dark", "font_scale": .96, "crop": "center", "motion": "fade"},
    {"id": "photo_stripe", "base": 2, "family": "photo", "palette": "red", "font_scale": 1.04, "crop": "top", "motion": "push"},
    {"id": "magazine", "base": 3, "family": "magazine", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "slide"},
    {"id": "magazine_mono", "base": 3, "family": "magazine", "palette": "mono", "font_scale": .93, "crop": "center", "motion": "static"},
    {"id": "magazine_red", "base": 3, "family": "magazine", "palette": "red", "font_scale": 1.05, "crop": "left", "motion": "fade"},
    {"id": "dark", "base": 4, "family": "dark", "palette": "dark", "font_scale": 1.00, "crop": "cover", "motion": "static"},
    {"id": "dark_red", "base": 4, "family": "dark", "palette": "red", "font_scale": 1.05, "crop": "center", "motion": "push"},
    {"id": "dark_compact", "base": 4, "family": "dark", "palette": "mono", "font_scale": .92, "crop": "right", "motion": "fade"},
    {"id": "quote", "base": 5, "family": "quote", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "static"},
    {"id": "quote_red", "base": 5, "family": "quote", "palette": "red", "font_scale": 1.06, "crop": "center", "motion": "zoom"},
    {"id": "quote_mono", "base": 5, "family": "quote", "palette": "mono", "font_scale": .94, "crop": "top", "motion": "fade"},
    {"id": "data", "base": 6, "family": "data", "palette": "light", "font_scale": .98, "crop": "cover", "motion": "slide"},
    {"id": "data_red", "base": 6, "family": "data", "palette": "red", "font_scale": 1.04, "crop": "right", "motion": "push"},
    {"id": "data_dark", "base": 6, "family": "data", "palette": "dark", "font_scale": .94, "crop": "center", "motion": "fade"},
    {"id": "minimal", "base": 7, "family": "minimal", "palette": "light", "font_scale": 1.00, "crop": "cover", "motion": "static"},
    {"id": "minimal_red", "base": 7, "family": "minimal", "palette": "red", "font_scale": 1.06, "crop": "top", "motion": "zoom"},
    {"id": "minimal_mono", "base": 7, "family": "minimal", "palette": "mono", "font_scale": .93, "crop": "center", "motion": "fade"},
]

CATEGORY_FAMILIES = {
    "politics": ("editorial", "split", "minimal", "quote", "dark"),
    "india": ("editorial", "photo", "minimal", "magazine"),
    "world": ("dark", "photo", "magazine", "split"),
    "business": ("data", "magazine", "editorial", "minimal"),
    "technology": ("data", "split", "minimal", "dark"),
    "science": ("data", "photo", "magazine", "editorial"),
    "sports": ("photo", "split", "minimal", "editorial"),
    "entertainment": ("photo", "magazine", "quote", "minimal"),
    "health": ("editorial", "data", "quote", "photo"),
    "general": ("editorial", "minimal", "magazine", "photo"),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ph(db):
    return "%s" if db._postgres else "?"


def ensure_advanced_schema(db):
    statements = [
        """CREATE TABLE IF NOT EXISTS ph_reel_layout_history (
            id BIGSERIAL PRIMARY KEY, item_id BIGINT, layout_id TEXT NOT NULL,
            family TEXT NOT NULL, palette TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
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


def _family_candidates(category):
    wanted = CATEGORY_FAMILIES.get(str(category or "general").lower(), CATEGORY_FAMILIES["general"])
    return [x for x in LAYOUTS if x["family"] in wanted]


def reserve_layout(db, item_id, category="general"):
    """Persist smart rotation; rejects consecutive family/palette repeats."""
    ensure_advanced_schema(db)
    rows = db.conn.execute(
        "SELECT layout_id,family,palette FROM ph_reel_layout_history ORDER BY id DESC LIMIT 8"
    ).fetchall()
    recent = {str(r["layout_id"] if db._postgres else r[0]) for r in rows}
    recent_pairs = {
        (str(r["family"] if db._postgres else r[1]), str(r["palette"] if db._postgres else r[2]))
        for r in rows[:2]
    }
    candidates = _family_candidates(category)
    seed = int(hashlib.sha1(f"{item_id}:{category}".encode()).hexdigest(), 16)
    ordered = sorted(candidates, key=lambda x: (seed + LAYOUTS.index(x)) % len(candidates))
    chosen = next(
        (x for x in ordered if x["id"] not in recent and (x["family"], x["palette"]) not in recent_pairs),
        None,
    ) or next((x for x in ordered if x["id"] not in recent), None) or ordered[0]
    now = _now()
    p = _ph(db)
    db.conn.execute(
        f"INSERT INTO ph_reel_layout_history(item_id,layout_id,family,palette,created_at) VALUES ({p},{p},{p},{p},{p})",
        (int(item_id), chosen["id"], chosen["family"], chosen["palette"], now),
    )
    if not db._postgres:
        db.conn.commit()
    return chosen


def layout_by_id(layout_id):
    return next((x for x in LAYOUTS if x["id"] == layout_id), LAYOUTS[0])


def visual_qa_card(path, width=1080, height=1920):
    """Geometry/asset QA for generated cards. No OCR/LLM dependency."""
    from PIL import Image, ImageStat
    p = str(path)
    with Image.open(p) as im:
        if im.size != (width, height):
            return {"passed": False, "errors": ["invalid_dimensions"], "size": im.size}
        if im.mode not in {"RGB", "RGBA"}:
            return {"passed": False, "errors": ["invalid_color_mode"]}
        stat = ImageStat.Stat(im.convert("RGB"))
        mean = sum(stat.mean) / 3
        if mean < 8 or mean > 250:
            return {"passed": False, "errors": ["near_blank_or_overexposed"]}
        return {"passed": True, "errors": [], "mean_luma": round(mean, 2)}


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


def duplicate_key(title, url=""):
    norm = re.sub(r"[^a-z0-9 ]+", " ", f"{title} {url}".lower())
    return hashlib.sha1(re.sub(r"\s+", " ", norm).strip().encode()).hexdigest()


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
    if state in {"RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED","INSTAGRAM_QUEUE","REEL_CREATED","INSTAGRAM_PUBLISHED"}:
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
    from app.phase_system import analytics
    a=analytics(db,1)
    p=_ph(db)
    counts={}
    for state in ("COLLECTED","RESEARCHING","VERIFICATION","PROCESSING","QUALITY_CHECK","PUBLISHED","INSTAGRAM_QUEUE","REEL_CREATED","INSTAGRAM_PUBLISHED"):
        row=db.conn.execute(f"SELECT COUNT(*) AS count FROM ph_story_state WHERE state={p}",(state,)).fetchone()
        counts[state]=int(row["count"] if db._postgres else row[0])
    recent=db.conn.execute("SELECT stage,status,item_id,details,created_at FROM ph_audit ORDER BY id DESC LIMIT 40").fetchall()
    return {"updated_at":_now(),"pipeline":counts,"agents":a,"audit":[dict(x) for x in recent]}


def detailed_report(db, days=7):
    ensure_advanced_schema(db)
    from app.phase_system import analytics
    payload=analytics(db,days)
    p=_ph(db)
    q=db.conn.execute("SELECT classification,COUNT(*) AS count FROM ph_verification GROUP BY classification").fetchall()
    payload["verification_breakdown"]={str(x["classification"]):int(x["count"]) for x in q}
    q=db.conn.execute("SELECT layout_id,COUNT(*) AS count FROM ph_reel_layout_history WHERE created_at >= " + p + " GROUP BY layout_id ORDER BY count DESC",( (datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),)).fetchall()
    payload["layout_usage"]={str(x["layout_id"]):int(x["count"]) for x in q}
    q=db.conn.execute("SELECT state,COUNT(*) AS count FROM ph_story_state GROUP BY state").fetchall()
    payload["pipeline_state"]={str(x["state"]):int(x["count"]) for x in q}
    return payload
