"""18-second Instagram Reel builder with fixed optional audio."""
from __future__ import annotations
import subprocess
from pathlib import Path

REEL_WIDTH=1080
REEL_HEIGHT=1920
FPS=30
DURATION=18

def build_reel_18s(image_path: str, output_path: str, audio_path: str|None=None) -> str:
    out=Path(output_path); out.parent.mkdir(parents=True,exist_ok=True)
    args=["ffmpeg","-y","-loop","1","-t",str(DURATION),"-i",image_path]
    if audio_path:
        args += ["-stream_loop","-1","-i",audio_path]
    vf=f"scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,crop={REEL_WIDTH}:{REEL_HEIGHT},setsar=1,format=yuv420p"
    args += ["-vf",vf,"-map","0:v:0","-r",str(FPS),"-c:v","libx264","-pix_fmt","yuv420p","-t",str(DURATION)]
    if audio_path:
        args += ["-map","1:a:0","-c:a","aac","-b:a","128k"]
    else:
        args += ["-an"]
    args += ["-movflags","+faststart",str(out)]
    subprocess.run(args,check=True,capture_output=True,text=True)
    return str(out)
