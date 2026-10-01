from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

AGENTS = {
    "trend": ("Trend Scout", "Collects and normalizes incoming stories", 1),
    "manager": ("Manager", "Routes work and controls workflow state", 1),
    "research": ("Research Desk", "Clusters stories and aggregates source coverage", 2),
    "factcheck": ("Verification Desk", "Cross-source verification precheck and risk flags", 2),
    "writer": ("Newsroom Writer", "Builds summaries and articles from source text", 2),
    "reviewer": ("Review Desk", "Quality gate, corrections and human-review routing", 3),
    "hr": ("Agent HR", "Tracks reliability, load and training events", 3),
    "automation": ("Automation Controller", "Schedules queues, retries and operational workflows", 4),
    "publisher": ("Web Publisher", "Publishes approved stories to the public site", 4),
    "instagram": ("Instagram Publisher", "Builds and publishes Reels within configured limits", 4),
    "reporting": ("Reporting Desk", "Produces operational analytics and report-ready output", 5),
}

PHASES = {
    1: "Foundation & orchestration",
    2: "Research, verification & newsroom",
    3: "HR, performance, training & knowledge",
    4: "Automation, queues & analytics",
    5: "Professional output, UI & quality control",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ph_agents (
 agent_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, phase INTEGER NOT NULL,
 score REAL NOT NULL DEFAULT 100, enabled INTEGER NOT NULL DEFAULT 1,
 last_trained_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ph_agent_runs (
 id BIGSERIAL PRIMARY KEY, agent_id TEXT NOT NULL, operation TEXT NOT NULL, item_id BIGINT,
 status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, duration_seconds REAL,
 metadata TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS ph_training (
 id BIGSERIAL PRIMARY KEY, agent_id TEXT NOT NULL, event_type TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ph_clusters (
 cluster_id TEXT PRIMARY KEY, canonical_title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 source_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ph_cluster_items (
 cluster_id TEXT NOT NULL, news_item_id BIGINT NOT NULL, source_name TEXT NOT NULL, source_url TEXT,
 created_at TEXT NOT NULL, PRIMARY KEY(cluster_id, news_item_id)
);
CREATE TABLE IF NOT EXISTS ph_knowledge (
 id BIGSERIAL PRIMARY KEY, topic TEXT NOT NULL, value TEXT NOT NULL, source TEXT,
 confidence REAL, updated_at TEXT NOT NULL, UNIQUE(topic, value)
);
CREATE TABLE IF NOT EXISTS ph_reports (
 id BIGSERIAL PRIMARY KEY, report_type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
 payload TEXT, created_at TEXT NOT NULL
);
"""

def _exec(db, sql, params=()):
    return db.conn.execute(sql, params)

def ensure_schema(db):
    statements = [x.strip() for x in SCHEMA.split(";") if x.strip()]
    for statement in statements:
        if not db._postgres:
            statement = statement.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        _exec(db, statement)
    if not db._postgres:
        db.conn.commit()
    now = datetime.now(timezone.utc).isoformat()
    for aid, (name, role, phase) in AGENTS.items():
        if db._postgres:
            _exec(db, "INSERT INTO ph_agents(agent_id,name,role,phase,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(agent_id) DO UPDATE SET name=EXCLUDED.name,role=EXCLUDED.role,phase=EXCLUDED.phase,updated_at=EXCLUDED.updated_at", (aid,name,role,phase,now,now))
        else:
            _exec(db, "INSERT OR IGNORE INTO ph_agents(agent_id,name,role,phase,created_at,updated_at) VALUES (?,?,?,?,?,?)", (aid,name,role,phase,now,now))
            _exec(db, "UPDATE ph_agents SET name=?,role=?,phase=?,updated_at=? WHERE agent_id=?", (name,role,phase,now,aid))
    if not db._postgres:
        db.conn.commit()

def start(db, agent_id, operation, item_id=None, metadata=""):
    ensure_schema(db)
    now = datetime.now(timezone.utc).isoformat()
    q = "INSERT INTO ph_agent_runs(agent_id,operation,item_id,status,started_at,metadata) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id" if db._postgres else "INSERT INTO ph_agent_runs(agent_id,operation,item_id,status,started_at,metadata) VALUES (?,?,?,?,?,?) RETURNING id"
    row = _exec(db,q,(agent_id,operation,item_id,"running",now,str(metadata)[:8000])).fetchone()
    if not db._postgres: db.conn.commit()
    return int(row["id"] if db._postgres else row[0]), time.perf_counter()

def finish(db, run_id, started, success=True, error=None):
    now = datetime.now(timezone.utc).isoformat()
    ph = "%s" if db._postgres else "?"
    _exec(db, "UPDATE ph_agent_runs SET status="+ph+",finished_at="+ph+",duration_seconds="+ph+",error="+ph+" WHERE id="+ph, ("success" if success else "failed",now,round(time.perf_counter()-started,4),str(error)[:4000] if error else None,run_id))
    # Resolve the agent for this run and update operational reliability.
    row=_exec(db,"SELECT agent_id FROM ph_agent_runs WHERE id="+ph,(run_id,)).fetchone()
    if row:
        reliability_update(db,row["agent_id"],success)
    if not db._postgres: db.conn.commit()


@contextmanager
def run(db, agent_id, operation, item_id=None, metadata=""):
    rid, started = start(db,agent_id,operation,item_id,metadata)
    try:
        yield rid
    except Exception as exc:
        finish(db,rid,started,False,exc)
        raise
    else:
        finish(db,rid,started,True)

def train(db, agent_id, event_type, notes=""):
    ensure_schema(db)
    now=datetime.now(timezone.utc).isoformat()
    q="INSERT INTO ph_training(agent_id,event_type,notes,created_at) VALUES (%s,%s,%s,%s)" if db._postgres else "INSERT INTO ph_training(agent_id,event_type,notes,created_at) VALUES (?,?,?,?)"
    _exec(db,q,(agent_id,event_type,str(notes)[:4000],now))
    if db._postgres:
        _exec(db,"UPDATE ph_agents SET last_trained_at=%s,updated_at=%s WHERE agent_id=%s",(now,now,agent_id))
    else:
        _exec(db,"UPDATE ph_agents SET last_trained_at=?,updated_at=? WHERE agent_id=?",(now,now,agent_id)); db.conn.commit()


def manager_route(title="", category="general", has_image=False):
    """Deterministic manager decision: route each story through the desks it needs."""
    text=f"{title} {category}".lower()
    route=["trend","manager","research","factcheck","writer","reviewer","publisher"]
    if any(k in text for k in ("market","stock","shares","gdp","inflation")):
        route.insert(3,"research")
    if has_image:
        route.append("instagram")
    return list(dict.fromkeys(route))


def quality_gate(title="", summary="", article="", allow_short=False):
    """Deterministic publication QA; never claims factual truth."""
    errors=[]; warnings=[]
    title=str(title or "").strip(); summary=str(summary or "").strip(); article=str(article or "").strip()
    if not title: errors.append("missing_title")
    elif len(title)>180: errors.append("title_too_long")
    if not summary: errors.append("missing_summary")
    elif not allow_short and len(summary)<35: errors.append("summary_too_short")
    if not article: errors.append("missing_article")
    elif not allow_short and len(article)<max(60,len(summary)): errors.append("article_too_short")
    for field_name,value in (("summary",summary),("article",article)):
        if re.search(r"\b(?:source\s*:|reported\s+by|via\s+)\s*[^.\n]{2,}",value,re.I):
            warnings.append(f"{field_name}_contains_source_fragment")
        if value.count("(")!=value.count(")"):
            errors.append(f"{field_name}_unbalanced_parentheses")
    if summary and title.casefold()==summary.casefold():
        warnings.append("summary_repeats_title")
    score=max(0,100-len(errors)*25-len(warnings)*5)
    return {"passed":not errors,"score":score,"errors":errors,"warnings":warnings}


def reliability_update(db, agent_id, success):
    """Operational reliability telemetry, not a factual-truth score."""
    ensure_schema(db)
    delta=1.0 if success else -3.0
    ph="%s" if db._postgres else "?"
    row=_exec(db,"SELECT score FROM ph_agents WHERE agent_id="+ph,(agent_id,)).fetchone()
    current=float(row["score"] if row else 100)
    score=max(0.0,min(100.0,current+delta))
    _exec(db,"UPDATE ph_agents SET score="+ph+",updated_at="+ph+" WHERE agent_id="+ph,(score,datetime.now(timezone.utc).isoformat(),agent_id))
    if not db._postgres: db.conn.commit()
    return round(score,1)


def _words(text):
    return set(re.findall(r"[a-z0-9]{3,}",str(text or "").lower()))

def cluster_stories(db, limit=250):
    ensure_schema(db)
    rows=[dict(r) for r in db.latest(limit=limit,status="all")]
    rows.sort(key=lambda x:int(x["id"]))
    assigned=0
    for row in rows:
        title=str(row.get("title") or "")
        words=_words(title)
        if not words: continue
        best=None
        for existing in rows:
            if int(existing["id"])>=int(row["id"]): break
            other=_words(existing.get("title"))
            if not other: continue
            score=len(words & other)/max(1,len(words | other))
            if best is None or score>best[0]: best=(score,existing)
        if best and best[0]>=0.45:
            cluster_id=best[1].get("_cluster_id") or ("c-"+hashlib.sha1(" ".join(sorted(_words(best[1]["title"]))).encode()).hexdigest()[:16])
        else:
            cluster_id="c-"+hashlib.sha1(" ".join(sorted(words)).encode()).hexdigest()[:16]
        row["_cluster_id"]=cluster_id
        now=datetime.now(timezone.utc).isoformat()
        ph="%s" if db._postgres else "?"
        q="INSERT INTO ph_clusters(cluster_id,canonical_title,created_at,updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT(cluster_id) DO UPDATE SET updated_at=EXCLUDED.updated_at" if db._postgres else "INSERT OR IGNORE INTO ph_clusters(cluster_id,canonical_title,created_at,updated_at) VALUES (?,?,?,?)"
        _exec(db,q,(cluster_id,title,now,now))
        q="INSERT INTO ph_cluster_items(cluster_id,news_item_id,source_name,source_url,created_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING" if db._postgres else "INSERT OR IGNORE INTO ph_cluster_items(cluster_id,news_item_id,source_name,source_url,created_at) VALUES (?,?,?,?,?)"
        _exec(db,q,(cluster_id,row["id"],row.get("source_name") or "",row.get("url") or "",now))
        assigned+=1
    if not db._postgres: db.conn.commit()
    _exec(db,"UPDATE ph_clusters SET source_count=(SELECT COUNT(*) FROM ph_cluster_items x WHERE x.cluster_id=ph_clusters.cluster_id)")
    if not db._postgres: db.conn.commit()
    return assigned

def analytics(db, days=7):
    ensure_schema(db)
    cutoff=(datetime.now(timezone.utc)-timedelta(days=max(1,min(int(days),90)))).isoformat()
    ph="%s" if db._postgres else "?"
    agents=_exec(db,"SELECT * FROM ph_agents ORDER BY phase,agent_id").fetchall()
    out=[]
    for a in agents:
        s=_exec(db,"SELECT COUNT(*) runs,SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) successes,SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,AVG(duration_seconds) avg_duration FROM ph_agent_runs WHERE agent_id="+ph+" AND started_at >= "+ph,(a["agent_id"],cutoff)).fetchone()
        current=_exec(db,"SELECT COUNT(*) count FROM ph_agent_runs WHERE agent_id="+ph+" AND status='running'",(a["agent_id"],)).fetchone()
        runs=int(s["runs"] or 0); successes=int(s["successes"] or 0); failed=int(s["failed"] or 0); active=int(current["count"] or 0)
        row=dict(a); row.update(runs=runs,successes=successes,failed=failed,success_rate=round(successes/runs*100,1) if runs else None,avg_duration_seconds=round(float(s["avg_duration"] or 0),3),current_load=active,load_percent=min(100,active*25)); out.append(row)
    totals={"runs":sum(x["runs"] for x in out),"successes":sum(x["successes"] for x in out),"failed":sum(x["failed"] for x in out)}
    totals["success_rate"]=round(totals["successes"]/totals["runs"]*100,1) if totals["runs"] else None
    return {"agents":out,"totals":totals,"days":days}

def phase_analytics(db, days=7):
    data=analytics(db,days)
    phases=[]
    for phase,name in PHASES.items():
        rows=[x for x in data["agents"] if int(x["phase"])==phase]
        runs=sum(int(x["runs"]) for x in rows); ok=sum(int(x["successes"]) for x in rows)
        phases.append({"phase":phase,"name":name,"agents":len(rows),"active_agents":sum(1 for x in rows if x["runs"]),"runs":runs,"successes":ok,"operational_success_rate":round(ok/runs*100,1) if runs else None,"implemented":True})
    return {"phases":phases,"agents":data["agents"],"totals":data["totals"]}

def cluster_summary(db):
    ensure_schema(db)
    rows=_exec(db,"SELECT cluster_id,canonical_title,source_count,updated_at FROM ph_clusters ORDER BY updated_at DESC LIMIT 20").fetchall()
    return [dict(x) for x in rows]

def add_knowledge(db,topic,value,source="",confidence=None):
    ensure_schema(db); now=datetime.now(timezone.utc).isoformat()
    q="INSERT INTO ph_knowledge(topic,value,source,confidence,updated_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(topic,value) DO UPDATE SET source=EXCLUDED.source,confidence=EXCLUDED.confidence,updated_at=EXCLUDED.updated_at" if db._postgres else "INSERT OR REPLACE INTO ph_knowledge(topic,value,source,confidence,updated_at) VALUES (?,?,?,?,?)"
    _exec(db,q,(topic,value,source,confidence,now))
    if not db._postgres: db.conn.commit()
