from __future__ import annotations
import os, sys, subprocess, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import NewsDatabase
from app.publish_policy import risk_flags
from app.instagram_graphic import generate_reel_cards, clean_instagram_text
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url, download_to
from app.cloudinary_storage import upload_video
from app.ai import AIService

OUT = Path(os.getenv("MEDIA_OUTPUT_DIR", "data/media"))
OUT.mkdir(parents=True, exist_ok=True)
MAX_INSTAGRAM_ATTEMPTS = 6
STALE_PROCESSING_MINUTES = 20


def _dedupe_caption_text(title: str, text: str) -> str:
    title = re.sub(r"\s+", " ", (title or "")).strip()
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    if text.casefold().startswith(title.casefold()):
        text = text[len(title):].lstrip(" :–—-|\n")
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    unique = []
    for part in parts:
        if not any(part.casefold() == old.casefold() for old in unique):
            unique.append(part)
    return " ".join(unique)


def caption(row):
    source_name = str(row.get("source_name") or "")
    title = clean_instagram_text(row.get("title") or "", source_name)
    text = clean_instagram_text(row.get("ai_summary") or row.get("summary") or "", source_name)
    text = _dedupe_caption_text(title, text)
    return f"{title}\n\n{text[:700]}\n\npoliticshub.in" if text else f"{title}\n\npoliticshub.in"


def audio_path():
    p = os.getenv("FIXED_AUDIO_PATH", "").strip()
    if p and Path(p).exists():
        return p
    url = os.getenv("FIXED_AUDIO_URL", "").strip()
    if not url.startswith(("https://", "http://")):
        return None
    source = OUT / "fixed_music_source"
    normalized = OUT / "fixed_music_instagram.m4a"
    try:
        download_to(str(source), url)
        subprocess.run([
            "ffmpeg", "-y", "-i", str(source), "-t", "18", "-vn", "-ac", "2", "-ar", "48000",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-movflags", "+faststart", str(normalized)
        ], check=True, capture_output=True, text=True)
        return str(normalized)
    except Exception as exc:
        print("Fixed audio preparation failed:", exc)
        return None


def publish_website_first(db: NewsDatabase, row: dict, now: str) -> dict:
    flags = risk_flags(row["title"], row.get("summary") or "")
    review_status = "needs_review" if flags else "pending"
    db.update(int(row["id"]), status="published", published_at_site=now,
              fact_check_status=review_status, fact_check_notes=", ".join(flags) if flags else None)
    row["status"] = "published"
    row["fact_check_status"] = review_status
    print(f"Website LIVE: item {row['id']} (review={review_status}).")
    return row


def _next_retry(attempts: int) -> str:
    minutes = (5, 15, 30, 60, 120)[min(max(attempts - 1, 0), 4)]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _recover_stale_processing(db: NewsDatabase, now: datetime) -> int:
    rows = [dict(r) for r in db.latest(50, status="published", instagram_status="processing")]
    recovered = 0
    cutoff = now - timedelta(minutes=STALE_PROCESSING_MINUTES)
    for row in rows:
        raw = row.get("instagram_last_attempt_at")
        if not raw:
            continue
        try:
            started = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if started <= cutoff:
            attempts = int(row.get("instagram_attempts") or 0)
            db.update(int(row["id"]), instagram_status="failed",
                      instagram_error="Recovered stale Instagram processing job",
                      instagram_next_retry_at=_next_retry(max(attempts, 1)))
            recovered += 1
            print(f"Recovered stale Instagram job: item {row['id']}")
    return recovered


