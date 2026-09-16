from __future__ import annotations
import os, sys, subprocess, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.instagram_reel import build_reel
from app.cloudinary_storage import upload_video
from app.meta_instagram import publish_reel

OUT = Path("data/test_instagram")
OUT.mkdir(parents=True, exist_ok=True)


def download_and_validate_audio(url: str, path: Path) -> None:
    headers = {"User-Agent": "news-bot-instagram-test/1.0"}
    r = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
    r.raise_for_status()
    data = r.content
    path.write_bytes(data)

    content_type = (r.headers.get("content-type") or "").lower()
    print(f"Audio download: {len(data)} bytes, Content-Type: {content_type}, Final URL: {r.url}")

    if data[:1] == b"<" or "text/html" in content_type:
        raise RuntimeError(
            "FIXED_AUDIO_URL returned HTML instead of an audio file. "
            "Use Cloudinary's actual Secure delivery URL for the uploaded MP3 "
            "(res.cloudinary.com/.../raw/upload/...mp3), not a Media Library/console URL."
        )

    if len(data) < 1024:
        raise RuntimeError(f"Downloaded audio is suspiciously small ({len(data)} bytes). Check FIXED_AUDIO_URL.")

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration", "-of", "default=nw=1", str(path)],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "Downloaded FIXED_AUDIO_URL is not a valid FFmpeg-readable audio file. "
            f"ffprobe says: {probe.stderr.strip()}"
        )
    print("Audio validation successful:", probe.stdout.strip().replace("\n", ", "))


def validate_cloudinary_video(url: str) -> None:
    headers = {"User-Agent": "news-bot-instagram-test/1.0"}
    last_error = None
    for attempt in range(6):
        try:
            r = requests.get(url, headers=headers, timeout=60, allow_redirects=True, stream=True)
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "").lower()
            content_length = r.headers.get("content-length", "unknown")
            print(
                f"Cloudinary video preflight {attempt + 1}/6: "
                f"HTTP {r.status_code}, Content-Type: {content_type}, Size: {content_length}"
            )
            if "video/mp4" not in content_type:
                raise RuntimeError(f"Cloudinary URL did not return video/mp4 (got {content_type}).")
            r.close()
            print("Cloudinary video is publicly reachable and ready.")
            # Give Cloudinary a small propagation window before Meta fetches it.
            time.sleep(10)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"Cloudinary video preflight failed: {last_error}")


def main():
    audio = os.getenv("FIXED_AUDIO_URL", "").strip()
    if not audio.startswith(("https://", "http://")):
        raise RuntimeError("FIXED_AUDIO_URL must be a full public https:// URL")

    audio_path = OUT / "audio.mp3"
    download_and_validate_audio(audio, audio_path)

    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1080, 1920), (20, 24, 32))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42)
    d.text((80, 780), "NEWS REEL TEST", font=font, fill="white")
    d.text((80, 890), "Instagram publishing test", font=small, fill="white")
    image = OUT / "card.jpg"
    img.save(image, quality=92)

    video = OUT / "test_reel.mp4"
    build_reel([str(image)], str(video), audio_path=str(audio_path), duration_per_image=18)
    print("18-second MP4 created successfully")

    url = upload_video(str(video))
    if not url:
        raise RuntimeError("Cloudinary video upload returned no public URL")
    print("Cloudinary video upload successful")
    validate_cloudinary_video(url)

    result = publish_reel(url, "News Reel - Instagram publishing test")
    print("Instagram publish successful:", result)


if __name__ == "__main__":
    main()
