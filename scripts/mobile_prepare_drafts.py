"""Prepare a bounded review queue on the phone; never approve or publish news.

Requires a local PostgreSQL worker credential in PGPASSFILE. Default is
read-only dry run. --write saves only bot_article and (if missing) bot_summary.
Do not run this against Neon or a production database.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.article_fetcher import enrich_source_text
from app.newsroom import process_news, validate_news_copy
from app.phase_system import quality_gate

LOCAL_DATABASE = "postgresql://politicshub_collector@127.0.0.1:5432/politicshub?sslmode=disable"


def prepare(db, limit=5, write=False):
    rows = [dict(row) for row in db.latest(limit, status="pending")]
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
        data = prepare(db, args.limit, args.write)
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
