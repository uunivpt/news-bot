"""Create polished Instagram-ready 9:16 Reels with strict 18-second output."""
from __future__ import annotations
import subprocess
from pathlib import Path

REEL_WIDTH = 1080
REEL_HEIGHT = 1920
DEFAULT_FPS = 30
REEL_DURATION = 18
SCENE_SECONDS = 6


def _run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "FFmpeg returned a non-zero exit code").strip()
        raise RuntimeError(f"FFmpeg failed (exit {exc.returncode}): {detail}") from exc


def _video_codec_args() -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "medium", "-profile:v", "baseline", "-level:v", "4.0",
        "-crf", "21", "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
    ]


def _audio_codec_args() -> list[str]:
    return ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "48000", "-ac", "2"]


def _motion_filter(index: int, direction: str, frames: int, scene_seconds: float) -> str:
    """Deterministic Ken-Burns motion with direction variants and scene fade."""
    end = max(scene_seconds - 0.20, 0.20)
    if direction == "left":
        x = "iw/2-(iw/zoom/2)-min(80,iw/zoom/10)"
    elif direction == "up":
        x = "iw/2-(iw/zoom/2)"
    else:
        x = "iw/2-(iw/zoom/2)+min(80,iw/zoom/10)"
    y = "ih/2-(ih/zoom/2)" if direction != "up" else "ih/2-(ih/zoom/2)-min(70,ih/zoom/10)"
    zoom = "min(zoom+0.0009,1.075)"
    return (
        f"[{index}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={REEL_WIDTH}x{REEL_HEIGHT}:fps={DEFAULT_FPS},"
        f"fade=t=in:st=0:d=0.20,fade=t=out:st={end:.2f}:d=0.20,format=yuv420p[v{index}]"
    )


def _validate_reel_output(output: Path) -> str:
    """Hard fail before upload if the rendered MP4 is malformed."""
    if not output.exists() or output.stat().st_size < 20_000:
        raise RuntimeError("Reel QA failed: output MP4 is missing or unexpectedly small")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,pix_fmt:format=duration",
         "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    import json
    data = json.loads(probe.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("Reel QA failed: no video stream")
    if int(video.get("width") or 0) != REEL_WIDTH or int(video.get("height") or 0) != REEL_HEIGHT:
        raise RuntimeError(f"Reel QA failed: expected {REEL_WIDTH}x{REEL_HEIGHT}")
    if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
        raise RuntimeError("Reel QA failed: unsupported pixel format")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration < REEL_DURATION - 0.25 or duration > REEL_DURATION + 0.75:
        raise RuntimeError(f"Reel QA failed: unexpected duration {duration:.2f}s")
    return str(output)

def build_reel(image_paths: list[str], output_path: str, audio_path: str | None = None, duration_per_image: float = SCENE_SECONDS) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration_per_image = float(duration_per_image)
    duration_per_image = REEL_DURATION if len(image_paths) == 1 else min(duration_per_image, REEL_DURATION / len(image_paths))
    if duration_per_image <= 0:
        raise ValueError("duration_per_image must be positive")

    if len(image_paths) == 1:
        frames = int(round(REEL_DURATION * DEFAULT_FPS))
        args = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(DEFAULT_FPS), "-i", image_paths[0]]
        if audio_path:
            args += ["-stream_loop", "-1", "-i", audio_path]
        motion = _motion_filter(0, "right", frames, REEL_DURATION)
        args += ["-filter_complex", motion, "-map", "[v0]", "-r", str(DEFAULT_FPS), *_video_codec_args()]
        args += (["-map", "1:a:0", *_audio_codec_args()] if audio_path else ["-an"])
        args += ["-t", str(REEL_DURATION), "-movflags", "+faststart", "-video_track_timescale", "90000", str(output)]
        _run_ffmpeg(args)
        return _validate_reel_output(output)

    args = ["ffmpeg", "-y"]
    frames_per_scene = int(round(duration_per_image * DEFAULT_FPS))
    for image in image_paths:
        args += ["-loop", "1", "-framerate", str(DEFAULT_FPS), "-t", str(duration_per_image), "-i", image]
    if audio_path:
        args += ["-stream_loop", "-1", "-i", audio_path]

    filters = []
    directions = ("left", "right", "up")
    for i in range(len(image_paths)):
        filters.append(_motion_filter(i, directions[i % len(directions)], frames_per_scene, duration_per_image))
    concat = "".join(f"[v{i}]" for i in range(len(image_paths)))
    filters.append(f"{concat}concat=n={len(image_paths)}:v=1:a=0[base]")
    filters.append(f"[base]drawbox=x=0:y=1908:w=iw*min(t/{REEL_DURATION},1):h=8:color=0xc91524:t=fill[progress]")
    args += ["-filter_complex", ";".join(filters), "-map", "[progress]", "-r", str(DEFAULT_FPS), "-t", str(REEL_DURATION), *_video_codec_args()]
    if audio_path:
        audio_index = len(image_paths)
        args += ["-map", f"{audio_index}:a", *_audio_codec_args()]
    else:
        args += ["-an"]
    args += ["-t", str(REEL_DURATION), "-movflags", "+faststart", "-video_track_timescale", "90000", str(output)]
    _run_ffmpeg(args)
    return _validate_reel_output(output)


def build_html_reel(
    news: dict,
    output_path: str,
    audio_path: str | None = None,
    template_path: str | None = None,
) -> str:
    """Render the PoliticsHub HTML motion template as the production Reel."""
    from .html_reel_renderer import render_html_reel
    return render_html_reel(
        news,
        output_path,
        audio_path=audio_path,
        template_path=template_path,
    )
