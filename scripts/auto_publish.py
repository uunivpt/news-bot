from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai import AIService
from app.article_fetcher import enrich_source_text
from app.cloudinary_storage import upload_video
from app.database import NewsDatabase
from app.instagram_graphic import clean_instagram_text, generate_reel_cards
from app.instagram_reel import build_reel
from app.media_storage import download_to, public_video_url
from app.meta_instagram import publish_reel
from app.publish_policy import risk_flags

OUT = Path(os.getenv("MEDIA_OUTPUT_DIR", "data/media"))
OUT.mkdir(parents=True, exist_ok=True)
MAX_INSTAGRAM_ATTEMPTS = 6
STALE_PROCESSING_MINUTES = 20


def _dedupe_caption_text(title: str, text: str | None) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    if text.casefold().startswith(title.casefold()):
        text = text[len(title):].lstrip(" :–—-|\n")
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    unique: list[str] = []
    for part in parts:
        if not any(part.casefold() == old.casefold() for old in unique):
            unique.append(part)
    return " ".join(unique)


def caption(row: dict) -> str:
    title = clean_instagram_text(row.get("title") or "", "")
    text = clean_instagram_text(row.get("ai_summary") or row.get("summary") or "", "")
    text = _dedupe_caption_text(title, text)
    return f"{title}\n\n{text[:700]}\n\npoliticshub.in" if text else f"{title}\n\npoliticshub.in"


def audio_path() -> str | None:
    path = os.getenv("FIXED_AUDIO_PATH", "").strip()
    if path and Path(path).exists():
        return path
    url = os.getenv("FIXED_AUDIO_URL", "").strip()
    if not url.startswith(("https://", "http://")):
        return None
    source = OUT / "fixed_music_source"
    normalized = OUT / "fixed_music_instagram.m4a"
    try:
        download_to(str(source), url)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-t", "18", "-vn", "-ac", "2", "-ar", "48000", "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-movflags", "+faststart", str(normalized)],
            check=True,
            capture_output=True,
            text=True,
        )
        return str(normalized)
    except Exception as exc:
        print("Fixed audio preparation failed:", exc)
        return None


def publish_website_first(db: NewsDatabase, row: dict, now: str) -> dict:
    flags = risk_flags(row["title"], row.get("summary") or row.get("ai_summary") or "")
    review = "needs_review" if flags else "pending"
    db.update(
        int(row["id"]),
        status="published",
        published_at_site=now,
        fact_check_status=review,
        fact_check_notes=", ".join(flags) if flags else None,
    )
    row["status"] = "published"
    return row


def _next_retry(attempts: int) -> str:
    minutes = (5, 15, 30, 60, 120)[min(max(attempts - 1, 0), 4)]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _recover_stale_processing(db: NewsDatabase, now: datetime) -> int:
    rows = [dict(r) for r in db.latest(100, status="published", instagram_status="processing")]
    cutoff = now - timedelta(minutes=STALE_PROCESSING_MINUTES)
    recovered = 0
    for row in rows:
        raw = row.get("instagram_last_attempt_at")
        if not raw:
            continue
        try:
            started = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            started = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if started <= cutoff:
            attempts = int(row.get("instagram_attempts") or 0)
            db.update(int(row["id"]), instagram_status="failed", instagram_error="Recovered stale Instagram processing job", instagram_next_retry_at=_next_retry(max(attempts, 1)))
            recovered += 1
    return recovered


