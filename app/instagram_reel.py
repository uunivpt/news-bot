"""Create Instagram-ready news reels from generated graphics.

Audio is intentionally supplied as a local/licensed asset by the owner.
No copyrighted/trending audio is fetched automatically.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REEL_WIDTH = 1080
REEL_HEIGHT = 1920
DEFAULT_FPS = 30


def build_reel(image_paths: list[str], output_path: str, audio_path: str | None = None,
               duration_per_image: float = 3.0) -> str:
    """Build a vertical MP4 reel from one or more images and optional fixed audio."""
    if not image_paths:
        raise ValueError("At least one image is required")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg is used for video encoding; images are scaled/cropped to 9:16.
    inputs: list[str] = []
    args = ["ffmpeg", "-y"]
    for image in image_paths:
        args += ["-loop", "1", "-t", str(duration_per_image), "-i", image]
        inputs.append(image)
    if audio_path:
        args += ["-i", audio_path]

    filters = []
    for i in range(len(image_paths)):
        filters.append(
            f"[{i}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,format=yuv420p[v{i}]"
        )
    concat = "".join(f"[v{i}]" for i in range(len(image_paths)))
    filters.append(f"{concat}concat=n={len(image_paths)}:v=1:a=0[vout]")

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-r", str(DEFAULT_FPS),
             "-c:v", "libx264", "-pix_fmt", "yuv420p"]

    if audio_path:
        audio_index = len(image_paths)
        args += ["-map", f"{audio_index}:a", "-c:a", "aac", "-shortest"]
    else:
        args += ["-an"]

    args += ["-movflags", "+faststart", str(output)]
    subprocess.run(args, check=True, capture_output=True, text=True)
    return str(output)
