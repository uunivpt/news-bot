"""Phase 4: authenticated, read-only alert triage and historical operations.

Source history is real append-only collector outcomes from the upgraded phone;
private history does not exist in GitHub snapshots. Never publish alert contents
anonymously, auto-edit a story, create tables on GET, or call a remote API here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .editorial_access import table_exists
from .source_inventory import _stamp
from .newsroom_operations import source_triage

TREND_DAYS = 14
MAX_ALERTS = 30
MAX_FOLLOWUPS = 40


def _stamp_or_none(value):
    value = _stamp(value)
    if not value:
        return None
    return value.astimezone(timezone.utc)


def _age_minutes(value, now):
    at = _stamp_or_none(value)
    if not at or at > now + timedelta(minutes=5):
        return None
    return max(0, round((now - at).total_seconds() / 60))


def _restrict(where):
    # Only pass preconstructed scope_sql() clauses; no user-provided SQL.
    return str(where or "").strip().removeprefix("WHERE ").strip()


def _daily_series(database, *, where, params, now):
    start = (now - timedelta(days=TREND_DAYS - 1)).date()
    dates = [(start + timedelta(days=day)).isoformat() for day in range(TREND_DAYS)]
    start_text = start.isoformat()
    daily = {day: {"day": day, "healthy": None, "failed": None,
                   "not_configured": None, "published": 0} for day in dates}
    recorded = table_exists(database, "ph_source_collection_history")
    outcome_rows = 0
    if recorded:
        for bucket in daily.values():
            bucket.update(healthy=0, failed=0, not_configured=0)
        rows = database.conn.execute(
            "SELECT substr(attempted_at,1,10) AS day,status,COUNT(*) AS total "
            "FROM ph_source_collection_history WHERE attempted_at >= "
            + ("%s" if database._postgres else "?")
            + " GROUP BY substr(attempted_at,1,10),status",
            (start_text,),
        ).fetchall()
        for row in rows:
            day, status, total = str(row["day"]), str(row["status"]), int(row["total"])
            if day in daily and status in {"healthy", "failed", "not_configured"}:
                daily[day][status] += total
                outcome_rows += total
    p = "%s" if database._postgres else "?"
    restriction = _restrict(where)
    sql = (
        "SELECT substr(published_at_site,1,10) AS day,COUNT(*) AS total "
        "FROM news_items WHERE status='published' AND published_at_site >= " + p
        + (" AND " + restriction if restriction else "")
        + " GROUP BY substr(published_at_site,1,10)"
    )
    for row in database.conn.execute(sql, (start_text, *params)).fetchall():
        day = str(row["day"])
        if day in daily:
            daily[day]["published"] = int(row["total"])
    return {
        "days": TREND_DAYS, "collector_history_available": recorded,
        "recorded_outcomes": outcome_rows if recorded else None,
        "series": list(daily.values()),
        "note": (
            "Collector history starts after the upgraded phone worker records its first "
            "completed check; earlier results are not reconstructed. Publication counts "
            "come from committed site-publication timestamps, not live URL checks."
        ),
    }


def newsroom_alerts(database, inventory, *, where="", params=(), now=None):
    """Read-only, scoped signals; only invoke for authorized operations readers."""
    now = now or datetime.now(timezone.utc)
    if inventory.get("scope") != "database":
        return {"scope": "unavailable", "alerts": [], "followups": [],
                "trend": None, "status": "unavailable"}
    p = "%s" if database._postgres else "?"
    restriction = _restrict(where)
    scope = (" AND item_id IN (SELECT id FROM news_items WHERE " + restriction + ")") if restriction else ""
    alerts = []
    followups = []
    triage = source_triage(inventory)

    def add(kind, severity, title, detail, *, item_id=None, source=None, at=None):
        if len(alerts) < MAX_ALERTS:
            alerts.append({
                "kind": kind, "severity": severity, "title": title, "detail": detail,
                "item_id": item_id, "source": source, "at": at,
            })

    for incident in triage.get("incidents") or []:
        state = incident["state"]
        add("source", "high" if state == "failed" else "warning",
            "Source " + ("failed" if state == "failed" else
                          "overdue" if state == "stale" else "not configured"),
            "Check the phone source collector and its latest recorded outcome.",
            source=incident["name"], at=incident.get("last_attempt_at"))

    delivery_recorded = table_exists(database, "ph_public_delivery")
    queue_cutoff = (now - timedelta(minutes=45)).isoformat()
    if delivery_recorded:
        rows = database.conn.execute(
            "SELECT item_id,state,updated_at FROM ph_public_delivery "
            "WHERE (state='failed' OR (state IN ('queued','syncing') AND updated_at <= " + p + "))"
            + scope + " ORDER BY updated_at ASC LIMIT " + str(MAX_FOLLOWUPS),
            (queue_cutoff, *params),
        ).fetchall()
        for row in rows:
            minutes = _age_minutes(row["updated_at"], now)
            state = str(row["state"])
            if minutes is None:
                continue
            add("delivery", "high" if state == "failed" else "warning",
                "Publication delivery " + ("failed" if state == "failed" else "overdue"),
                "Story #" + str(int(row["item_id"])) + " · " + state + " · " + str(minutes)
                + " min since last recorded delivery change. Verify the public URL before retrying.",
                item_id=int(row["item_id"]), at=row["updated_at"])

    corrections_recorded = table_exists(database, "ph_editorial_updates")
    corrections_cutoff = (now - timedelta(hours=6)).isoformat()
    if corrections_recorded:
        rows = database.conn.execute(
            "SELECT id,item_id,kind,created_at FROM ph_editorial_updates "
            "WHERE status='pending' AND created_at <= " + p
            + scope + " ORDER BY created_at ASC LIMIT " + str(MAX_FOLLOWUPS),
            (corrections_cutoff, *params),
        ).fetchall()
        for row in rows:
            minutes = _age_minutes(row["created_at"], now)
            if minutes is None:
                continue
            kind = str(row["kind"])
            if kind != "correction" and minutes < 24 * 60:
                continue
            item_id = int(row["item_id"])
            followup = {
                "id": int(row["id"]), "item_id": item_id, "kind": kind,
                "created_at": row["created_at"], "age_minutes": minutes,
            }
            followups.append(followup)
            add("correction", "high" if kind == "correction" else "warning",
                "Correction awaiting review" if kind == "correction" else "Editorial update awaiting review",
                "Story #" + str(item_id) + " · proposed " + str(minutes)
                + " minutes ago. Review original evidence and approve or reject manually.",
                item_id=item_id, at=row["created_at"])

    trend = _daily_series(database, where=where, params=params, now=now)
    missing = []
    if not trend["collector_history_available"]:
        missing.append("collector history")
    if not delivery_recorded:
        missing.append("delivery queue")
    if not corrections_recorded:
        missing.append("editorial updates")
    state = ("attention" if alerts else "partial" if missing or not trend["recorded_outcomes"]
             else "no_current_alerts")
    return {
        "scope": "database", "status": state, "alerts": alerts,
        "alert_count_shown": len(alerts), "alert_limit": MAX_ALERTS,
        "followups": followups[:MAX_FOLLOWUPS], "trend": trend,
        "availability": {
            "collector_history": trend["collector_history_available"],
            "delivery": delivery_recorded, "corrections": corrections_recorded,
        },
        "note": (
            "Alerts are evaluated from saved evidence whenever an authorized admin "
            "loads this view, not pushed as phone notifications. "
            "No alert automatically publishes, corrects or retries a story. "
            "Lists are capped; check the phone for complete records."
        ),
    }
