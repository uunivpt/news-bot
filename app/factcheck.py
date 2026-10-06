from collections import defaultdict

from .database import NewsDatabase
from .phase_system import ensure_schema, run as agent_run


def run_cross_source_check(db: NewsDatabase, limit: int = 100) -> int:
    """Conservative fact-check precheck: never marks a claim as verified.
    It only flags whether similar titles appear across multiple sources."""
    ensure_schema(db)
    rows = db.latest(limit=limit, status="all")
    groups = defaultdict(list)
    for row in rows:
        key = row["title_hash"] if isinstance(row, dict) else row["title_hash"]
        groups[key].append(row)

    checked = 0
    with agent_run(db, "factcheck", "cross_source_check", metadata={"limit": limit}):
     for rows_for_title in groups.values():
      sources = {r["source_name"] for r in rows_for_title}
      note = f"Found {len(sources)} source(s) with the same title fingerprint. Human/source verification still required."
      status = "cross_source" if len(sources) >= 2 else "needs_review"
      for row in rows_for_title:
       item_id = row["id"]
       current = str(row["fact_check_status"] or "").strip().lower()
       # Never overwrite a human-reviewed/approved decision with an automated precheck.
       if current in {"reviewed", "approved"}:
        continue
       db.update(item_id, fact_check_status=status, fact_check_notes=note)
       checked += 1
    return checked
