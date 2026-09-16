"""Create Instagram-ready news reels from generated graphics."""
from __future__ import annotations
import subprocess
from pathlib import Path

REEL_WIDTH = 1080
REEL_HEIGHT = 1920
DEFAULT_FPS = 30
REEL_DURATION = 18


def _run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "FFmpeg returned a non-zero exit code").strip()
        raise RuntimeError(f"FFmpeg failed (exit {exc.returncode}): {detail}") from exc


def _video_codec_args() -> list[str]:
    # Conservative H.264/AAC settings for Instagram's remote video fetcher.
    return [
        "-c:v", "libx264",
        "-preset", "medium",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-crf", "20",
        "-maxrate", "8M",
        "-bufsize", "16M",
        "-pix_fmt", "yuv420p",
    ]


def _audio_codec_args() -> list[str]:
    return [
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
    ]


def build_reel(image_paths: list[str], output_path: str, audio_path: str | None = None,
               duration_per_image: float = REEL_DURATION) -> str:
    """Build a vertical MP4 reel with an exact 18-second output duration."""
    if not image_paths:
        raise ValueError("At least one image is required")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(image_paths) == 1:
        args = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(DEFAULT_FPS), "-i", image_paths[0],
        ]
        if audio_path:
            args += ["-stream_loop", "-1", "-i", audio_path]

        args += [
            "-t", str(REEL_DURATION),
            "-vf", (
                f"scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,format=yuv420p"
            ),
            "-map", "0:v:0", "-r", str(DEFAULT_FPS),
        ]
        args += _video_codec_args()
        if audio_path:
            args += ["-map", "1:a:0"] + _audio_codec_args() + ["-t", str(REEL_DURATION)]
        else:
            args += ["-an"]
        args += ["-movflags", "+faststart", str(output)]
        _run_ffmpeg(args)
        return str(output)

    args = ["ffmpeg", "-y"]
    for image in image_paths:
        args += ["-loop", "1", "-t", str(duration_per_image), "-i", image]
    if audio_path:
        args += ["-stream_loop", "-1", "-i", audio_path]

    filters = []
    for i in range(len(image_paths)):
        filters.append(
            f"[{i}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,format=yuv420p[v{i}]"
        )
    concat = "".join(f"[v{i}]" for i in range(len(image_paths)))
    filters.append(f"{concat}concat=n={len(image_paths)}:v=1:a=0[vout]")
    args += [
        "-filter_complex", ";".join(filters), "-map", "[vout]",
        "-r", str(DEFAULT_FPS), "-t", str(REEL_DURATION),
    ]
    args += _video_codec_args()
    if audio_path:
        audio_index = len(image_paths)
        args += ["-map", f"{audio_index}:a"] + _audio_codec_args() + ["-t", str(REEL_DURATION)]
    else:
        args += ["-an"]
    args += ["-movflags", "+faststart", str(output)]
    _run_ffmpeg(args)
    return str(output)
