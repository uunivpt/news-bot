"""Emergency Instagram worker when primary PostgreSQL is at quota.

Uses source-linked public snapshot stories. Every category gets the premium
4:5 editorial photo-post, a substantive source-backed caption, and a Git-tracked
publication receipt. One post per two hours outside explicitly requested batches.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.cloudinary_storage import upload_image
from app.meta_instagram import publish_photo
from app.editorial_poster import render_editorial_poster, editorial_caption
from app.category_routing import normalize_category
from app.image_acquisition import prepare_story_image
from app.article_fetcher import enrich_source_text
from app.newsroom import process_news
from scripts.offline_snapshot import parse_date, valid_url

FEED = Path("public/news-data.json")
LEDGER = Path("public/instagram-offline-ledger.json")
POSTER_DIR = Path("data/editorial_posters")
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
    story = dict(story)
    story["category"] = normalize_category(story.get("category"), story.get("title"), story.get("summary"))
    if len(str(story.get("bot_article") or "").strip()) < 150:
        source = enrich_source_text(story.get("title") or "", story.get("summary") or "", story.get("url") or "")
        processed = process_news(story.get("title") or "", source.get("text") or "", story["category"])
        if not processed or len(processed.get("article") or "") < 150:
            print("Skipping thin source excerpt; substantive source-backed article required.")
            return
        story["bot_article"] = processed["article"]
        story["bot_summary"] = processed["summary"]
    try:
        image_meta = prepare_story_image(story, output_dir=POSTER_DIR / "licensed")
        if image_meta:
            story.update(image_meta)
    except Exception as exc:
        print("Licensed image unavailable; using original editorial typographic design:", type(exc).__name__)
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    poster = render_editorial_poster(story, POSTER_DIR / ("offline-" + identifier + ".jpg"))
    public_url = upload_image(str(poster), public_id="politicshub/offline-editorial-" + identifier)
    print("Publishing premium source-backed 4:5 editorial image for news item", identifier)
    result = publish_photo(public_url, editorial_caption(story))
    media_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    if not media_id:
        raise RuntimeError("Meta did not confirm a published Instagram media ID")

    posted_at = datetime.now(timezone.utc).isoformat()
    posts = ledger.get("posts") or []
    posts.insert(0, {"id": identifier, "url": story["url"], "media_id": media_id, "published_at": posted_at})
    ledger["posts"] = posts[:150]
    ledger["last_published_at"] = posted_at
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Instagram fallback published premium editorial photo", identifier, "with Meta media confirmation.")


if __name__ == "__main__":
    main()
