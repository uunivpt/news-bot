"""Build an hourly Hindi headline/link feed independently of the live database.

Source-controlled RSS URLs only. Publish attribution, a brief excerpt and
the original publisher link; do not scrape or republish full articles/images.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collector import load_sources
from app.rss import collect_rss
from scripts.offline_snapshot import clean_text, parse_date, valid_url

OUT = Path("public/hindi-news.json")
AGE = timedelta(hours=72)
MAX_ROWS = 100
HINDI = re.compile(r"[\u0900-\u097f]")
log = logging.getLogger(__name__)


def story_from_rss(item, now):
    title = clean_text(item.title)
    if not 15 <= len(title) <= 220 or not HINDI.search(title) or not valid_url(item.url):
        return None
    stamp = parse_date(item.published_at)
    if stamp is None or stamp > now + timedelta(minutes=30) or now - stamp > AGE:
        return None
    # RSS excerpts only; the full report remains on the source website.
    description = clean_text(item.summary)
    summary = description[:240].rsplit(" ", 1)[0] if len(description) > 240 else description
    if len(description) > 240 and summary:
        summary += "…"
    if not summary:
        summary = title
    return {
        "id": 1_000_000_000_000 + int(hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:11], 16),
        "title": title,
        "summary": summary,
        "bot_summary": summary,
        "source_name": str(item.source_name)[:100],
        "source_type": "rss",
        "url": item.url,
        "published_at": stamp.isoformat(),
        "published_at_site": stamp.isoformat(),
        "category": "hindi",
        "status": "published",
        "public_source": True,
        "image_url": None,
        "bot_article": "",
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    current = []
    if OUT.exists():
        try:
            current = json.loads(OUT.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            log.warning("Previous Hindi feed was invalid; rebuilding")
    by_url = {}
    for record in current if isinstance(current, list) else []:
        if not isinstance(record, dict) or record.get("category") != "hindi":
            continue
        stamp = parse_date(record.get("published_at"))
        if stamp and now - AGE <= stamp <= now + timedelta(minutes=30) and valid_url(record.get("url")):
            by_url[record["url"]] = record
    successful = 0
    for source in load_sources().get("hindi_rss", []):
        if not source.get("enabled", True):
            continue
        try:
            for item in collect_rss(source):
                story = story_from_rss(item, now)
                if story:
                    by_url[story["url"]] = story
            successful += 1
        except Exception as exc:
            log.warning("Hindi source %s unavailable: %s", source.get("name"), type(exc).__name__)
    if successful == 0:
        if by_url:
            log.warning("No Hindi source responded; preserving recent existing stories")
            return
        raise SystemExit("No Hindi sources responded, cannot produce feed")
    rows = sorted(by_url.values(), key=lambda x: x["published_at"], reverse=True)[:MAX_ROWS]
    if not rows:
        log.warning("No current Hindi stories found; preserving existing feed")
        return
    content = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if not OUT.exists() or OUT.read_text(encoding="utf-8") != content:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(content, encoding="utf-8")
    log.info("Hindi source checks successful=%s; stories=%s", successful, len(rows))


if __name__ == "__main__":
    main()
