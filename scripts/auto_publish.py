from __future__ import annotations
import os, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    p=os.getenv("FIXED_AUDIO_PATH","").strip()
    if p and Path(p).exists(): return p
    url=os.getenv("FIXED_AUDIO_URL","").strip()
    if not url: return None
    if not url.startswith(("https://","http://")):
        print("Fixed audio URL is not a valid HTTP(S) URL; Instagram publishing will be skipped.")
        return None
    p=str(OUT/"fixed_music.mp3")
    try:
        return download_to(p,url)
    except Exception as exc:
        print("Fixed audio download failed; Instagram publishing will be skipped:",exc)
        return None

def main():
    db=NewsDatabase(); ai=AIService()
    publish_instagram=os.getenv("PUBLISH_TO_INSTAGRAM","false").strip().lower() in {"1","true","yes"}
    try:
        max_items=max(1,int(os.getenv("MAX_ITEMS","100")))
    except ValueError:
        max_items=100
    rows=[dict(r) for r in db.latest(max_items,status="pending")]
    music=audio_path() if publish_instagram else None
    if not publish_instagram:
        print("Instagram publishing is OFF (PUBLISH_TO_INSTAGRAM=false).")
    print(f"Processing up to {max_items} pending item(s).")
    processed=0
    for row in rows:
        if processed >= max_items: break
        source=row.get("summary") or row["title"]; ai_summary=row.get("ai_summary"); ai_article=row.get("ai_article")
        if ai.enabled:
            try:
                ai_summary=ai_summary or ai.summarize(row["title"],source)
                ai_article=ai_article or ai.write_article(row["title"],source)
                db.update(int(row["id"]),ai_summary=ai_summary,ai_article=ai_article)
            except Exception as exc: print("AI skipped:",exc)
        flags=risk_flags(row["title"],source); decision=publication_status(row["title"],source)
        db.update(int(row["id"]),status=decision,fact_check_status="needs_review" if flags else "pending",fact_check_notes=", ".join(flags) if flags else None)
        processed += 1
        if decision!="published": continue
        db.update(int(row["id"]),published_at_site=datetime.now(timezone.utc).isoformat())
        label=choose_template(row.get("category"),row["title"])
        web=OUT/f"{row['id']}_web.jpg"; reel_img=OUT/f"{row['id']}_reel.jpg"; video=OUT/f"{row['id']}.mp4"
        build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=label,out_path=str(web))
        build_graphic(row["title"],row.get("category") or "general",row.get("image_url"),label=label,reel=True,out_path=str(reel_img))
        if publish_instagram:
            if not music:
                print("Instagram skipped: fixed 18-second audio is unavailable",row["id"])
                continue
            build_reel([str(reel_img)],str(video),audio_path=music,duration_per_image=18)
            url=upload_video(str(video)) or public_video_url(str(video))
            if not url:
                print("Instagram skipped: public video URL unavailable",row["id"])
                continue
            try:
                print("Instagram result",publish_reel(url,caption({**row,"ai_summary":ai_summary})))
            except Exception as exc:
                print("Instagram publish failed:",exc)
        else:
            print("Reel generation skipped in safe mode",row["id"])
    db.close()

if __name__=="__main__": main()