def process_instagram(db: NewsDatabase, row: dict, music: str | None) -> bool:
    item_id = int(row["id"])
    attempts = int(row.get("instagram_attempts") or 0)
    if attempts >= MAX_INSTAGRAM_ATTEMPTS:
        db.update(item_id, instagram_status="failed", instagram_error="Instagram retry limit reached")
        return False

    attempts += 1
    started = datetime.now(timezone.utc).isoformat()
    db.update(item_id, instagram_status="processing", instagram_error=None,
              instagram_attempts=attempts, instagram_last_attempt_at=started,
              instagram_next_retry_at=None)

    if not music:
        error = "News Pulse audio unavailable"
        db.update(item_id, instagram_status="failed", instagram_error=error,
                  instagram_next_retry_at=_next_retry(attempts))
        return False

    try:
        summary = row.get("ai_summary") or row.get("summary") or ""
        cards = generate_reel_cards(
            title=row["title"], summary=summary,
            category=row.get("category") or "general", image_url=row.get("image_url"),
            source_name=row.get("source_name") or "",
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
        db.update(item_id, instagram_status="published", instagram_media_id=media_id,
                  instagram_container_id=container_id, instagram_selected=0,
                  instagram_published_at=datetime.now(timezone.utc).isoformat(),
                  instagram_error=None, instagram_next_retry_at=None)
        print(f"Instagram LIVE: item {item_id} media={media_id} container={container_id}")
        return True
    except Exception as exc:
        error = str(exc)[:2000]
        db.update(item_id, instagram_status="failed", instagram_error=error,
                  instagram_next_retry_at=_next_retry(attempts))
        print(f"Instagram failed for item {item_id}, attempt {attempts}: {error}")
        return False


def enrich_with_ai(db: NewsDatabase, row: dict, ai: AIService) -> None:
    if not ai.enabled:
        return
    source = row.get("summary") or row["title"]
    try:
        ai_summary = row.get("ai_summary") or ai.summarize(row["title"], source)
        ai_article = row.get("ai_article") or ai.write_article(row["title"], source)
        db.update(int(row["id"]), ai_summary=ai_summary, ai_article=ai_article)
        row["ai_summary"] = ai_summary
        row["ai_article"] = ai_article
        print(f"AI enrichment complete: item {row['id']}")
    except Exception as exc:
        print(f"AI enrichment skipped for item {row['id']}: {exc}")


def _retry_due(row: dict, now: datetime) -> bool:
    if int(row.get("instagram_attempts") or 0) >= MAX_INSTAGRAM_ATTEMPTS:
        return False
    raw = row.get("instagram_next_retry_at")
    if not raw:
        return True
    try:
        due = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return due <= now
    except ValueError:
        return False


def _today_bounds():
    tz = ZoneInfo("Asia/Kolkata")
    today = datetime.now(tz).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def _instagram_candidates(db: NewsDatabase, mode: str, limit: int, now: datetime):
    if limit <= 0:
        return []
    if mode == "manual":
        rows = [dict(r) for r in db.latest(max(limit * 3, 20), status="published", instagram_status="pending")]
        return [r for r in rows if int(r.get("instagram_selected") or 0) == 1][:limit]
    return [dict(r) for r in db.latest(limit, status="published", instagram_status="pending")]


def main():
    db = NewsDatabase()
    ai = AIService()
    env_instagram = os.getenv("PUBLISH_TO_INSTAGRAM", "false").strip().lower() in {"1", "true", "yes"}
    env_website = os.getenv("PUBLISH_WEBSITE", "true").strip().lower() in {"1", "true", "yes"}
    settings = db.get_settings()
    publish_instagram = env_instagram and settings.get("instagram_enabled", "true") == "true"
    publish_website = env_website and settings.get("website_enabled", "true") == "true"

    try:
        max_items = max(1, int(os.getenv("MAX_ITEMS", "15")))
    except ValueError:
        max_items = 15
    try:
        ai_items = max(0, int(os.getenv("AI_ENRICH_ITEMS", "5")))
    except ValueError:
        ai_items = 5
    try:
        retry_limit = max(0, int(os.getenv("INSTAGRAM_RETRY_ITEMS", "10")))
    except ValueError:
        retry_limit = 10
    try:
        admin_daily_limit = max(0, int(settings.get("instagram_daily_limit", "5")))
    except ValueError:
        admin_daily_limit = 5
    try:
        env_daily_limit = max(0, int(os.getenv("INSTAGRAM_NEW_ITEMS", "5")))
    except ValueError:
        env_daily_limit = 5

    # The admin limit is the hard cap; the workflow env remains an additional safety cap.
    daily_limit = min(admin_daily_limit, env_daily_limit) if env_daily_limit else 0
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    music = audio_path() if publish_instagram else None

    pending = [dict(r) for r in db.latest(max_items, status="pending")] if publish_website else []
    for row in pending:
        publish_website_first(db, row, now_iso)

    if ai.enabled and ai_items:
        ai_rows = pending[:ai_items] if publish_website else [dict(r) for r in db.latest(ai_items, status="published")]
        for row in ai_rows:
            enrich_with_ai(db, row, ai)

    attempted_ids: set[int] = set()
    if publish_instagram and daily_limit > 0:
        _recover_stale_processing(db, now)
        day_start, day_end = _today_bounds()
        published_today = db.instagram_daily_count(day_start.isoformat(), day_end.isoformat())
        remaining = max(0, daily_limit - published_today)
        mode = settings.get("instagram_selection_mode", "auto")
        candidates = _instagram_candidates(db, mode, remaining, now)
        for row in candidates:
            process_instagram(db, row, music)
            attempted_ids.add(int(row["id"]))
            # Re-check the DB count after every attempt that can become live.
            published_today = db.instagram_daily_count(day_start.isoformat(), day_end.isoformat())
            remaining = max(0, daily_limit - published_today)
            if remaining <= 0:
                break

        # Failed retries also respect the same daily cap and never retry an item twice in one run.
        if retry_limit and remaining > 0:
            retry_rows = [dict(r) for r in db.latest(retry_limit, status="published", instagram_status="failed")]
            for row in retry_rows:
                item_id = int(row["id"])
                if item_id in attempted_ids or not _retry_due(row, now):
                    continue
                process_instagram(db, row, music)
                attempted_ids.add(item_id)
                published_today = db.instagram_daily_count(day_start.isoformat(), day_end.isoformat())
                remaining = max(0, daily_limit - published_today)
                if remaining <= 0:
                    break

    print(
        f"Website published={len(pending)}; Instagram enabled={publish_instagram}; "
        f"daily_limit={daily_limit}; Instagram attempted={len(attempted_ids) if publish_instagram else 0}"
    )
    db.close()


if __name__ == "__main__":
    main()
