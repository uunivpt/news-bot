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
    if not url:
        return None
    if not url.startswith(("https://", "http://")):
        print("Fixed audio URL is not a valid HTTP(S) URL; Instagram publishing will be skipped.")
        return None

    source = OUT / "fixed_music_source"
    normalized = OUT / "fixed_music_instagram.m4a"
    try:
        download_to(str(source), url)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration",
             "-of", "default=nw=1", str(source)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            raise RuntimeError(f"FIXED_AUDIO_URL is not valid audio: {probe.stderr.strip()}")
        print("Fixed audio validated:", probe.stdout.strip().replace("\n", ", "))

        # Normalize the owner-supplied track before muxing. This avoids relying on
        # Instagram to interpret an MP3 source and guarantees a short AAC-LC track.
        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-t", "18", "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k",
            "-movflags", "+faststart", str(normalized),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Fixed audio normalized to 18-second AAC-LC for Instagram.")
        return str(normalized)
    except Exception as exc:
        print("Fixed audio preparation failed; Instagram publishing will be skipped:", exc)
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

    # Fetch a candidate pool larger than MAX_ITEMS. A risky/political item can be
    # correctly routed to review; it must not prevent a later eligible news item
    # from becoming the Reel in the same run.
    candidate_limit = max(max_items * 10, 20)
    rows = [dict(r) for r in db.latest(candidate_limit, status="pending")]
    music = audio_path() if publish_instagram else None

    if not publish_instagram:
        print("Instagram publishing is OFF (PUBLISH_TO_INSTAGRAM=false).")
    print(f"Scanning up to {candidate_limit} pending item(s); publishing up to {max_items} eligible item(s).")

    eligible = []
    for row in rows:
        source = row.get("summary") or row["title"]
        ai_summary = row.get("ai_summary")
        ai_article = row.get("ai_article")

        if ai.enabled:
            try:
                ai_summary = ai_summary or ai.summarize(row["title"], source)
                ai_article = ai_article or ai.write_article(row["title"], source)
                db.update(int(row["id"]), ai_summary=ai_summary, ai_article=ai_article)
                row["ai_summary"] = ai_summary
                row["ai_article"] = ai_article
            except Exception as exc:
                print(f"AI skipped for item {row['id']}:", exc)

        flags = risk_flags(row["title"], source)
        decision = publication_status(row["title"], source)
        db.update(
            int(row["id"]),
            status=decision,
            fact_check_status="needs_review" if flags else "pending",
            fact_check_notes=", ".join(flags) if flags else None,
        )

        if decision != "published":
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
        label = choose_template(row.get("category"), row["title"])
        web = OUT / f"{row['id']}_web.jpg"
        reel_img = OUT / f"{row['id']}_reel.jpg"
        video = OUT / f"{row['id']}.mp4"

        build_graphic(
            row["title"], row.get("category") or "general", row.get("image_url"),
            label=label, out_path=str(web)
        )
        build_graphic(
            row["title"], row.get("category") or "general", row.get("image_url"),
            label=label, reel=True, out_path=str(reel_img)
        )

        if publish_instagram:
            if not music:
                msg = f"Instagram skipped: fixed 18-second audio is unavailable for item {row['id']}"
                print(msg)
                if require_instagram:
                    raise RuntimeError(msg)
                continue

            build_reel([str(reel_img)], str(video), audio_path=music, duration_per_image=18)
            url = upload_video(str(video)) or public_video_url(str(video))
            if not url:
                msg = f"Instagram skipped: public video URL unavailable for item {row['id']}"
                print(msg)
                if require_instagram:
                    raise RuntimeError(msg)
                continue

            try:
                result = publish_reel(url, caption({**row, "ai_summary": row.get("ai_summary")}))
                instagram_success += 1
                db.update(int(row["id"]), published_at_site=now)
                print("Instagram result", result)
            except Exception as exc:
                print("Instagram publish failed:", exc)
                # Do not mark the article as published if Instagram failed.
                if require_instagram:
                    raise
                continue
        else:
            db.update(int(row["id"]), published_at_site=now)
            print("Reel generation skipped in safe mode", row["id"])

    db.close()
    if require_instagram and instagram_success < 1:
        raise RuntimeError("No Reel was successfully published to Instagram.")


if __name__ == "__main__":
    main()
