from __future__ import annotations
import os, sys, subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import NewsDatabase
from app.publish_policy import risk_flags
from app.instagram_graphic import generate_reel_cards
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url, download_to
from app.cloudinary_storage import upload_video
from app.ai import AIService

OUT = Path(os.getenv("MEDIA_OUTPUT_DIR", "data/media"))
OUT.mkdir(parents=True, exist_ok=True)


def caption(row):
    text = row.get("ai_summary") or row.get("summary") or row.get("title") or ""
    # Source names/links are intentionally omitted from Instagram captions.
    return f"{row['title']}\n\n{text[:700]}\n\npoliticshub.in"


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
            "ffmpeg", "-y", "-i", str(source), "-t", "18", "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-movflags", "+faststart", str(normalized)
        ], check=True, capture_output=True, text=True)
        return str(normalized)
    except Exception as exc:
        print("Fixed audio preparation failed:", exc)
        return None


def publish_website_first(db: NewsDatabase, row: dict, now: str) -> dict:
    """Website publication is the primary transaction and never waits for Instagram."""
    flags = risk_flags(row["title"], row.get("summary") or "")
    review_status = "needs_review" if flags else "pending"
    db.update(
        int(row["id"]),
        status="published",
        published_at_site=now,
        fact_check_status=review_status,
        fact_check_notes=", ".join(flags) if flags else None,
    )
    row["status"] = "published"
    row["fact_check_status"] = review_status
    print(f"Website LIVE: item {row['id']} (review={review_status}).")
    return row


def process_instagram(db: NewsDatabase, row: dict, music: str | None) -> bool:
    if not music:
        db.update(int(row["id"]), instagram_status="failed", instagram_error="News Pulse audio unavailable")
        return False

    db.update(int(row["id"]), instagram_status="processing", instagram_error=None)
    try:
        summary = row.get("ai_summary") or row.get("summary") or ""
        cards = generate_reel_cards(
            title=row["title"],
            summary=summary,
            category=row.get("category") or "general",
            image_url=row.get("image_url"),
            output_dir=OUT / "reel_cards" / str(row["id"]),
        )
        video = OUT / f"{row['id']}.mp4"
        build_reel([str(p) for p in cards], str(video), audio_path=music, duration_per_image=6)
        url = upload_video(str(video)) or public_video_url(str(video))
        if not url:
            raise RuntimeError("Public Reel video URL unavailable")
        result = publish_reel(url, caption(row))
        media_id = result.get("id") if isinstance(result, dict) else None
        db.update(
            int(row["id"]),
            instagram_status="published",
            instagram_media_id=media_id,
            instagram_published_at=datetime.now(timezone.utc).isoformat(),
            instagram_error=None,
        )
        print(f"Instagram LIVE: item {row['id']} media={media_id}")
        return True
    except Exception as exc:
        error = str(exc)[:2000]
        db.update(int(row["id"]), instagram_status="failed", instagram_error=error)
        print(f"Instagram failed for item {row['id']}: {error}")
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


def main():
    db = NewsDatabase()
    ai = AIService()
    publish_instagram = os.getenv("PUBLISH_TO_INSTAGRAM", "false").strip().lower() in {"1", "true", "yes"}
    try:
        max_items = max(1, int(os.getenv("MAX_ITEMS", "15")))
    except ValueError:
        max_items = 15
    try:
        retry_limit = max(0, int(os.getenv("INSTAGRAM_RETRY_ITEMS", "10")))
    except ValueError:
        retry_limit = 10

    now = datetime.now(timezone.utc).isoformat()
    music = audio_path() if publish_instagram else None

    # New items are published to the website immediately. Review is metadata,
    # not a publication gate. Instagram is an independent delivery channel.
    pending = [dict(r) for r in db.latest(max_items, status="pending")]
    retry_rows = []
    if publish_instagram and retry_limit:
        retry_rows = [
            dict(r) for r in db.latest(retry_limit, status="published", instagram_status="failed")
        ]

    print(f"New items: {len(pending)}; Instagram retries: {len(retry_rows)}")

    for row in pending:
        publish_website_first(db, row, now)
        enrich_with_ai(db, row, ai)
        if publish_instagram:
            process_instagram(db, row, music)

    # Retry failed Instagram delivery without touching website publication.
    for row in retry_rows:
        if row.get("instagram_status") == "published":
            continue
        print(f"Retrying Instagram for published item {row['id']}...")
        process_instagram(db, row, music)

    db.close()


if __name__ == "__main__":
    main()