def process_instagram(db: NewsDatabase, row: dict, music: str | None) -> bool:
    item_id = int(row["id"])
    attempts = int(row.get("instagram_attempts") or 0)
    if attempts >= MAX_INSTAGRAM_ATTEMPTS:
        return False
    attempts += 1
    started = datetime.now(timezone.utc).isoformat()
    db.update(item_id, instagram_status="processing", instagram_error=None, instagram_attempts=attempts, instagram_last_attempt_at=started, instagram_next_retry_at=None)
    if not music:
        db.update(item_id, instagram_status="failed", instagram_error="News Pulse audio unavailable", instagram_next_retry_at=_next_retry(attempts))
        return False
    try:
        cards = generate_reel_cards(
            title=row["title"],
            summary=row.get("ai_summary") or row.get("summary") or "",
            category=row.get("category") or "general",
            image_url=row.get("image_url"),
            source_name="",
            output_dir=OUT / "reel_cards" / str(item_id),
        )
        video = OUT / f"{item_id}.mp4"
        build_reel([str(p) for p in cards], str(video), audio_path=music, duration_per_image=18)
        url = upload_video(str(video)) or public_video_url(str(video))
        if not url:
            raise RuntimeError("Public Reel video URL unavailable")
        result = publish_reel(url, caption(row))
        media_id = result.get("id") if isinstance(result, dict) else None
        container_id = result.get("container_id") if isinstance(result, dict) else None
        db.update(item_id, instagram_status="published", instagram_media_id=media_id, instagram_container_id=container_id, instagram_selected=0, instagram_published_at=datetime.now(timezone.utc).isoformat(), instagram_error=None, instagram_next_retry_at=None)
        return True
    except Exception as exc:
        db.update(item_id, instagram_status="failed", instagram_error=str(exc)[:3000], instagram_next_retry_at=_next_retry(attempts))
        print(f"Instagram failed item {item_id}: {exc}")
        return False


def enrich_with_ai(db: NewsDatabase, row: dict, ai: AIService) -> bool:
    if not ai.enabled:
        return False
    try:
        source = enrich_source_text(row.get("title") or "", row.get("summary") or "")
        material = source.get("text") or row.get("summary") or row.get("title") or ""
        result = ai.newsroom_rewrite(row.get("title") or "", material, row.get("category") or "general")
        if not result:
            raise RuntimeError("AI newsroom rewrite returned incomplete output")
        fields = {"title": result["headline"], "ai_summary": result["summary"], "ai_article": result["article"], "summary": result["summary"]}
        if source.get("image_url") and not row.get("image_url"):
            fields["image_url"] = source["image_url"]
        db.update(int(row["id"]), **fields)
        row.update(fields)
        return True
    except Exception as exc:
        print(f"AI enrichment skipped for item {row.get('id')}: {exc}")
        return False


def repair_published_ai(db: NewsDatabase, ai: AIService, limit: int) -> int:
    if not ai.enabled or limit <= 0:
        return 0
    rows = [dict(r) for r in db.latest(max(limit * 4, limit), status="published") if not r.get("ai_article")][:limit]
    repaired = 0
    for row in rows:
        if enrich_with_ai(db, row, ai):
            repaired += 1
    return repaired


def _retry_due(row: dict, now: datetime) -> bool:
    if int(row.get("instagram_attempts") or 0) >= MAX_INSTAGRAM_ATTEMPTS:
        return False
    raw = row.get("instagram_next_retry_at")
    if not raw:
        return True
    try:
        due = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
        return due <= now
    except ValueError:
        return False


def _today_bounds():
    tz = ZoneInfo("Asia/Kolkata")
    today = datetime.now(tz).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def _minutes_since_last(db: NewsDatabase, now: datetime):
    raw = db.instagram_last_published_at()
    if not raw:
        return None
    try:
        last = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        return max(0, (now - last).total_seconds() / 60)
    except ValueError:
        return None


def _instagram_candidates(db: NewsDatabase, mode: str, limit: int):
    if limit <= 0:
        return []
    if mode == "manual":
        rows = [dict(r) for r in db.latest(max(limit * 5, 50), status="published", instagram_status="pending")]
        return [r for r in rows if int(r.get("instagram_selected") or 0) == 1][:limit]
    return [dict(r) for r in db.latest(limit, status="published", instagram_status="pending")]


