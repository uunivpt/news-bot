from datetime import datetime, timezone

from .database import NewsDatabase


def publish_approved(db: NewsDatabase, limit: int = 50) -> int:
    """Publishing bot: moves approved items into the site's published feed."""
    rows = db.latest(limit=limit, status="approved")
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        db.update(row["id"], status="published", published_at_site=now)
    return len(rows)
