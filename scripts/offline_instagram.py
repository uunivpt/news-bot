"""Emergency Instagram worker when primary PostgreSQL is at quota.

Uses source-linked public snapshot stories, the production Remotion Reel,
a source-backed caption, and a Git-tracked publication receipt.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.cloudinary_storage import upload_image, upload_video
from app.meta_instagram import publish_photo, publish_reel
from app.remotion_reel_renderer import render_remotion_reel
from app.editorial_poster import render_editorial_poster, editorial_caption
from app.category_routing import normalize_category
from app.image_acquisition import prepare_story_image
from app.article_fetcher import enrich_source_text
from app.newsroom import process_news
from scripts.offline_snapshot import parse_date, valid_url

FEED = Path("public/news-data.json")
LEDGER = Path("public/instagram-offline-ledger.json")
POSTER_DIR = Path("data/editorial_posters")
COOLDOWN = timedelta(hours=3)
MAX_DAILY_POSTS = 4
INDIA_TZ = ZoneInfo("Asia/Kolkata")
ELIGIBLE_CATEGORIES = ("india", "politics", "business", "world", "technology", "sports", "science", "health", "entertainment")


def choose_story(rows, ledger, now):
    receipts = ledger.get("posts", [])
    seen = {str(row.get("url", "")) for row in receipts if isinstance(row, dict)}
    # Apply the same daily ceiling while the primary database is offline.
    today = now.astimezone(INDIA_TZ).date()
    posted_today = 0
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        stamped = parse_date(receipt.get("published_at"))
        if stamped and stamped.astimezone(INDIA_TZ).date() == today:
            posted_today += 1
    if posted_today >= MAX_DAILY_POSTS:
        return None
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
        if row.get("source_type") not in {"newsdata", "rss"} or not row.get("public_source") or category not in ELIGIBLE_CATEGORIES:
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


def prepare_story(story):
    story = dict(story)
    story["category"] = normalize_category(story.get("category"), story.get("title"), story.get("summary"))
    if len(str(story.get("bot_article") or "").strip()) < 150:
        source = enrich_source_text(story.get("title") or "", story.get("summary") or "", story.get("url") or "")
        processed = process_news(story.get("title") or "", source.get("text") or "", story["category"])
        if not processed or len(processed.get("article") or "") < 150:
            return None
        story["bot_article"] = processed["article"]
        story["bot_summary"] = processed["summary"]
    return story


def publish_story(story):
    identifier = str(story["id"])
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    if os.getenv("INSTAGRAM_POST_FORMAT", "reel").lower() == "reel":
        from scripts.auto_publish import audio_path
        music = audio_path()
        if not music:
            raise RuntimeError("News Pulse audio unavailable")
        reel_story = dict(story)
        reel_story["image_url"] = story.get("image_local_path") or story.get("image_url")
        reel = render_remotion_reel(reel_story, str(POSTER_DIR / ("offline-" + identifier + ".mp4")), audio_path=music)
        import hashlib
        digest = hashlib.sha256(Path(reel).read_bytes()).hexdigest()[:12]
        public_url = upload_video(reel, public_id="politicshub/offline-reel-" + identifier + "-" + digest)
        if not public_url:
            raise RuntimeError("No public Reel video URL returned")
        return publish_reel(public_url, editorial_caption(story)), "reel", public_url
    poster = render_editorial_poster(story, POSTER_DIR / ("offline-" + identifier + ".jpg"))
    public_url = upload_image(str(poster), public_id="politicshub/offline-editorial-" + identifier)
    return publish_photo(public_url, editorial_caption(story)), "editorial_4x5", public_url


def main():
    if not FEED.exists():
        raise RuntimeError("No public source-linked snapshot is available yet")
    rows = json.loads(FEED.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"posts": []}
    if not isinstance(rows, list) or not isinstance(ledger, dict):
        raise RuntimeError("Invalid Instagram fallback data")
    now = datetime.now(timezone.utc)
    # A thin newest story must not permanently starve every later candidate.
    story = None
    candidates = rows
    for _ in range(10):
        candidate = choose_story(candidates, ledger, now)
        if not candidate:
            break
        story = prepare_story(candidate)
        if story:
            break
        print("Skipping thin source excerpt:", candidate["id"])
        candidates = [row for row in candidates if row.get("url") != candidate["url"]]
    if not story:
        print("No eligible source-backed story or 30-minute publication interval remains.")
        return

    required = ("META_ACCESS_TOKEN", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET")
    if any(not os.getenv(key) for key in required):
        raise RuntimeError("Instagram fallback missing configured Meta/Cloudinary secrets")

    identifier = str(story["id"])
    try:
        image_meta = prepare_story_image(story, output_dir=POSTER_DIR / "licensed")
        if image_meta:
            story.update(image_meta)
    except Exception as exc:
        print("Licensed image unavailable; using original editorial typographic design:", type(exc).__name__)
    result, post_format, public_url = publish_story(story)
    media_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    if not media_id:
        raise RuntimeError("Meta did not confirm a published Instagram media ID")

    posted_at = datetime.now(timezone.utc).isoformat()
    posts = ledger.get("posts") or []
    posts.insert(0, {"id": identifier, "url": story["url"], "media_id": media_id, "published_at": posted_at, "format": post_format, "media_url": public_url})
    ledger["posts"] = posts[:150]
    ledger["last_published_at"] = posted_at
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Instagram fallback published", post_format, identifier, "with Meta media confirmation.")


if __name__ == "__main__":
    main()
