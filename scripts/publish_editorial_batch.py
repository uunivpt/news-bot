"""One-time, duplicate-safe PoliticsHub editorial launch batch.

Publish at most five verified articles with premium 1080x1350 imagery.
Never post an unverified source excerpt, scrape a copyrighted photo,
or repeat a story found in recent Instagram captions / the local ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.category_routing import normalize_category
from app.editorial_poster import render_editorial_poster, editorial_caption
from app.cloudinary_storage import upload_image
from app.image_acquisition import prepare_story_image
from app.meta_instagram import _cfg, _resolve_instagram_user, publish_photo, InstagramRateLimitError
from scripts.offline_snapshot import parse_date, valid_url
from scripts.offline_instagram import COOLDOWN, MAX_DAILY_POSTS

FEED = Path("public/news-data.json")
LEDGER = Path("public/instagram-offline-ledger.json")
OUTPUT = Path("data/editorial_batch")
BATCH_SIZE = 1

def select_stories(rows, ledger, now, posted_titles=None, limit=BATCH_SIZE):
    receipts = [p for p in ledger.get("posts", []) if isinstance(p, dict)]
    seen_urls = {str(p.get("url") or "") for p in receipts}
    posted = [date for p in receipts if (date := parse_date(p.get("published_at")))]
    local_date = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    count_today = sum(date.astimezone(ZoneInfo("Asia/Kolkata")).date() == local_date for date in posted)
    if count_today >= MAX_DAILY_POSTS or (posted and now - max(posted) < COOLDOWN):
        return []
    slots_today = MAX_DAILY_POSTS - count_today
    posted_titles = posted_titles or set()
    eligible = []
    for row in rows:
        if not isinstance(row, dict) or row.get("source_type") != "editorial_verified":
            continue
        if not row.get("editorial_pick") or not row.get("public_source"):
            continue
        title = str(row.get("title") or "").strip()
        summary = str(row.get("bot_summary") or row.get("summary") or "").strip()
        article = str(row.get("bot_article") or "").strip()
        url = str(row.get("url") or "")
        published = parse_date(row.get("published_at"))
        if not (valid_url(url) and url not in seen_urls and published):
            continue
        if not (timedelta(0) <= now-published <= timedelta(hours=36)):
            continue
        if len(title.split()) < 5 or len(summary) < 90 or len(article) < 300:
            continue
        if any(title.lower() in caption.lower() for caption in posted_titles):
            continue
        eligible.append(row)
    return eligible[:max(0, min(BATCH_SIZE, limit, slots_today))]

def instagram_recent_captions():
    token, configured, version, host = _cfg()
    if not token:
        raise RuntimeError("Instagram access token is missing")
    base = f"{host}/{version}"
    user = _resolve_instagram_user(base, token, configured)
    response = requests.get(f"{base}/{user}/media",
        params={"fields":"id,caption", "limit":100, "access_token":token}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError("Could not inspect recently published Instagram posts")
    return {str(item.get("caption") or "") for item in payload.get("data", [])}

def confirmed_permalink(media_id):
    try:
        token, _, version, host = _cfg()
        response = requests.get(f"{host}/{version}/{media_id}",
            params={"fields":"permalink", "access_token":token}, timeout=15)
        if response.ok:
            return str(response.json().get("permalink") or "")
    except requests.RequestException:
        pass
    return ""

def main():
    rows = json.loads(FEED.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"posts":[]}
    if not isinstance(rows, list) or not isinstance(ledger, dict):
        raise ValueError("Invalid source feed or Instagram ledger")
    required = ("META_ACCESS_TOKEN", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_UPLOAD_PRESET")
    if any(not os.getenv(name) for name in required):
        raise RuntimeError("Meta/Cloudinary publishing credentials are unavailable")
    # Fail closed if the Instagram account cannot be read: duplicate
    # prevention is more important than forcing an extra live news post.
    captions = instagram_recent_captions()
    stories = select_stories(rows, ledger, datetime.now(timezone.utc), captions)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    for row in stories:
        story = dict(row)
        story["category"] = normalize_category(story.get("category"),story.get("title"),story.get("summary"))
        identifier = str(story["id"])
        try:
            try:
                image_meta = prepare_story_image(story, output_dir=OUTPUT / "licensed")
                if image_meta:
                    story.update(image_meta)
            except Exception as exc:
                print("Licensed source photo unavailable:", identifier, type(exc).__name__)
            poster = render_editorial_poster(story, OUTPUT / (identifier + ".jpg"))
            digest = hashlib.sha256(poster.read_bytes()).hexdigest()[:12]
            public_url = upload_image(str(poster), public_id=f"politicshub/editorial-{identifier}-{digest}")
            result = publish_photo(public_url, editorial_caption(story))
            media_id = str(result.get("id") or "") if isinstance(result, dict) else ""
            if not media_id:
                raise RuntimeError("Meta did not return a confirmed media ID")
            published = datetime.now(timezone.utc).isoformat()
            entry = {"id":identifier,"url":story["url"],"media_id":media_id,"image_url":public_url,
                     "permalink":confirmed_permalink(media_id),"format":"editorial_4x5","published_at":published}
            ledger["posts"] = [entry] + list(ledger.get("posts") or [])[:149]
            ledger["last_published_at"] = published
            LEDGER.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print("CONFIRMED INSTAGRAM EDITORIAL POST", identifier, media_id, entry["permalink"])
            succeeded += 1
        except InstagramRateLimitError as exc:
            print("Instagram rate limit reached: stopping batch without duplicating previous posts", str(exc))
            break
        except Exception as exc:
            print("FAILED INSTAGRAM EDITORIAL POST", identifier, type(exc).__name__, str(exc)[:300])
    print(f"Editorial launch batch: {succeeded} confirmed posts out of {len(stories)} eligible (cap 5)")
    if not succeeded and stories:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
