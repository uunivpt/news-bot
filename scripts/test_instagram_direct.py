from __future__ import annotations
import os, sys, subprocess, time, json
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
        raise RuntimeError("FIXED_AUDIO_URL returned HTML instead of an audio file.")
    if len(data) < 1024:
        raise RuntimeError(f"Downloaded audio is suspiciously small ({len(data)} bytes).")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration", "-of", "default=nw=1", str(path)],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"Downloaded FIXED_AUDIO_URL is not valid audio: {probe.stderr.strip()}")
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
            print(f"Cloudinary video preflight {attempt + 1}/6: HTTP {r.status_code}, Content-Type: {content_type}, Size: {content_length}")
            if "video/mp4" not in content_type:
                raise RuntimeError(f"Cloudinary URL did not return video/mp4 (got {content_type}).")
            r.close()
            print("Cloudinary video is publicly reachable and ready.")
            time.sleep(10)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"Cloudinary video preflight failed: {last_error}")


def inspect_video(path: Path) -> None:
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_name,profile,codec_type,width,height,r_frame_rate,avg_frame_rate,pix_fmt,level,has_b_frames,sample_rate,channels:format=format_name,duration,size",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"Generated MP4 failed ffprobe: {probe.stderr.strip()}")
    print("Generated MP4 ffprobe:")
    print(probe.stdout)
    data = json.loads(probe.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not video or video.get("codec_name") != "h264":
        raise RuntimeError("Generated Reel is not H.264 video.")
    if video.get("width") != 1080 or video.get("height") != 1920:
        raise RuntimeError(f"Generated Reel has wrong dimensions: {video.get('width')}x{video.get('height')}")
    if video.get("pix_fmt") != "yuv420p":
        raise RuntimeError(f"Generated Reel has wrong pixel format: {video.get('pix_fmt')}")
    if abs(duration - 18.0) > 0.15:
        raise RuntimeError(f"Generated Reel is not 18 seconds: {duration}")
    if audio and (audio.get("codec_name") != "aac" or str(audio.get("sample_rate")) != "48000"):
        raise RuntimeError("Generated Reel audio is not AAC 48 kHz.")


def main():
    skip_audio = os.getenv("SKIP_AUDIO", "false").strip().lower() in {"1", "true", "yes"}
    audio_path = None
    if skip_audio:
        print("Diagnostic mode: publishing video-only Reel to isolate Meta video/API compatibility.")
    else:
        audio_url = os.getenv("FIXED_AUDIO_URL", "").strip()
        if not audio_url.startswith(("https://", "http://")):
            raise RuntimeError("FIXED_AUDIO_URL must be a full public https:// URL")
        audio_path = OUT / "news_pulse.mp3"
        print("Using the real FIXED_AUDIO_URL audio track for this Instagram test.")
        download_and_validate_audio(audio_url, audio_path)

    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1080, 1920), (20, 24, 32))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42)
    d.text((80, 780), "NEWS REEL TEST", font=font, fill="white")
    d.text((80, 890), "Instagram compatibility test", font=small, fill="white")
    image = OUT / "card.jpg"
    img.save(image, quality=92)

    video = OUT / "test_reel.mp4"
    build_reel([str(image)], str(video), audio_path=str(audio_path) if audio_path else None, duration_per_image=18)
    print("18-second MP4 created successfully")
    inspect_video(video)

    url = upload_video(str(video))
    if not url:
        raise RuntimeError("Cloudinary video upload returned no public URL")
    print("Cloudinary video upload successful")
    validate_cloudinary_video(url)

    result = publish_reel(url, "News Reel - Instagram publishing test")
    print("Instagram publish successful:", result)


if __name__ == "__main__":
    main()
