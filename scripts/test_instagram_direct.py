from __future__ import annotations
import os, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.instagram_reel import build_reel
from app.cloudinary_storage import upload_video
from app.meta_instagram import publish_reel

OUT=Path("data/test_instagram"); OUT.mkdir(parents=True,exist_ok=True)

def main():
    audio=os.getenv("FIXED_AUDIO_URL","").strip()
    if not audio.startswith(("https://","http://")):
        raise RuntimeError("FIXED_AUDIO_URL must be a full public https:// URL")
    audio_path=OUT/"audio.mp3"
    r=requests.get(audio,timeout=60); r.raise_for_status(); audio_path.write_bytes(r.content)
    from PIL import Image, ImageDraw, ImageFont
    img=Image.new("RGB",(1080,1920),(20,24,32)); d=ImageDraw.Draw(img)
    font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",72)
    small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",42)
    d.text((80,780),"NEWS REEL TEST",font=font,fill="white")
    d.text((80,890),"Instagram publishing test",font=small,fill="white")
    image=OUT/"card.jpg"; img.save(image,quality=92)
    video=OUT/"test_reel.mp4"
    build_reel([str(image)],str(video),audio_path=str(audio_path),duration_per_image=18)
    print("18-second MP4 created successfully")
    url=upload_video(str(video))
    if not url: raise RuntimeError("Cloudinary video upload returned no public URL")
    print("Cloudinary video upload successful")
    result=publish_reel(url,"News Reel — Instagram publishing test")
    print("Instagram publish successful:",result)

if __name__=="__main__": main()
