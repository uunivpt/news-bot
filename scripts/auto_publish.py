from __future__ import annotations
import os, sys, subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import NewsDatabase
from app.publish_policy import publication_status, risk_flags
from app.content_pipeline import choose_template
from app.image_generator import build_graphic
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url, download_to
from app.cloudinary_storage import upload_video
from app.ai import AIService

OUT = Path(os.getenv("MEDIA_OUTPUT_DIR", "data/media"))
OUT.mkdir(parents=True, exist_ok=True)


def caption(row):
    text = row.get("ai_summary") or row.get("summary") or row.get("title") or ""
    return f"{row['title']}\n\n{text[:500]}\n\nSource: {row['source_name']}"


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
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration", "-of", "default=nw=1", str(source)],
            capture_output=True, text=True, check=True,
        )
        print("Fixed audio validated:", probe.stdout.strip().replace("\n", ", "))
        subprocess.run([
            "ffmpeg", "-y", "-i", str(source), "-t", "18", "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-movflags", "+faststart", str(normalized)
        ], check=True, capture_output=True, text=True)
        print("Fixed News Pulse audio normalized to 18-second AAC-LC.")
        return str(normalized)
    except Exception as exc:
        print("Fixed audio preparation failed:", exc)
        return None


def main():
    db = NewsDatabase()
    ai = AIService()
    publish_instagram = os.getenv("PUBLISH_TO_INSTAGRAM", "false").strip().lower() in {"1", "true", "yes"}
    require_instagram = os.getenv("REQUIRE_INSTAGRAM_PUBLISH", "false").strip().lower() in {"1", "true", "yes"}
    try:
        max_items = max(1, int(os.getenv("MAX_ITEMS", "100")))
    except ValueError:
        max_items = 100

    candidate_limit = max(max_items * 10, 20)
    rows = [dict(r) for r in db.latest(candidate_limit, status="pending")]
    music = audio_path() if publish_instagram else None
    print(f"Scanning up to {candidate_limit} pending item(s); publishing up to {max_items} eligible item(s).")

    eligible = []
    for row in rows:
        source = row.get("summary") or row["title"]
        flags = risk_flags(row["title"], source)
        decision = publication_status(row["title"], source)
        if decision != "published":
            db.update(int(row["id"]), status=decision, fact_check_status="needs_review", fact_check_notes=", ".join(flags) if flags else None)
            print(f"Item {row['id']} routed to review: {decision}; flags={flags}")
            continue
        eligible.append(row)
        if len(eligible) >= max_items:
            break

    if not eligible:
        db.close()
        if require_instagram:
            raise RuntimeError("No eligible pending news item was found for automatic publication.")
        print("No eligible pending news item found.")
        return

    instagram_success = 0
    for row in eligible:
        now = datetime.now(timezone.utc).isoformat()
        source = row.get("summary") or row["title"]
        ai_summary = row.get("ai_summary")
        ai_article = row.get("ai_article")
        if ai.enabled:
            try:
                ai_summary = ai_summary or ai.summarize(row["title"], source)
                ai_article = ai_article or ai.write_article(row["title"], source)
                db.update(int(row["id"]), ai_summary=ai_summary, ai_article=ai_article)
                row["ai_summary"] = ai_summary
            except Exception as exc:
                print(f"AI skipped for item {row['id']}:", exc)

        label = choose_template(row.get("category"), row["title"])
        web = OUT / f"{row['id']}_web.jpg"
        reel_img = OUT / f"{row['id']}_reel.jpg"
        video = OUT / f"{row['id']}.mp4"
        build_graphic(row["title"], row.get("category") or "general", row.get("image_url"), label=label, out_path=str(web))
        build_graphic(row["title"], row.get("category") or "general", row.get("image_url"), label=label, reel=True, out_path=str(reel_img))

        if publish_instagram:
            if not music:
                raise RuntimeError(f"News Pulse audio unavailable for item {row['id']}")
            build_reel([str(reel_img)], str(video), audio_path=music, duration_per_image=18)
            url = upload_video(str(video)) or public_video_url(str(video))
            if not url:
                raise RuntimeError(f"Public Reel video URL unavailable for item {row['id']}")
            try:
                result = publish_reel(url, caption(row))
                instagram_success += 1
                print("Instagram publish successful:", result)
            except Exception as exc:
                print("Instagram publish failed:", exc)
                if require_instagram:
                    raise
                continue

        db.update(
            int(row["id"]),
            status="published",
            published_at_site=now,
            fact_check_status="needs_review" if risk_flags(row["title"], source) else "pending",
            fact_check_notes=", ".join(risk_flags(row["title"], source)) or None,
        )
        print(f"Item {row['id']} published successfully.")

    db.close()
    if require_instagram and instagram_success < 1:
        raise RuntimeError("No Reel was successfully published to Instagram.")


if __name__ == "__main__":
    main()
