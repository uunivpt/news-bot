"""DB-independent single-story Instagram release for PoliticsHub.

Runs once on the special workflow push, never on the regular 5-minute schedule.
Uses original Remotion animation and original synthetic audio (no third-party clip).
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from app.cloudinary_storage import upload_video
from app.meta_instagram import publish_reel
from app.news_pulse_audio import ensure_audio
from app.remotion_reel_renderer import render_remotion_reel

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "public" / "nana-tribute-published.json"
REEL = ROOT / "data" / "media" / "nana-patekar-tribute.mp4"
BEAT = ROOT / "data" / "media" / "nana-patekar-original-audio.wav"

TITLE = "Nana Patekar dies at 75 in Goa, leaving a lasting cinema legacy"
SUMMARY = (
    "Veteran actor Nana Patekar died aged 75 in Goa on 8 October 2026. "
    "Remembered for acclaimed Hindi and Marathi cinema performances, "
    "including Parinda, Krantiveer, Ab Tak Chhappan and Natsamrat."
)

def main():
    if STATUS.is_file():
        try:
            if json.loads(STATUS.read_text(encoding="utf-8")).get("published") is True:
                print("Memorial Instagram Reel already recorded as published; refusing duplicate.")
                return
        except (OSError, ValueError):
            pass
    REEL.parent.mkdir(parents=True, exist_ok=True)
    ensure_audio(BEAT)
    render_remotion_reel(
        {"headline": TITLE, "summary": SUMMARY,
         "category": "Entertainment", "date": "2026-10-08T06:00:00+05:30",
         "location": "Goa, India", "source": "Reuters and Associated Press",
         "image_url": None},
        str(REEL), audio_path=str(BEAT),
    )
    video_url = upload_video(
        str(REEL), public_id="politicshub/reels/nana-patekar-memorial-20261008"
    )
    if not video_url:
        raise RuntimeError("Cloudinary could not provide the public memorial Reel")
    caption = (
        "Remembering Nana Patekar (1951–2026).\n\n"
        "The acclaimed actor died in Goa on 8 October 2026, aged 75. "
        "His work across Hindi and Marathi cinema leaves a lasting legacy.\n\n"
        "Reporting: Reuters and Associated Press.\n"
        "Read the full sourced report: politicshub.in/nana-patekar-tribute.html\n\n"
        "#NanaPatekar #IndianCinema #MarathiCinema #PoliticsHub"
    )
    outcome = publish_reel(video_url, caption)
    media_id = str((outcome or {}).get("id") or "").strip()
    if not media_id:
        raise RuntimeError("Meta did not confirm a published Instagram media ID")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({
        "published": True, "media_id": media_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "template": "nana-tribute", "video_url": video_url,
        "story_url": "https://www.politicshub.in/nana-patekar-tribute.html",
        "source": "Reuters and Associated Press"
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Confirmed Meta Instagram publication media ID: {media_id}")

if __name__ == "__main__":
    main()
