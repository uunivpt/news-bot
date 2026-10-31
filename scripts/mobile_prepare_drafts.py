"""Prepare a bounded review queue on the phone; never approve or publish news.

Requires a local PostgreSQL worker credential in PGPASSFILE. Default is
read-only dry run. --write saves only bot_article and (if missing) bot_summary.
Do not run this against Neon or a production database.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.article_fetcher import enrich_source_text
from app.newsroom import process_news, validate_news_copy
from app.phase_system import quality_gate

LOCAL_DATABASE = "postgresql://politicshub_collector@127.0.0.1:5432/politicshub?sslmode=disable"
CURSOR_FILE = Path.home() / ".local/share/politicshub/draft-review-cursor"


def pending_without_drafts(db, limit: int, cursor: int | None = None):
    """Walk the whole pending queue instead of retrying the same five IDs.

    All operations are read-only; the local cursor is advanced only by main()
    after an entire draft batch finishes without an exception.
    """
    def query(bound):
        return [dict(row) for row in db.conn.execute(
            """SELECT * FROM news_items
               WHERE status = %s
                 AND COALESCE(BTRIM(bot_article), '') = ''
                 AND id < %s
               ORDER BY id DESC LIMIT %s""",
            ("pending", bound, limit),
        ).fetchall()]

    rows = query(cursor if cursor is not None and cursor > 0 else 2**63 - 1)
    if not rows and cursor is not None:
        rows = query(2**63 - 1)
    return rows


def prepare(db, limit=5, write=False, rows=None):
    if rows is None:
        # Preserve a tiny test/interactive API; scheduled work passes a
        # rotating batch from pending_without_drafts() explicitly.
        rows = db.latest(limit, status="pending")
    rows = [dict(row) for row in rows]
    stats = {"examined": 0, "ready": 0, "saved": 0, "held": 0}
    for row in rows:
        stats["examined"] += 1
        item_id = int(row["id"])
        if (row.get("bot_article") or "").strip():
            print(f"SKIP {item_id}: draft already exists")
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "")
        source = enrich_source_text(title, row.get("summary") or "", url)
        text = str(source.get("text") or "")
        result = process_news(title, text, row.get("category") or "general")
        if not result:
            stats["held"] += 1
            print(f"HOLD {item_id}: insufficient reliable source material")
            continue

        article = result.get("article") or ""
        summary = result.get("summary") or ""
        copy = validate_news_copy(result.get("headline") or title, summary, article)
        quality = quality_gate(title, summary, article)
        if not copy["passed"] or not quality["passed"]:
            stats["held"] += 1
            print(f"HOLD {item_id}: draft QA rejected")
            continue

        stats["ready"] += 1
        if not write:
            print(f"PREVIEW {item_id}: draft={len(article)} characters; no writes")
            continue
        # Prepared copy remains unpublished and unverified. No status,
        # approval, fact check, original headline or source metadata changes.
        fields = {"bot_article": article}
        if not (row.get("bot_summary") or "").strip():
            fields["bot_summary"] = summary
        db.update(item_id, **fields)
        stats["saved"] += 1
        print(f"DRAFT SAVED {item_id}: pending editorial review")
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--write", action="store_true",
                        help="Save draft fields only; never approve/publish")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("--limit must be between 1 and 10")

    # Refuse remote database credentials or an accidental SQLite fallback.
    if os.environ.get("DATABASE_3URL") or os.environ.get("DATABASE_URL"):
        raise SystemExit("STOP: Unset remote DATABASE_3URL/DATABASE_URL first")
    credentials = Path.home() / ".politicshub-worker.pgpass"
    if not credentials.is_file():
        raise SystemExit("STOP: Local PostgreSQL credential file missing")
    os.environ["PGPASSFILE"] = str(credentials)

    from app.database import NewsDatabase

    db = NewsDatabase(database_url=LOCAL_DATABASE, initialize_schema=False)
    try:
        if not db._postgres:
            raise RuntimeError("STOP: PostgreSQL connection required")
        try:
            cursor = int(CURSOR_FILE.read_text().strip())
        except (OSError, ValueError):
            cursor = None
        rows = pending_without_drafts(db, args.limit, cursor)
        data = prepare(db, args.limit, args.write, rows=rows)
        if args.write and rows:
            CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CURSOR_FILE.with_suffix(".tmp")
            tmp.write_text(str(min(int(row["id"]) for row in rows)))
            tmp.replace(CURSOR_FILE)
            print("NEXT BATCH CURSOR:", min(int(row["id"]) for row in rows))
        print("=== MOBILE REVIEW PREPARATION ===")
        for key, value in data.items():
            print(f"{key}: {value}")
        print("PUBLISHED: 0 (unchanged)")
        print("APPROVALS: 0 (unchanged)")
        print("MODE:", "DRAFT-ONLY WRITE" if args.write else "DRY RUN")
    finally:
        db.close()


if __name__ == "__main__":
    main()
