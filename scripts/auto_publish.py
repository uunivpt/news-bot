from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone
from app.database import NewsDatabase
from app.publish_policy import publication_status, risk_flags
from app.image_generator import build_graphic
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url
from app.cloudinary_storage import upload_video

OUT=Path(os.getenv("MEDIA_OUTPUT_DIR","data/media"))
def caption(row):
    text=row.get("ai_summary") or row.get("summary") or row.get("title") or ""
    return f"{row['title']}\n\n{text[:500]}\n\nSource: {row['source_name']}"

def main():
    db=NewsDatabase(); rows=[dict(r) for r in db.latest(100,status="pending")]
    for row in rows:
        flags=risk_flags(row["title"],row.get("summary") or ""); decision=publication_status(row["title"],row.get("summary") or "")
        db.update(int(row["id"]),status=decision,fact_check_status="needs_review" if flags else "pending",fact_check_notes=", ".join(flags) if flags else None)
        if decision!="published":continue
        db.update(int(row["id"]),ai_article=row.get("ai_article") or row.get("summary") or row["title"],published_at_site=datetime.now(timezone.utc).isoformat())
        web=OUT/f"{row['id']}_web.jpg"; reel_img=OUT/f"{row['id']}_reel.jpg"; video=OUT/f"{row['id']}.mp4"
        build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=row.get("category") or "NEWS",out_path=str(web))
        build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=row.get("category") or "NEWS",reel=True,out_path=str(reel_img))
        build_reel([str(reel_img)],str(video),audio_path=os.getenv("FIXED_AUDIO_PATH") or None,duration_per_image=6)
        url=upload_video(str(video)) or public_video_url(str(video))
        if url and os.getenv("META_ACCESS_TOKEN") and os.getenv("META_INSTAGRAM_ACCOUNT_ID"):
            print("Instagram result",publish_reel(url,caption(row)))
        else:print("Instagram pending media storage or Meta credentials",row["id"])
    db.close()
if __name__=="__main__":main()
