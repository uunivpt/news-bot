from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REEL_WIDTH = 1080
REEL_HEIGHT = 1920
REEL_FPS = 30
REEL_DURATION = 18.0
ROOT = Path(__file__).resolve().parents[1]


def _display_date(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y").upper()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        return dt.strftime("%d %b %Y").upper()
    except ValueError:
        return raw[:48].upper()


def _story_image(news: dict) -> str | None:
    raw = str(news.get("img") or news.get("image_url") or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://", "data:", "blob:")):
        return raw
    local = Path(raw)
    if not local.is_absolute():
        local = (ROOT / local).resolve()
    return str(local) if local.exists() else raw


def build_story_props(news: dict) -> dict:
    return {
        "HEADLINE": str(news.get("headline") or news.get("title") or "Latest news update").strip(),
        "IMAGE": _story_image(news),
        "CATEGORY": str(news.get("category") or "NEWS").strip(),
        "DATE": _display_date(news.get("date") or news.get("published_at")),
        "LOCATION": str(news.get("location") or "NEWS DESK").strip(),
        "SOURCE": str(news.get("source") or news.get("source_name") or "PoliticsHub.in").strip(),
        "SUMMARY": str(news.get("summary") or news.get("bot_summary") or "Read the full verified update on PoliticsHub.in").strip(),
        # Production audio is muxed by Python so the bot keeps using its existing fixed News Pulse track.
        "AUDIO": False,
        "LOGO": None,
        "DEBUG_SAFE": False,
    }


def _browser(env: dict[str, str]) -> None:
    if env.get("CHROME_PATH"):
        return
    # Prefer a real Google Chrome binary on GitHub runners. Ubuntu's chromium
    # package can resolve to a wrapper that Remotion cannot connect to reliably.
    found = shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if found:
        env["CHROME_PATH"] = found


def _validate(path: Path) -> str:
    if not path.exists() or path.stat().st_size < 20_000:
        raise RuntimeError("Remotion Reel QA failed: output MP4 is missing or unexpectedly small")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,pix_fmt,r_frame_rate:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(probe.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("Remotion Reel QA failed: no video stream")
    if (int(video.get("width") or 0), int(video.get("height") or 0)) != (REEL_WIDTH, REEL_HEIGHT):
        raise RuntimeError(f"Remotion Reel QA failed: expected {REEL_WIDTH}x{REEL_HEIGHT}")
    if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
        raise RuntimeError("Remotion Reel QA failed: unsupported pixel format")
    if str(video.get("r_frame_rate") or "") not in {"30/1", "60/2"}:
        raise RuntimeError(f"Remotion Reel QA failed: expected 30fps, got {video.get('r_frame_rate')}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration < REEL_DURATION - 0.25 or duration > REEL_DURATION + 0.75:
        raise RuntimeError(f"Remotion Reel QA failed: unexpected duration {duration:.2f}s")
    return str(path)


def render_remotion_reel(news: dict, output_path: str, audio_path: str | None = None, project_dir: str | None = None) -> str:
    project = Path(project_dir or os.getenv("POLITICSHUB_REMOTION_DIR") or ROOT / "reel")
    script = project / "scripts" / "render.mjs"
    if not script.exists():
        raise FileNotFoundError(f"PoliticsHub Remotion renderer not found: {script}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="politicshub_remotion_"))
    story = work / "story.json"
    silent = work / "silent.mp4"
    story.write_text(json.dumps(build_story_props(news), ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    _browser(env)
    try:
        subprocess.run(
            ["node", str(script), str(story), str(silent)],
            cwd=str(project), env=env, check=True,
            timeout=int(os.getenv("REMOTION_RENDER_TIMEOUT", "900")),
        )
        if audio_path and Path(audio_path).exists():
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(audio_path),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-profile:a", "aac_low",
                    "-b:a", "128k", "-ar", "48000", "-ac", "2", "-t", str(REEL_DURATION), "-movflags", "+faststart", str(output),
                ],
                check=True, capture_output=True, text=True,
            )
        else:
            shutil.copyfile(silent, output)
        return _validate(output)
    finally:
        shutil.rmtree(work, ignore_errors=True)
