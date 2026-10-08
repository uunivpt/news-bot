from __future__ import annotations

import json
import os
import re
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


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F"
    "\u200D"
    "]+",
    flags=re.UNICODE,
)


def _clean_reel_text(value: object) -> str:
    text = str(value or "").strip()
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[/,:;|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.!?])", r"\1", text)
    return text


def _first_complete_sentence(value: object) -> str:
    text = _clean_reel_text(value)
    if not text:
        return ""
    match = re.search(r"^(.+?[.!?])(?:\s|$)", text)
    sentence = (match.group(1) if match else text).strip()
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def _reel_headline(news: dict) -> str:
    raw = news.get("headline") or news.get("title") or "Latest news update"
    headline = _clean_reel_text(raw)
    if len(headline.split()) < 4:
        richer = _first_complete_sentence(news.get("summary") or news.get("bot_summary"))
        if len(richer.split()) >= 4:
            headline = richer
    if headline and headline[-1] not in ".!?":
        headline += "."
    return headline or "Latest news update."


def _reel_summary(news: dict) -> str:
    primary = _first_complete_sentence(
        news.get("summary") or news.get("bot_summary") or news.get("bot_article") or news.get("article")
    )
    if not primary:
        primary = "Read the full verified update on PoliticsHub.in."
    words = primary.split()
    if len(words) < 10 or len(primary) < 70:
        extra_source = news.get("bot_article") or news.get("article") or news.get("body") or ""
        extra_text = _clean_reel_text(extra_source)
        extra_parts = re.split(r"(?<=[.!?])\s+", extra_text)
        for part in extra_parts:
            part = _first_complete_sentence(part)
            if not part or part.lower() == primary.lower() or len(part.split()) < 6:
                continue
            combined = (primary + " " + part).strip()
            if len(combined) <= 300:
                primary = combined
            break
    return primary


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
        "HEADLINE": _reel_headline(news),
        "IMAGE": _story_image(news),
        "CATEGORY": _clean_reel_text(news.get("category") or "NEWS").upper(),
        "DATE": _display_date(news.get("date") or news.get("published_at")),
        "LOCATION": _clean_reel_text(news.get("location") or "NEWS DESK"),
        "SOURCE": _clean_reel_text(news.get("source") or news.get("source_name") or "PoliticsHub.in"),
        "SUMMARY": _reel_summary(news),
        # Production audio is muxed by Python so the bot keeps using its existing fixed News Pulse track.
        "AUDIO": False,
        "LOGO": None,
        "DEBUG_SAFE": False,
        "TEMPLATE": "nana-tribute" if "nana patekar dies at 75" in _reel_headline(news).lower() else None,
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
