"""DB-independent emergency public feed from enabled, attribution-safe sources.

Writes public/news-data.json; GitHub Actions deploys it only after valid new stories.
No scraper bypasses, fabricated articles, unlicensed image copies, or DB credentials.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.public_archive import retain_public_records
from app.collector import load_sources
from app.news_api import collect_newsdata
from app.category_routing import normalize_category
from app.rss import collect_rss
from app.source_text import source_text
from app.normalize import normalize_url

OUTPUT = Path("public/news-data.json")
MOBILE_REVIEWED = Path("public/mobile-reviewed.json")
MAX_STORIES = 140
MAX_AGE = timedelta(hours=48)
ARCHIVE_AGE = timedelta(days=5)
log = logging.getLogger("offline_feed")


def parse_date(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def clean_text(value):
    return source_text(value)


def valid_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


def public_story(item, now):
    title = clean_text(item.title)
    summary = clean_text(item.summary)
    published = parse_date(item.published_at)
    if not valid_url(item.url) or not published:
        return None
    if published > now + timedelta(minutes=30) or now - published > MAX_AGE:
        return None
    if not 20 <= len(title) <= 210 or not 55 <= len(summary) <= 4200:
        return None
    # End public excerpts at a real sentence boundary; no chopped news copy.
    excerpt = summary[:460]
    endings = list(re.finditer(r"[.!?](?=\s|$)", excerpt))
    if endings:
        summary = excerpt[:endings[-1].end()].strip()
    elif len(summary) > 460:
        return None
    elif not summary.endswith((".", "!", "?")) and item.source_type != "rss":
        return None
    # RSS standfirsts often intentionally omit a final full stop. Preserve the
    # entire short source excerpt rather than discard today's feed as a fragment.
    # Explicitly clipped excerpts still stay out of the public feed.
    if summary.endswith(("...", "…", "[read more]", "[Read more]")):
        return None
    if len(summary) < 55:
        return None
    source = clean_text(item.source_name)[:90] or "Original source"
    story_id = 1000000000 + int(hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:11], 16)
    stamp = published.isoformat()
    return {
        "id": story_id,
        "source_name": source,
        "source_type": str(item.source_type or "rss"),
        "title": title,
        "url": item.url,
        "published_at": stamp,
        "published_at_site": stamp,
        "summary": summary,
        "bot_summary": summary,
        "bot_article": "",
        "category": normalize_category(item.category or "india", title, summary),
        "image_url": None,
        "public_source": True,
    }


def build(current, collected, now):
    indexed = {}
    fresh = 0
    for row in current:
        if not isinstance(row, dict) or not valid_url(row.get("url")):
            continue
        published = parse_date(row.get("published_at") or row.get("published_at_site"))
        if not published or published > now + timedelta(minutes=30) or now - published > ARCHIVE_AGE:
            continue
        key = str(row["url"]).strip()
        row = dict(row)
        repaired = False
        for field in ("summary", "bot_summary"):
            if row.get(field):
                cleaned = clean_text(row[field])
                if cleaned != row[field]:
                    row[field] = cleaned
                    repaired = True
        if repaired:
            fresh += 1
        row["category"] = normalize_category(row.get("category"), row.get("title"), row.get("summary") or row.get("bot_summary"))
        indexed[key] = row

    for item in collected:
        story = public_story(item, now)
        if not story:
            continue
        key = story["url"]
        if key in indexed:
            # Repair older incomplete emergency excerpts without duplicating stories.
            old = indexed[key]
            if old.get("source_type") == "newsdata" and old.get("summary") != story["summary"]:
                indexed[key] = story
                fresh += 1
            continue
        indexed[key] = story
        fresh += 1

    result = sorted(
        indexed.values(),
        key=lambda x: parse_date(x.get("published_at") or x.get("published_at_site")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:MAX_STORIES]
    return result, fresh


def mobile_reviewed_story(row, now):
    """Validate phone-exported records again before any public exposure."""
    if not isinstance(row, dict):
        return None
    if row.get("status") != "published" or row.get("public_source") is not True:
        return None
    if not row.get("approved_at") or str(row.get("fact_check_status") or "").lower() not in {"passed", "verified", "approved"}:
        return None
    url = str(row.get("url") or "")
    if not valid_url(url):
        return None
    try:
        story_id = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    if not 0 < story_id < 2**53:
        return None
    title = clean_text(row.get("title"))
    source = clean_text(row.get("source_name"))
    summary = clean_text(row.get("bot_summary") or row.get("summary"))
    published = parse_date(row.get("published_at_site") or row.get("published_at"))
    if not (title and source and 20 <= len(title) <= 210 and 55 <= len(summary) <= 4200 and published):
        return None
    if published > now + timedelta(minutes=30) or now - published > ARCHIVE_AGE:
        return None
    stamp = published.isoformat()
    return {
        "id": story_id,
        "title": title,
        "url": url,
        "source_name": source[:90],
        "source_type": str(row.get("source_type") or "rss")[:30],
        "published_at": str(row.get("published_at") or stamp),
        "published_at_site": stamp,
        "summary": summary,
        "bot_summary": summary,
        "bot_article": "",
        "category": normalize_category(row.get("category") or "india", title, summary),
        "image_url": None,
        "public_source": True,
        "status": "published",
    }


def merge_mobile_reviewed(current, incoming, now):
    """Merge verified phone exports without deleting or renumbering public stories."""
    indexed = {normalize_url(row["url"]): dict(row) for row in current
               if isinstance(row, dict) and valid_url(row.get("url"))}
    identities = {str(row.get("id")): key for key, row in indexed.items()}
    changed = 0
    for raw in incoming:
        story = mobile_reviewed_story(raw, now)
        if story is None:
            continue
        key = normalize_url(story["url"])
        old = indexed.get(key)
        if old:
            # Preserve published URL identity and existing article links.
            story["id"] = old["id"]
        elif identities.get(str(story["id"]), key) != key:
            log.warning("Mobile feed ID conflict; skipping story %s", story["id"])
            continue
        if old != story:
            indexed[key] = story
            changed += 1
        identities[str(story["id"])] = key
    result = sorted(indexed.values(),
                    key=lambda row: parse_date(row.get("published_at_site") or row.get("published_at"))
                    or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True)[:MAX_STORIES]
    return result, changed


def load_mobile_reviewed(path=MOBILE_REVIEWED):
    if not path.exists():
        return []
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Mobile reviewed feed too large")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Invalid reviewed feed format")
        return rows
    except (ValueError, OSError) as exc:
        raise RuntimeError("Invalid reviewed feed; existing snapshot preserved") from exc

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sources = load_sources()
    now = datetime.now(timezone.utc)
    collected = []
    good = 0
    failed = []
    # Only providers whose APIs/feed metadata are explicitly enabled.
    # Private sites and Telegram scraping are intentionally excluded.
    for source_type, fn in (("newsdata", collect_newsdata), ("rss", collect_rss)):
        for source in sources.get(source_type, []):
            if not source.get("enabled", True) or not source.get("public_source", False):
                continue
            try:
                items = fn(source)
                collected.extend(items)
                good += 1
                log.info("%s: %s source items", source.get("name"), len(items))
            except Exception as exc:
                failed.append(str(source.get("name") or source_type))
                log.warning("Feed source unavailable: %s (%s)", source.get("name"), type(exc).__name__)

    current = []
    if OUTPUT.exists():
        try:
            value = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(value, list):
                current = value
        except (OSError, ValueError) as exc:
            log.warning("Ignoring corrupt local snapshot (%s)", type(exc).__name__)

    mobile = load_mobile_reviewed()
    if not good and not any(mobile_reviewed_story(row, now) for row in mobile):
        log.error("All offline feed sources failed; preserving last published snapshot")
        raise SystemExit(1)

    result, fresh = build(current, collected, now)
    result, mobile_changes = merge_mobile_reviewed(result, mobile, now)
    fresh += mobile_changes
    retain_public_records(current + result)
    newest = max((parse_date(row.get("published_at")) for row in result), default=None)
    age_minutes = max(0, int((now - newest).total_seconds() / 60)) if newest else None
    log.info("Feed freshness: newest=%s age_minutes=%s; sources_ok=%s sources_failed=%s", newest, age_minutes, good, len(failed))
    report_path = os.getenv("GITHUB_STEP_SUMMARY")
    if report_path:
        with open(report_path, "a", encoding="utf-8") as report:
            report.write(f"\n### Public feed freshness\nSuccessful sources: {good}; failed sources: {len(failed)}; new/updated stories: {fresh}.\n\nNewest source story: {newest.isoformat() if newest else 'none'}; age: {age_minutes} minutes.\n")
    if age_minutes is None or age_minutes > 180:
        log.warning("No source story within the last three hours; check provider delay and source availability")
        if os.getenv("GITHUB_ACTIONS"):
            print("::warning::Public feed is stale: no eligible source story within the last three hours.")
    # Apply editorial recategorization even when the source offers no fresh item.
    changed_categories = any(
        isinstance(row, dict)
        and normalize_category(row.get("category"), row.get("title"), row.get("summary") or row.get("bot_summary")) != str(row.get("category") or "india").strip().lower()
        for row in current
    )
    if fresh == 0 and not changed_categories:
        log.info("No newly eligible stories or editorial changes; public snapshot unchanged")
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    log.info("Published %s new source-linked articles to emergency snapshot (%s retained)", fresh, len(result))


if __name__ == "__main__":
    main()
