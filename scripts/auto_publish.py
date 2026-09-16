from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone
from app.database import NewsDatabase
from app.publish_policy import publication_status, risk_flags
from app.content_pipeline import choose_template
from app.image_generator import build_graphic
from app.instagram_reel import build_reel
from app.meta_instagram import publish_reel
from app.media_storage import public_video_url, download_to
from app.cloudinary_storage import upload_video
from app.ai import AIService

OUT=Path(os.getenv("MEDIA_OUTPUT_DIR","data/media")); OUT.mkdir(parents=True,exist_ok=True)
def caption(row):
    text=row.get("ai_summary") or row.get("summary") or row.get("title") or ""
    return f"{row['title']}\n\n{text[:500]}\n\nSource: {row['source_name']}"
def audio_path():
    p=os.getenv("FIXED_AUDIO_PATH","")
    if p and Path(p).exists():return p
    url=os.getenv("FIXED_AUDIO_URL","")
    if url:
        p=str(OUT/"fixed_music.mp3")
        try:return download_to(p,url)
        except Exception as exc:print("Audio download skipped:",exc)
    return None
def main():
    db=NewsDatabase(); ai=AIService(); rows=[dict(r) for r in db.latest(100,status="pending")]; music=audio_path()
    for row in rows:
        source=row.get("summary") or row["title"]; ai_summary=row.get("ai_summary"); ai_article=row.get("ai_article")
        if ai.enabled:
            try:
                ai_summary=ai_summary or ai.summarize(row["title"],source); ai_article=ai_article or ai.write_article(row["title"],source); db.update(int(row["id"]),ai_summary=ai_summary,ai_article=ai_article)
            except Exception as exc:print("AI skipped:",exc)
        flags=risk_flags(row["title"],source); decision=publication_status(row["title"],source)
        db.update(int(row["id"]),status=decision,fact_check_status="needs_review" if flags else "pending",fact_check_notes=", ".join(flags) if flags else None)
        if decision!="published":continue
        db.update(int(row["id"]),published_at_site=datetime.now(timezone.utc).isoformat())
        label=choose_template(row.get("category"),row["title"]); web=OUT/f"{row['id']}_web.jpg"; reel_img=OUT/f"{row['id']}_reel.jpg"; video=OUT/f"{row['id']}.mp4"
        build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=label,out_path=str(web)); build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=label,reel=True,out_path=str(reel_img)); build_reel([str(reel_img)],str(video),audio_path=music,duration_per_image=6)
        url=upload_video(str(video)) or public_video_url(str(video))
        if url and os.getenv("META_ACCESS_TOKEN") and os.getenv("META_INSTAGRAM_ACCOUNT_ID"):print("Instagram result",publish_reel(url,caption({**row,"ai_summary":ai_summary})))
        else:print("Instagram pending media storage or Meta credentials",row["id"])
    db.close()
if __name__=="__main__":main()