def main():
    db = NewsDatabase()
    ai = AIService()
    settings = db.get_settings()
    env_ig = os.getenv("PUBLISH_TO_INSTAGRAM", "false").lower() in {"1", "true", "yes"}
    env_web = os.getenv("PUBLISH_WEBSITE", "true").lower() in {"1", "true", "yes"}
    require_ai = os.getenv("AI_REQUIRED_FOR_WEBSITE", "true").lower() in {"1", "true", "yes"}
    priority_id = str(settings.get("instagram_priority_id", "") or "").strip()
    paused = settings.get("instagram_paused", "false") == "true"
    publish_instagram = env_ig and (settings.get("instagram_enabled", "true") == "true" or bool(priority_id))
    publish_website = env_web and settings.get("website_enabled", "true") == "true"

    try:
        max_items = max(1, int(os.getenv("MAX_ITEMS", "15")))
    except ValueError:
        max_items = 15
    try:
        ai_items = max(0, int(os.getenv("AI_ENRICH_ITEMS", "8")))
    except ValueError:
        ai_items = 8
    try:
        ai_repair_items = max(0, int(os.getenv("AI_REPAIR_ITEMS", "5")))
    except ValueError:
        ai_repair_items = 5
    try:
        retry_limit = max(0, int(os.getenv("INSTAGRAM_RETRY_ITEMS", "10")))
    except ValueError:
        retry_limit = 10
    try:
        admin_daily = max(0, int(settings.get("instagram_daily_limit", "5")))
    except ValueError:
        admin_daily = 5
    try:
        env_daily = max(0, int(os.getenv("INSTAGRAM_NEW_ITEMS", "100")))
    except ValueError:
        env_daily = 100
    try:
        interval = max(0, int(settings.get("instagram_interval_minutes", "60")))
    except ValueError:
        interval = 60

    daily_limit = min(admin_daily, env_daily) if env_daily else 0
    now = datetime.now(timezone.utc)
    music = audio_path() if publish_instagram else None
    pending = [dict(r) for r in db.latest(max_items, status="pending")] if publish_website else []

    published = 0
    blocked = 0
    for row in pending:
        enriched = enrich_with_ai(db, row, ai) if ai_items > 0 else False
        ai_items -= 1 if ai_items > 0 else 0
        if require_ai and not enriched and not row.get("ai_article"):
            blocked += 1
            print(f"Website publish held for item {row['id']}: complete AI article unavailable")
            continue
        publish_website_first(db, row, now.isoformat())
        published += 1

    repaired = repair_published_ai(db, ai, ai_repair_items)

    attempted: set[int] = set()
    if publish_instagram:
        _recover_stale_processing(db, now)
        if priority_id:
            try:
                priority_row = next((dict(r) for r in db.latest(1000, status="published", instagram_status="all") if str(r["id"]) == priority_id), None)
            except Exception:
                priority_row = None
            if priority_row and priority_row.get("instagram_status") != "published":
                ok = process_instagram(db, priority_row, music)
                attempted.add(int(priority_row["id"]))
                if ok:
                    db.set_settings({"instagram_priority_id": "", "instagram_paused": "false"})
                    priority_id = ""
                    paused = False
                else:
                    print(f"Instagram priority item {priority_id} failed; normal queue remains paused")
            else:
                db.set_settings({"instagram_priority_id": "", "instagram_paused": "false"})
                priority_id = ""
                paused = False

        if not priority_id and not paused and daily_limit > 0:
            start, end = _today_bounds()
            published_today = db.instagram_daily_count(start.isoformat(), end.isoformat())
            remaining = max(0, daily_limit - published_today)
            since = _minutes_since_last(db, now)
            slot_open = since is None or since >= interval
            if remaining > 0 and slot_open:
                mode = settings.get("instagram_selection_mode", "auto")
                candidates = _instagram_candidates(db, mode, 1)
                if candidates:
                    row = candidates[0]
                    process_instagram(db, row, music)
                    attempted.add(int(row["id"]))
                elif retry_limit:
                    retry_rows = [dict(r) for r in db.latest(retry_limit, status="published", instagram_status="failed")]
                    for row in retry_rows:
                        if int(row["id"]) in attempted or not _retry_due(row, now):
                            continue
                        process_instagram(db, row, music)
                        attempted.add(int(row["id"]))
                        break
            else:
                print(f"Instagram slot closed: last_publish_minutes={since}, interval={interval}, remaining_today={remaining}")
        elif paused and not priority_id:
            print("Instagram queue paused by admin")

    print(f"Website published={published}; held_for_ai={blocked}; repaired={repaired}; Instagram enabled={publish_instagram}; paused={paused}; priority={priority_id or 'none'}; attempted={len(attempted)}")
    db.close()


if __name__ == "__main__":
    main()
