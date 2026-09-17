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
        "-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-level:v", "4.1",
        "-crf", "21", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p",
        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
    ]


def _audio_codec_args() -> list[str]:
    return ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "48000", "-ac", "2"]


def _motion_filter(index: int, direction: str) -> str:
    # Render each still as a 6s moving editorial shot. Different x/y motion keeps
    # the three scenes from feeling like a static slideshow.
    if direction == "left":
        x = "iw/2-(iw/zoom/2)-min(90,(on/179)*90)"
        y = "ih/2-(ih/zoom/2)"
    elif direction == "right":
        x = "iw/2-(iw/zoom/2)+min(90,(on/179)*90)"
        y = "ih/2-(ih/zoom/2)"
    else:
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)-min(70,(on/179)*70)"
    return (
        f"[{index}:v]scale=1280:2276:force_original_aspect_ratio=increase,"
        f"crop=1280:2276,zoompan=z='min(zoom+0.0008,1.14)':x='{x}':y='{y}':"
        f"d=180:s={REEL_WIDTH}x{REEL_HEIGHT}:fps={DEFAULT_FPS},"
        f"setsar=1,format=yuv420p,fade=t=in:st=0:d=0.18,fade=t=out:st=5.82:d=0.18[v{index}]"
    )


def build_reel(image_paths: list[str], output_path: str, audio_path: str | None = None, duration_per_image: float = SCENE_SECONDS) -> str:
    if not image_paths:
        raise ValueError("At least one image is required")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(image_paths) == 1:
        args = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(DEFAULT_FPS), "-i", image_paths[0]]
        if audio_path:
            args += ["-stream_loop", "-1", "-i", audio_path]
        args += [
            "-t", str(REEL_DURATION),
            "-vf", f"scale=1280:2276:force_original_aspect_ratio=increase,crop=1280:2276,zoompan=z='min(zoom+0.0007,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=540:s={REEL_WIDTH}x{REEL_HEIGHT}:fps={DEFAULT_FPS},setsar=1,format=yuv420p,fade=t=in:st=0:d=0.2,fade=t=out:st=17.8:d=0.2",
            "map", "0:v:0", "-r", str(DEFAULT_FPS), *_video_codec_args(),
        ]
        # Correct ffmpeg option spelling after assembling the filter chain.
        args[args.index("map")] = "-map"
        args += (["-map", "1:a:0", *_audio_codec_args()] if audio_path else ["-an"])
        args += ["-t", str(REEL_DURATION), "-movflags", "+faststart", "-video_track_timescale", "90000", str(output)]
        _run_ffmpeg(args)
        return str(output)

    args = ["ffmpeg", "-y"]
    for image in image_paths:
        args += ["-loop", "1", "-t", str(SCENE_SECONDS), "-i", image]
    if audio_path:
        args += ["-stream_loop", "-1", "-i", audio_path]

    filters = []
    directions = ("left", "right", "up")
    for i in range(len(image_paths)):
        filters.append(_motion_filter(i, directions[i % len(directions)]))
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
