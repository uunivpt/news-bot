from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

AGENTS = {
    "trend": {"name": "Trend Scout", "phase": 1, "role": "Collects and normalizes incoming stories"},
    "manager": {"name": "Manager", "phase": 1, "role": "Routes work and controls workflow state"},
    "research": {"name": "Research Desk", "phase": 2, "role": "Clusters stories and aggregates source coverage"},
    "factcheck": {"name": "Verification Desk", "phase": 2, "role": "Cross-source verification precheck and risk flags"},
    "writer": {"name": "Newsroom Writer", "phase": 2, "role": "Builds concise summaries and articles from source text"},
    "reviewer": {"name": "Review Desk", "phase": 3, "role": "Quality gate, corrections and human-review routing"},
    "hr": {"name": "Agent HR", "phase": 3, "role": "Tracks agent reliability, load and training events"},
    "automation": {"name": "Automation Controller", "phase": 4, "role": "Schedules queues, retries and operational workflows"},
    "publisher": {"name": "Web Publisher", "phase": 4, "role": "Publishes approved stories to the public site"},
    "instagram": {"name": "Instagram Publisher", "phase": 4, "role": "Builds and publishes Reels within configured limits"},
    "reporting": {"name": "Reporting Desk", "phase": 5, "role": "Produces operational analytics and report-ready output"},
}

PHASES = {
    1: "Foundation & orchestration",
    2: "Research, verification & newsroom",
    3: "HR, performance, training & knowledge",
    4: "Automation, queues & analytics",
    5: "Professional output, UI & quality control",
}


def ensure_agents(db):
    now = datetime.now(timezone.utc).isoformat()
    for agent_id, spec in AGENTS.items():
        db.upsert_agent(agent_id, spec["name"], spec["role"], spec["phase"], now)


@contextmanager
def agent_run(db, agent_id, operation, item_id=None, metadata=None):
    ensure_agents(db)
    started = time.perf_counter()
    run_id = db.start_agent_run(
        agent_id,
        operation,
        item_id=item_id,
        metadata=json.dumps(metadata or {}, ensure_ascii=False)[:8000],
    )
    try:
        yield run_id
    except Exception as exc:
        db.finish_agent_run(
            run_id,
            "failed",
            round(time.perf_counter() - started, 4),
            error=str(exc)[:4000],
        )
        raise
    else:
        db.finish_agent_run(
            run_id,
            "success",
            round(time.perf_counter() - started, 4),
        )


def record_agent_result(db, agent_id, operation, success=True, item_id=None, metadata=None, error=None):
    ensure_agents(db)
    started = time.perf_counter()
    run_id = db.start_agent_run(
        agent_id,
        operation,
        item_id=item_id,
        metadata=json.dumps(metadata or {}, ensure_ascii=False)[:8000],
    )
    db.finish_agent_run(
        run_id,
        "success" if success else "failed",
        round(time.perf_counter() - started, 4),
        error=str(error)[:4000] if error else None,
    )
    return run_id


def dashboard(db, days=7):
    ensure_agents(db)
    return db.agent_dashboard(days=days)


def phase_dashboard(db, days=7):
    data = dashboard(db, days)
    by_agent = {row["agent_id"]: row for row in data["agents"]}
    phases = []
    for phase, title in PHASES.items():
        ids = [k for k, v in AGENTS.items() if v["phase"] == phase]
        active = [by_agent[k] for k in ids if by_agent.get(k, {}).get("runs", 0)]
        runs = sum(int(x.get("runs", 0)) for x in active)
        successes = sum(int(x.get("successes", 0)) for x in active)
        operational = round((successes / runs) * 100, 1) if runs else None
        phases.append({
            "phase": phase,
            "name": title,
            "agents": len(ids),
            "active_agents": len(active),
            "runs": runs,
            "successes": successes,
            "operational_success_rate": operational,
            "implemented": True,
        })
    return {"phases": phases, "agents": data["agents"], "totals": data["totals"]}


def health_summary(db):
    data = dashboard(db, days=1)
    total = int(data["totals"].get("runs", 0))
    successes = int(data["totals"].get("successes", 0))
    return {
        "operational_success_rate_24h": round(successes / total * 100, 1) if total else None,
        "runs_24h": total,
        "failed_24h": int(data["totals"].get("failed", 0)),
        "active_agents": sum(1 for x in data["agents"] if x.get("runs", 0)),
    }
