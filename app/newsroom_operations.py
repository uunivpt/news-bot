"""Read-only, source-backed newsroom operations metrics.

Every number comes from actual collection checks or committed database records.
Do not create tables, repair sources, start workers, or claim phone health from
a cached public snapshot during an admin GET.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median

from .editorial_access import table_exists
from .source_inventory import _stamp

MAX_LATENCY_SAMPLE = 300


def source_triage(inventory):
    scope = inventory.get("scope", "unavailable")
    if scope != "database":
        return {
            "scope": scope, "status": "unavailable", "observed": None,
            "attention": None, "counts": None, "incidents": [],
            "note": "Private phone collection checks cannot be inferred from a GitHub snapshot.",
        }

    counts = {name: 0 for name in (
        "healthy", "failed", "stale", "checking", "awaiting_collection",
        "not_configured", "unknown", "disabled", "external_pipeline"
    )}
    incidents = []
    observed = 0
    tracked = 0
    for row in inventory.get("items") or []:
        state = str(row.get("collection_status") or "unknown").lower()
        if row.get("configured") is False:
            continue
        if row.get("enabled") is False:
            state = "disabled"
        if state not in counts:
            state = "unknown"
        counts[state] += 1
        if state in {"disabled", "external_pipeline"}:
            continue
        tracked += 1
        if state in {"healthy", "failed", "stale", "checking"}:
            observed += 1
        if state in {"failed", "stale", "not_configured"}:
            incidents.append({
                "name": row.get("name"), "state": state,
                "last_attempt_at": row.get("last_attempt_at"),
                "last_success_at": row.get("last_success_at"),
                "error_class": row.get("last_error") if state == "failed" else None,
            })
    priority = {"failed": 0, "stale": 1, "not_configured": 2}
    incidents.sort(key=lambda item: (priority[item["state"]], str(item["name"] or "").casefold()))
    # An empty ph_source_collection table is no evidence of healthy publishers.
    status = ("not_configured" if not tracked else
              "awaiting_checks" if not observed else
              "attention" if counts["failed"] or counts["stale"] or counts["not_configured"] else
              "checks_recorded")
    return {
        "scope": scope, "status": status, "tracked": tracked, "observed": observed,
        "attention": len(incidents), "counts": counts, "incidents": incidents[:30],
        "note": ("Statuses describe the latest recorded phone collector checks, not "
                 "independent verification of a publisher or the public website."),
    }


def _lag_minutes(collected, published, now):
    start = _stamp(collected)
    end = _stamp(published)
    if not start or not end:
        return None
    if start > now + timedelta(minutes=30) or end > now + timedelta(minutes=30):
        return None
    elapsed = (end - start).total_seconds() / 60
    return round(elapsed, 2) if 0 <= elapsed <= 60 * 24 * 14 else None


def publication_operations(database, *, where="", params=(), now=None):
    """Private authorized summary; optional tables are read, never initialized."""
    now = now or datetime.now(timezone.utc)
    clauses = ("status='published' AND NULLIF(published_at_site,'') IS NOT NULL"
               " AND NULLIF(collected_at,'') IS NOT NULL")
    if where:
        # scope_sql already supplies a parameterized restriction.
        clauses += " AND " + where.lstrip().removeprefix("WHERE ").strip()
    rows = database.conn.execute(
        "SELECT collected_at,published_at_site FROM news_items WHERE " + clauses +
        " ORDER BY id DESC LIMIT " + str(MAX_LATENCY_SAMPLE), tuple(params)
    ).fetchall()
    durations = sorted(value for row in rows
                       if (value := _lag_minutes(row["collected_at"],
                                                  row["published_at_site"], now)) is not None)
    latency = {
        "sample_limit": MAX_LATENCY_SAMPLE, "evaluated": len(rows),
        "measured": len(durations), "median_minutes": round(median(durations), 1) if durations else None,
        "p95_minutes": durations[max(0, ceil(0.95 * len(durations)) - 1)] if durations else None,
        "under_60m": sum(x <= 60 for x in durations) if durations else None,
        "definition": "Elapsed time from a story's recorded collection to its recorded site publication; NOT external website visibility.",
    }

    def scoped_counts(table, field):
        if not table_exists(database, table):
            return {"recorded": False, "counts": None}
        # ph_public_delivery / ph_editorial_updates are keyed by item_id.
        scoped = "item_id IN (SELECT id FROM news_items"
        if where:
            scoped += " WHERE " + where.lstrip().removeprefix("WHERE ").strip()
        scoped += ")"
        result = database.conn.execute(
            f"SELECT {field} AS label,COUNT(*) AS amount FROM {table} "
            f"WHERE {scoped} GROUP BY {field}", tuple(params)
        ).fetchall()
        return {
            "recorded": True,
            "counts": {str(r["label"]): int(r["amount"]) for r in result},
        }

    delivery = scoped_counts("ph_public_delivery", "state")
    corrections = scoped_counts("ph_editorial_updates", "status")
    return {
        "scope": "database", "latency": latency,
        "delivery": delivery, "corrections": corrections,
        "note": ("Delivery queue state is not proof of anonymous website visibility. "
                 "Signed publication receipts are checked separately."),
    }
