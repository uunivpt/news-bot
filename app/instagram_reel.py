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


def _motion_filter(index: int, direction: str, frames: int) -> str:
    """Turn a still image into exactly `frames` moving frames.

    d=1 is intentional: the image input already runs at 30fps. Using d=180
    here would multiply frames and make the render unnecessarily huge.
    """
    # Keep every news image completely static. No zoom, pan, or Ken Burns
    # effect: the supplied photo stays visually unchanged throughout its scene.
    end = max(frames / DEFAULT_FPS - 0.18, 0.18)
    return (
        f"[{index}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,format=yuv420p,"
        f"fade=t=out:st={end:.2f}:d=0.18[v{index}]"
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
    return _validate_reel_output(output)

def build_reel(image_paths: list[str], output_path: str, audio_path: str | None = None, duration_per_image: float = SCENE_SECONDS) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration_per_image = float(duration_per_image)
    if duration_per_image <= 0:
        raise ValueError("duration_per_image must be positive")

    if len(image_paths) == 1:
        frames = int(round(REEL_DURATION * DEFAULT_FPS))
        args = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(DEFAULT_FPS), "-i", image_paths[0]]
        if audio_path:
            args += ["-stream_loop", "-1", "-i", audio_path]
        motion = _motion_filter(0, "right", frames)
        args += ["-filter_complex", motion, "-map", "[v0]", "-r", str(DEFAULT_FPS), *_video_codec_args()]
        args += (["-map", "1:a:0", *_audio_codec_args()] if audio_path else ["-an"])
        args += ["-t", str(REEL_DURATION), "-movflags", "+faststart", "-video_track_timescale", "90000", str(output)]
        _run_ffmpeg(args)
        return str(output)

    args = ["ffmpeg", "-y"]
    frames_per_scene = int(round(duration_per_image * DEFAULT_FPS))
    for image in image_paths:
        args += ["-loop", "1", "-framerate", str(DEFAULT_FPS), "-t", str(duration_per_image), "-i", image]
    if audio_path:
        args += ["-stream_loop", "-1", "-i", audio_path]

    filters = []
    directions = ("left", "right", "up")
    for i in range(len(image_paths)):
        filters.append(_motion_filter(i, directions[i % len(directions)], frames_per_scene))
    concat = "".join(f"[v{i}]" for i in range(len(image_paths)))
    filters.append(f"{concat}concat=n={len(image_paths)}:v=1:a=0[vout]")
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-r", str(DEFAULT_FPS), "-t", str(REEL_DURATION), *_video_codec_args()]
    if audio_path:
        audio_index = len(image_paths)
        args += ["-map", f"{audio_index}:a", *_audio_codec_args()]
    else:
        args += ["-an"]
    args += ["-t", str(REEL_DURATION), "-movflags", "+faststart", "-video_track_timescale", "90000", str(output)]
    _run_ffmpeg(args)
    return str(output)
