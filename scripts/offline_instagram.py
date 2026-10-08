"""Emergency Instagram worker when primary PostgreSQL is at quota.

Uses only newly syndicated, source-linked public snapshot stories.
A Git-tracked receipt prevents scheduled duplicate posts. One post / two hours.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.cloudinary_storage import upload_video
from app.meta_instagram import publish_reel
from app.remotion_reel_renderer import render_remotion_reel
from scripts.auto_publish import audio_path
from scripts.offline_snapshot import parse_date, valid_url

FEED = Path("public/news-data.json")
LEDGER = Path("public/instagram-offline-ledger.json")
VIDEO_DIR = Path("data/media")
COOLDOWN = timedelta(hours=2)
ELIGIBLE_CATEGORIES = ("india", "politics", "business", "world", "technology", "entertainment")


def choose_story(rows, ledger, now):
    receipts = ledger.get("posts", [])
    seen = {str(row.get("url", "")) for row in receipts if isinstance(row, dict)}
    last = parse_date(ledger.get("last_published_at"))
    if last and now - last < COOLDOWN:
        return None
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        stamp = parse_date(row.get("published_at"))
        summary = str(row.get("summary") or row.get("bot_summary") or "").strip()
        category = str(row.get("category") or "").strip().lower()
        if not valid_url(url) or url in seen:
            continue
        if row.get("source_type") != "newsdata" or category not in ELIGIBLE_CATEGORIES:
            continue
        if not stamp or stamp > now or now - stamp > timedelta(hours=26):
            continue
        if len(str(row.get("title") or "")) < 25 or len(summary) < 95:
            continue
        if re.search(r"(\.\.\.|…|read more)\s*$", summary, flags=re.I):
            continue
        candidates.append((ELIGIBLE_CATEGORIES.index(category), -stamp.timestamp(), row))
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2] if candidates else None


def main():
    if not FEED.exists():
        raise RuntimeError("No public source-linked snapshot is available yet")
    rows = json.loads(FEED.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"posts": []}
    if not isinstance(rows, list) or not isinstance(ledger, dict):
        raise RuntimeError("Invalid Instagram fallback data")
    now = datetime.now(timezone.utc)
    story = choose_story(rows, ledger, now)
    if not story:
        print("No eligible unposted India-related story or 2-hour safety window remains.")
        return

    required = ("META_ACCESS_TOKEN", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET")
    if any(not os.getenv(key) for key in required):
        raise RuntimeError("Instagram fallback missing configured Meta/Cloudinary secrets")

    identifier = str(story["id"])
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    output = VIDEO_DIR / ("offline-news-" + identifier + ".mp4")
    music = audio_path()
    if not music:
        raise RuntimeError("PoliticsHub licensed news audio is not available")

    print("Rendering source-linked emergency Reel for news item", identifier)
    render_remotion_reel(story, str(output), audio_path=music)
    public_url = upload_video(str(output), public_id="politicshub_offline_" + identifier)
    if not public_url:
        raise RuntimeError("Could not upload emergency Reel to public storage")

    text = str(story.get("summary") or "").strip()
    title = str(story.get("title") or "").strip()
    caption = (
        title + "\n\n" + text + "\n\n"
        + "Source: " + str(story.get("source_name") or "Original report") + "\n"
        + "Read the source: " + str(story["url"])
        + "\n\n#PoliticsHub #IndiaNews #NewsUpdate"
    )
    result = publish_reel(public_url, caption)
    media_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    if not media_id:
        raise RuntimeError("Meta did not confirm a published Instagram media ID")

    posted_at = datetime.now(timezone.utc).isoformat()
    posts = ledger.get("posts") or []
    posts.insert(0, {"id": identifier, "url": story["url"], "media_id": media_id, "published_at": posted_at})
    ledger["posts"] = posts[:150]
    ledger["last_published_at"] = posted_at
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Instagram fallback published news item", identifier, "with Meta media confirmation.")


if __name__ == "__main__":
    main()
