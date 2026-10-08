"""Restore source-linked public news from the committed snapshot into a NEW, EMPTY database.

Dry run (no DB access): python scripts/restore_public_snapshot.py
Restore after safely setting the *new* DATABASE_URL:
    python scripts/restore_public_snapshot.py --apply
Resume a verified partial restore:
    python scripts/restore_public_snapshot.py --apply --resume

Does NOT touch/delete the old Neon project, carry passwords/admins/subscribers,
or import unverified Telegram reposts. Requires a new empty database on --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from app.database import CATEGORIES, NewsDatabase
from app.normalize import fingerprint, normalize_url

DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "public" / "news-data.json"
MAX_STORIES = 2000


def select_stories(records):
    """Use only valid public, source-linked reports, deduplicated by URL."""
    if not isinstance(records, list):
        raise ValueError("Expected a JSON list of public news stories")
    if len(records) > MAX_STORIES:
        raise ValueError("Snapshot unexpectedly large; review manually before importing")
    stories = []
    seen_ids, seen_urls = set(), set()
    for raw in records:
        if not isinstance(raw, dict) or raw.get("public_source") is not True:
            continue
        if str(raw.get("source_type") or "").lower() == "telegram":
            continue
        try:
            item_id = int(raw.get("id"))
        except (ValueError, TypeError):
            continue
        title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()[:300]
        source = str(raw.get("source_name") or "").strip()[:180]
        url = str(raw.get("url") or "").strip()
        host = urlsplit(url)
        if (item_id <= 0 or item_id in seen_ids or len(title.split()) < 5
                or not source or host.scheme != "https" or not host.hostname):
            continue
        normalized = normalize_url(url)
        if normalized in seen_urls:
            continue
        seen_ids.add(item_id)
        seen_urls.add(normalized)
        stories.append({
            "id": item_id,
            "source_name": source,
            "source_type": str(raw.get("source_type") or "public_snapshot")[:80],
            "title": title,
            "url": url,
            "normalized_url": normalized,
            "published_at": str(raw.get("published_at") or "")[:80] or None,
            "published_at_site": str(raw.get("published_at_site") or raw.get("published_at") or "")[:80] or None,
            "summary": str(raw.get("summary") or "")[:2500],
            "bot_summary": str(raw.get("bot_summary") or raw.get("summary") or "")[:2500],
            "bot_article": str(raw.get("bot_article") or "")[:15000],
            "category": raw.get("category") if raw.get("category") in CATEGORIES else "general",
        })
    return stories


def load_snapshot(path=DEFAULT_SNAPSHOT):
    return select_stories(json.loads(Path(path).read_text(encoding="utf-8")))


def restore(database, stories, resume=False):
    """Restore without replacing records; explicit resume validates every existing story."""
    if not stories:
        raise ValueError("No eligible public stories in snapshot")
    if resume:
        expected = {int(row["id"]): row["normalized_url"] for row in stories}
        current = database.conn.execute("SELECT id, normalized_url FROM news_items").fetchall()
        for record in current:
            item_id = int(record["id"])
            if item_id not in expected or record["normalized_url"] != expected[item_id]:
                raise RuntimeError("Destination has unrelated news. Refusing to mix projects.")
    elif database.count() != 0:
        raise RuntimeError("Destination contains news already. Refusing to overwrite or mix projects.")
    ph = "%s" if database._postgres else "?"
    columns = (
        "id", "source_name", "source_type", "title", "url", "normalized_url",
        "published_at", "published_at_site", "summary", "bot_summary",
        "bot_article", "collected_at", "url_hash", "title_hash",
        "category", "status", "public_source",
    )
    sql = (f"INSERT INTO news_items ({','.join(columns)}) VALUES "
           f"({','.join([ph] * len(columns))}) ON CONFLICT DO NOTHING")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    transaction = database.conn.transaction() if database._postgres else database.conn
    with transaction:
        inserted = 0
        for row in stories:
            url_hash, title_hash = fingerprint(row["normalized_url"], row["title"])
            values = [
                row["id"], row["source_name"], row["source_type"], row["title"],
                row["url"], row["normalized_url"], row["published_at"],
                row["published_at_site"], row["summary"], row["bot_summary"],
                row["bot_article"], now, url_hash, title_hash,
                row["category"], "published", 1,
            ]
            inserted += database.conn.execute(sql, values).rowcount
        if database._postgres:
            # Explicitly restored IDs must not collide with future BIGSERIAL IDs.
            database.conn.execute(
                "SELECT setval(pg_get_serial_sequence('news_items','id'), "
                "(SELECT MAX(id) FROM news_items), true)"
            )
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Recover public news without changing the original database")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--apply", action="store_true",
                        help="Apply to an explicitly configured NEW database only")
    parser.add_argument("--resume", action="store_true",
                        help="Resume a partial restore only if all existing news matches the snapshot")
    args = parser.parse_args()
    stories = load_snapshot(args.snapshot)
    print(f"Source-linked, non-Telegram public stories ready for restoration: {len(stories)}")
    if not args.apply:
        print("DRY RUN ONLY. No database was contacted or changed.")
        return
    if not os.getenv("DATABASE_URL", "").startswith(("postgresql://", "postgres://")):
        raise SystemExit("DATABASE_URL must be set to a NEW PostgreSQL project (never the old project)")
    database = NewsDatabase()
    try:
        count = restore(database, stories, resume=args.resume)
        print(f"Restored {count} public news stories into the NEW database.")
        print("Subscriber/owner records were NOT migrated. Reconfirm subscriptions separately.")
    finally:
        database.close()


if __name__ == "__main__":
    main()
