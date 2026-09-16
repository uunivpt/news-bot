from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

from app.instagram_reel import build_reel

OUT = Path("data/test_reel")
OUT.mkdir(parents=True, exist_ok=True)


def get_audio() -> str:
    url = os.getenv("FIXED_AUDIO_URL", "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "FIXED_AUDIO_URL is not a full HTTPS/HTTP URL. It must be the Cloudinary Secure URL, "
            "starting with https://res.cloudinary.com/..."
        )
    path = OUT / "fixed_music.mp3"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    path.write_bytes(r.content)
    if path.stat().st_size < 1000:
        raise RuntimeError("Downloaded audio file is unexpectedly small")
    return str(path)


def make_sample_image() -> str:
    path = OUT / "sample.jpg"
    image = Image.new("RGB", (1080, 1920), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    draw.text((70, 150), "NEWS PULSE", font=font, fill="black")
    draw.text((70, 260), "18 SECOND REEL TEST", font=small, fill="black")
    draw.rectangle((70, 380, 1010, 1320), outline="black", width=5)
    draw.text((120, 800), "AUDIO + VIDEO TEST", font=small, fill="black")
    image.save(path, quality=92)
    return str(path)


def duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    audio = get_audio()
    image = make_sample_image()
    video = OUT / "news_pulse_test_18s.mp4"
    build_reel([image], str(video), audio_path=audio, duration_per_image=18)
    d = duration(str(video))
    print(f"TEST_REEL_DURATION={d:.3f}")
    if not 17.8 <= d <= 18.2:
        raise RuntimeError(f"Expected an 18-second reel, got {d:.3f}s")
    print("TEST_REEL_OK=1")


if __name__ == "__main__":
    main()
