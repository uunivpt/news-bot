"""Process pending stories into website + Instagram-ready media.

Safe stories publish automatically; stories containing high-risk allegations/incidents
are held for review so the system does not turn an unverified claim into a headline.
"""
from __future__ import annotations
import os
from pathlib import Path
from app.database import NewsDatabase
from app.publish_policy import publication_status
from app.image_generator import build_graphic
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url

OUT=Path(os.getenv("MEDIA_OUTPUT_DIR","data/media"))

def caption(row):
    text=row.get("ai_summary") or row.get("summary") or row.get("title") or ""
    return f"{row['title']}\n\n{text[:500]}\n\nSource: {row['source_name']}"

def main():
    db=NewsDatabase(); rows=db.latest(100,status="pending")
    for row in rows:
        title=row["title"]; summary=row["summary"] or title; category=row["category"] or "general"
        decision,flags=publication_status(title,summary)
        db.update(int(row["id"]),status=decision,fact_check_status="needs_review" if flags else "pending",fact_check_notes=", ".join(flags) if flags else None)
        if decision!="published": continue
        article=row.get("ai_article") or summary
        db.update(int(row["id"]),ai_article=article,published_at_site=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
        image=OUT/f"{row['id']}_web.jpg"; reel_img=OUT/f"{row['id']}_reel.jpg"; video=OUT/f"{row['id']}.mp4"
        build_graphic(title,category,row.get("image_url"),label=category,reel=False,out_path=str(image))
        build_graphic(title,category,row.get("image_url"),label=category,reel=True,out_path=str(reel_img))
        audio=os.getenv("FIXED_AUDIO_PATH") or None
        build_reel([str(reel_img)],str(video),audio_path=audio,duration_per_image=6)
        url=public_video_url(str(video))
        if url and os.getenv("META_ACCESS_TOKEN") and os.getenv("META_INSTAGRAM_ACCOUNT_ID"):
            result=publish_reel(url,caption(row)); print("Instagram published",row["id"],result)
        else:
            print("Instagram skipped (media URL or Meta credentials missing)",row["id"])
    db.close()

if __name__=="__main__": main()
