from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.article_fetcher import enrich_source_text
from app.cloudinary_storage import upload_video
from app.database import NewsDatabase
from app.instagram_graphic import clean_instagram_text, generate_reel_cards
from app.instagram_reel import build_reel
from app.media_storage import download_to, public_video_url
from app.meta_instagram import publish_reel, InstagramRateLimitError
from app.newsroom import process_news
from app.publish_policy import risk_flags
from app.phase_system import ensure_schema, run as agent_run, start as agent_start, finish as agent_finish, quality_gate, manager_route
from app.advanced_ops import LAYOUTS, reserve_layout, layout_by_id, audit_stage, state_transition, visual_qa_card, record_verification, find_duplicate_story
from app.advanced_system import ensure_schema as ensure_upgrade_schema, score_story, select_layout, attach_event, self_heal, publish_lock, mark_published, is_published, record_preview, record_source
OUT=Path(os.getenv("MEDIA_OUTPUT_DIR","data/media")); OUT.mkdir(parents=True,exist_ok=True)
MAX_INSTAGRAM_ATTEMPTS=999999; STALE_PROCESSING_MINUTES=20
TRAILING_FRAGMENT_RE=re.compile(r"\b(?:a|an|and|as|at|by|for|from|in|including|into|of|on|or|the|their|this|to|under|via|was|were|with|without)\.?$",re.I)
SHORT_FINAL_TOKEN_RE=re.compile(r"\b[a-zA-Z]{1,2}\.$")
KNOWN_SHORT_ENDINGS={"US.","UK.","EU.","UN.","AI.","PM.","MP.","CM.","UP.","U.S.","U.K."}

def _bad_fragment(text):
 value=re.sub(r"\s+"," ",text or "").rstrip()
 if not value:return True
 if TRAILING_FRAGMENT_RE.search(value):return True
 match=SHORT_FINAL_TOKEN_RE.search(value)
 return bool(match and match.group(0) not in KNOWN_SHORT_ENDINGS)

def _dedupe_caption_text(title,text):
 title=re.sub(r"\s+"," ",title or "").strip(); text=re.sub(r"\s+"," ",text or "").strip()
 if not text:return ""
 if text.casefold().startswith(title.casefold()):text=text[len(title):].lstrip(" :–—-|\n")
 parts=[p.strip() for p in re.split(r"\n+",text) if p.strip()]; unique=[]
 for part in parts:
  if not any(part.casefold()==old.casefold() for old in unique):unique.append(part)
 return " ".join(unique)

REEL_HASHTAGS="#reel #update #news #politics #global"

def caption(row):
 title=clean_instagram_text(row.get("title") or "",""); text=clean_instagram_text(row.get("bot_summary") or row.get("summary") or "",row.get("source_name") or ""); text=_dedupe_caption_text(title,text)
 base=f"{title}\\n\\n{text}" if text else title
 return f"{base}\\n\\n{REEL_HASHTAGS}"

def audio_path():
 path=os.getenv("FIXED_AUDIO_PATH","").strip()
 if path and Path(path).exists():return path
 url=os.getenv("FIXED_AUDIO_URL","").strip()
 if url.startswith(("https://","http://")):
  source=OUT/"fixed_music_source"; normalized=OUT/"fixed_music_instagram.m4a"
  try:
   download_to(str(source),url); subprocess.run(["ffmpeg","-y","-i",str(source),"-t","18","-vn","-ac","2","-ar","48000","-c:a","aac","-profile:a","aac_low","-b:a","128k","-movflags","+faststart",str(normalized)],check=True,capture_output=True,text=True); return str(normalized)
  except Exception as exc:print("Fixed audio preparation failed:",exc)
 # Built-in PoliticsHub News Pulse: keeps the selected beat available
 # on the phone without requiring another URL or environment variable.
 embedded=OUT/"politicshub_news_pulse_15s.wav"
 try:
  if not embedded.exists():
   from app.news_pulse_audio import ensure_audio
   ensure_audio(embedded)
  print("Using embedded PoliticsHub News Pulse audio.")
  return str(embedded)
 except Exception as exc:
  print("Embedded News Pulse preparation failed:",exc)
  return None

def _process_content(row):
 try:
  source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or "")
  material=source.get("text") or row.get("summary") or row.get("title") or ""
  result=process_news(row.get("title") or "",material,row.get("category") or "general")
  if not result:return False
  fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"]}
  state_transition(db,int(row["id"]),"PROCESSING")
  qa=quality_gate(fields["title"],fields["summary"],fields["bot_article"])
  state_transition(db,int(row["id"]),"QUALITY_CHECK",";".join(qa["errors"]) if not qa["passed"] else None)
  if not qa["passed"]:
   print(f"Quality gate blocked item {row.get('id')}: {qa['errors']}")
   return False
  if source.get("image_url") and not row.get("image_url"):fields["image_url"]=source["image_url"]
  audit_stage(db,int(row["id"]),"WRITER","completed",{"quality_score":qa["score"],"warnings":qa["warnings"]})
  row.update(fields); return fields
 except Exception as exc:print(f"Bot processing failed for item {row.get('id')}: {exc}"); return False

def _direct_fallback_content(row):
 # Very short alerts cannot be expanded safely by the newsroom processor.
 # Publish the source wording directly after removing source-name fragments and emoji.
 title=clean_instagram_text(row.get("title") or "",row.get("source_name") or "")
 raw=row.get("summary") or row.get("title") or ""
 summary=clean_instagram_text(raw,row.get("source_name") or "")
 if not summary:
  summary=title
 if not title and not summary:return False
 article=summary
 return {"title":title or "Latest news update","summary":summary,"bot_summary":summary,"bot_article":article}

def prepare_content(db,row):
 fields=_process_content(row)
 if fields:
  db.update(int(row["id"]),**fields); return True
 fallback=_direct_fallback_content(row)
 if not fallback:return False
 db.update(int(row["id"]),**fallback); row.update(fallback)
 print(f"Using direct source fallback for short item {row['id']}")
 return True

def process_content(db,row):
 return prepare_content(db,row)

def _needs_content_repair(row):
 title=str(row.get("title") or "").strip(); summary=str(row.get("bot_summary") or row.get("summary") or "").strip(); article=str(row.get("bot_article") or "").strip()
 if not article or not summary:return True
 if title.endswith(("…","...")) or len(title.split())>18:return True
 return _bad_fragment(summary) or _bad_fragment(article)

def publish_website_first(db,row,now):
 flags=risk_flags(row["title"],row.get("bot_summary") or row.get("summary") or ""); review="needs_review" if flags else "pending"
 db.update(int(row["id"]),status="published",published_at_site=now,fact_check_status=review,fact_check_notes=", ".join(flags) if flags else None); row["status"]="published"; return row

def _next_retry(attempts):
 minutes=(5,15,30,60,120)[min(max(attempts-1,0),4)]; return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()

def _recover_stale_processing(db,now):
 rows=[dict(r) for r in db.latest(100,status="published",instagram_status="processing")]; cutoff=now-timedelta(minutes=STALE_PROCESSING_MINUTES); recovered=0
 for row in rows:
  raw=row.get("instagram_last_attempt_at")
  if not raw:continue
  try:started=datetime.fromisoformat(str(raw).replace("Z","+00:00")); started=started if started.tzinfo else started.replace(tzinfo=timezone.utc)
  except ValueError:continue
  if started<=cutoff:
   attempts=int(row.get("instagram_attempts") or 0); db.update(int(row["id"]),instagram_status="failed",instagram_error="Recovered stale Instagram processing job",instagram_next_retry_at=_next_retry(max(attempts,1))); recovered+=1
 return recovered

def _process_instagram_untracked(db,row,music):
 item_id=int(row["id"]); attempts=int(row.get("instagram_attempts") or 0)
 if attempts>=MAX_INSTAGRAM_ATTEMPTS:return False
 attempts+=1; started=datetime.now(timezone.utc).isoformat(); db.update(item_id,instagram_status="processing",instagram_error=None,instagram_attempts=attempts,instagram_last_attempt_at=started,instagram_next_retry_at=None)
 if is_published(db,item_id,"instagram"):
  db.update(item_id,instagram_status="published",instagram_selected=0,instagram_error=None,instagram_next_retry_at=None)
  return True
 if not music:db.update(item_id,instagram_status="failed",instagram_error="News Pulse audio unavailable",instagram_next_retry_at=_next_retry(attempts)); return False
 try:
  # Ensure manually published stories are processed before any Instagram Reel is built.
  if not row.get("bot_article") or not row.get("bot_summary"):
   if not process_content(db,row):
    raise RuntimeError("Story could not be processed by the newsroom bot")
  url=str(row.get("reel_cloudinary_url") or "").strip()
  cards=[]; qa_card={"passed":True,"cached":True}; layout={"id":"cached"}
  if url:
   print(f"Reusing cached Reel URL for item {item_id}: {url}")
  else:
   layout=select_layout(row.get("category") or "general",row.get("title") or "",item_id,breaking=bool((score_story(db,row,1,"UNVERIFIED",0) or {}).get("breaking")),has_image=bool(row.get("image_url")))
   state_transition(db,item_id,"INSTAGRAM_QUEUE")
   audit_stage(db,item_id,"TEMPLATE_SELECTED","completed",layout)
   profile=layout
   cards=generate_reel_cards(title=row["title"],summary=row.get("bot_summary") or row.get("summary") or "",category=row.get("category") or "general",image_url=row.get("image_url"),source_name=row.get("source_name") or "",output_dir=OUT/"reel_cards"/str(item_id),item_key=item_id,template_variant=int(layout["variant"]))
   for card in cards:
    qa_card=visual_qa_card(card)
    if not qa_card.get("passed"): raise RuntimeError(f"Visual QA failed: {qa_card.get('errors')}")
   video=OUT/f"{item_id}.mp4"; build_reel([str(p) for p in cards],str(video),audio_path=music,duration_per_image=18)
   state_transition(db,item_id,"REEL_CREATED")
   audit_stage(db,item_id,"REEL_QA","completed",{"cards":len(cards),"layout":layout["id"]}); record_preview(db,item_id,str(video),str(cards[0]) if cards else "",qa_card,layout["id"])
   public_id=f"politicshub/reels/item-{item_id}"
   url=upload_video(str(video),public_id=public_id) or public_video_url(str(video))
   if not url:raise RuntimeError("Public Reel video URL unavailable")
   db.update(item_id,reel_cloudinary_url=url,reel_cloudinary_public_id=public_id)
  record_preview(db,item_id,url,str(cards[0]) if cards else "",qa_card,layout["id"] if "layout" in locals() else "cached")
  result=publish_reel(url,caption(row)); media_id=result.get("id") if isinstance(result,dict) else None; container_id=result.get("container_id") if isinstance(result,dict) else None
  mark_published(db,item_id,"instagram",url)
  db.update(item_id,instagram_status="published",instagram_media_id=media_id,instagram_container_id=container_id,instagram_selected=0,instagram_published_at=datetime.now(timezone.utc).isoformat(),instagram_error=None,instagram_next_retry_at=None)
  state_transition(db,item_id,"INSTAGRAM_PUBLISHED")
  audit_stage(db,item_id,"INSTAGRAM","completed",{"media_id":media_id})
  return True
 except InstagramRateLimitError as exc:
  retry_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
  db.update(item_id,instagram_status="pending",instagram_error=str(exc)[:3000],instagram_next_retry_at=retry_at)
  print(f"Instagram app rate limit reached; pausing this worker run for item {item_id}: {exc}")
  return "rate_limited"
 except Exception as exc:
  self_heal(db,"instagram","reel_publish",exc,item_id,attempts)
  db.update(item_id,instagram_status="failed",instagram_error=str(exc)[:3000],instagram_next_retry_at=_next_retry(attempts)); print(f"Instagram failed item {item_id}: {exc}"); return False

def process_instagram(db,row,music):
 item_id=int(row["id"])
 run_id,started=agent_start(db,"instagram","publish_reel",item_id,{"title":str(row.get("title") or "")[:180]})
 try:
  result=_process_instagram_untracked(db,row,music)
  agent_finish(db,run_id,started,result is True, None if result is True else str(row.get("instagram_error") or result))
  return result
 except Exception as exc:
  agent_finish(db,run_id,started,False,exc)
  raise

def repair_published_content(db,limit):
 if limit<=0:return 0
 rows=[dict(r) for r in db.latest(max(limit*12,limit),status="published") if _needs_content_repair(r)][:limit]; repaired=0
 for row in rows:
  if process_content(db,row):repaired+=1
 return repaired

def _schedule_due(row,now):
 raw=row.get("instagram_scheduled_at")
 if not raw:return True
 try:
  due=datetime.fromisoformat(str(raw).replace("Z","+00:00")); due=due if due.tzinfo else due.replace(tzinfo=timezone.utc); return due<=now
 except ValueError:return False

def _retry_due(row,now):
 if int(row.get("instagram_attempts") or 0)>=MAX_INSTAGRAM_ATTEMPTS:return False
 raw=row.get("instagram_next_retry_at")
 if not raw:return True
 try:due=datetime.fromisoformat(str(raw).replace("Z","+00:00")); due=due if due.tzinfo else due.replace(tzinfo=timezone.utc); return due<=now
 except ValueError:return False

def _today_bounds():
 tz=ZoneInfo("Asia/Kolkata"); today=datetime.now(tz).date(); start=datetime.combine(today,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc); return start,start+timedelta(days=1)

def _minutes_since_last(db,now):
 raw=db.instagram_last_published_at()
 if not raw:return None
 try:last=datetime.fromisoformat(str(raw).replace("Z","+00:00")); last=last if last.tzinfo else last.replace(tzinfo=timezone.utc); return max(0,(now-last).total_seconds()/60)
 except ValueError:return None

def _instagram_candidates(db,mode,limit,now):
 if limit<=0:return []
 # Phone/Instagram-only workers may intentionally leave website items in "pending".
 # Instagram should still be able to consume those queued stories.
 rows=[dict(r) for r in db.latest(max(limit*20,100),status="all",instagram_status="pending")]
 rows=[r for r in rows if r.get("status") in {"pending","published"} and _schedule_due(r,now)]
 if mode=="manual":rows=[r for r in rows if int(r.get("instagram_selected") or 0)==1]
 for r in rows:
  try:
   s=db.conn.execute("SELECT score,breaking FROM ph_news_scores WHERE item_id="+("%s" if db._postgres else "?"),(int(r["id"]),)).fetchone()
   r["_upgrade_score"]=float(s["score"] if s else 0); r["_upgrade_breaking"]=bool(s["breaking"] if s else 0)
  except Exception:
   r["_upgrade_score"]=0; r["_upgrade_breaking"]=False
rows.sort(key=lambda r:(0 if r.get("_upgrade_breaking") else 1,0 if r.get("instagram_scheduled_at") else 1,-float(r.get("_upgrade_score") or 0),int(r.get("instagram_queue_order") or 0) if int(r.get("instagram_queue_order") or 0)>0 else 10**9,-int(r.get("id") or 0)))
 return rows[:limit]

def main():
 db=NewsDatabase(); ensure_schema(db); ensure_upgrade_schema(db); settings=db.get_settings(); env_ig=os.getenv("PUBLISH_TO_INSTAGRAM","false").lower() in {"1","true","yes"}; env_web=os.getenv("PUBLISH_WEBSITE","true").lower() in {"1","true","yes"}; priority_id=str(settings.get("instagram_priority_id","") or "").strip(); paused=settings.get("instagram_paused","false")=="true"; publish_instagram=env_ig and (settings.get("instagram_enabled","true")=="true" or bool(priority_id)); publish_website=env_web and settings.get("website_enabled","true")=="true"
 try:max_items=max(1,int(os.getenv("MAX_ITEMS","15")))
 except ValueError:max_items=15
 try:repair_items=max(0,int(os.getenv("BOT_REPAIR_ITEMS","5")))
 except ValueError:repair_items=5
 try:retry_limit=max(0,int(os.getenv("INSTAGRAM_RETRY_ITEMS","10")))
 except ValueError:retry_limit=10
 try:admin_daily=max(0,int(settings.get("instagram_daily_limit","1000")))
 except ValueError:admin_daily=1000
 try:env_daily=max(0,int(os.getenv("INSTAGRAM_NEW_ITEMS","1000")))
 except ValueError:env_daily=1000
 try:interval=max(0,int(os.getenv("INSTAGRAM_INTERVAL_MINUTES",settings.get("instagram_interval_minutes","0"))))
 except ValueError:interval=0
 daily_limit=min(admin_daily,env_daily) if env_daily else admin_daily; now=datetime.now(timezone.utc); music=audio_path() if publish_instagram else None; pending=[dict(r) for r in db.latest(max_items,status="pending")] if publish_website else []
 published=held=0
 for row in pending:
  # Always regenerate pending content from the freshest source. If the newsroom
  # processor rejects a very short alert, fall back to cleaned source wording.
  duplicate=find_duplicate_story(db,int(row["id"]),row.get("title") or "")
  if duplicate:
   audit_stage(db,int(row["id"]),"DUPLICATE_CHECK","flagged",{"similarity":round(duplicate[0],3),"existing_id":duplicate[1].get("id")})
  p="%s" if db._postgres else "?"
  vr=db.conn.execute("SELECT source_name FROM ph_cluster_items WHERE news_item_id="+p,(int(row["id"]),)).fetchall()
  names=[str(x["source_name"]) for x in vr]
  classification=record_verification(db,int(row["id"]),len(names),names,[])
  event_id=attach_event(db,int(row["id"]),row.get("title") or "",row.get("category") or "general",row.get("source_name") or (names[0] if names else ""))
  score_story(db,row,len(names),classification,round(duplicate[0]*100,2) if duplicate else 0)
  for source in names or ([row.get("source_name")] if row.get("source_name") else []):
   record_source(db,source,success=True,coverage=len(names)>=2)
  audit_stage(db,int(row["id"]),"VERIFICATION","completed",{"classification":classification,"source_count":len(names)})
  state_transition(db,int(row["id"]),"COLLECTED")
  route=manager_route(row.get("title") or "",row.get("category") or "general",bool(row.get("image_url")))
  with agent_run(db, "manager", "route_story", int(row["id"]), {"route":route}):
   pass
  with agent_run(db, "writer", "prepare_story", int(row["id"]), {"route":route}):
   ready=prepare_content(db,row)
  if not ready:held+=1; print(f"Website publish held for item {row['id']}: no usable source text"); continue
  if not publish_lock(db,int(row["id"]),event_id):
   held+=1; audit_stage(db,int(row["id"]),"PUBLISH_LOCK","blocked",{"story_key":event_id}); print(f"Website duplicate lock blocked item {row['id']}"); continue
  with agent_run(db, "publisher", "publish_website", int(row["id"])):
   publish_website_first(db,row,now.isoformat())
   mark_published(db,int(row["id"]),"website")
  published+=1
 repaired=repair_published_content(db,repair_items); attempted=set(); priority_handled=False
 if publish_instagram:
  _recover_stale_processing(db,now)
  if priority_id:
   priority_row=next((dict(r) for r in db.latest(1000,status="published",instagram_status="all") if str(r["id"])==priority_id),None)
   if priority_row and priority_row.get("instagram_status")!="published":
    ok=process_instagram(db,priority_row,music); attempted.add(int(priority_row["id"])); priority_handled=True
    if ok=="rate_limited": return
    if ok:db.set_settings({"instagram_priority_id":"","instagram_paused":"false"}); priority_id=""; paused=False
    else:
     print(f"Instagram priority item {priority_id} failed; continuing normal queue")
     db.set_settings({"instagram_priority_id":""}); priority_id=""
   else:db.set_settings({"instagram_priority_id":"","instagram_paused":"false"}); priority_id=""; paused=False
  if not priority_id and not paused and daily_limit>0 and not priority_handled:
   start,end=_today_bounds(); remaining=max(0,daily_limit-db.instagram_daily_count(start.isoformat(),end.isoformat())); since=_minutes_since_last(db,now); slot_open=since is None or since>=interval
   if remaining>0 and slot_open:
    mode=settings.get("instagram_selection_mode","auto")
    # No artificial one-Reel-per-run bottleneck when interval is set to 0.
    # Limit each scheduled run to a small batch so Meta is not hammered by a backlog.
    try:max_run=max(1,int(os.getenv("INSTAGRAM_MAX_PER_RUN","5")))
    except ValueError:max_run=5
    slots=min(remaining,max_run)
    while slots>0:
     candidates=_instagram_candidates(db,mode,1,now)
     if candidates:
      row=candidates[0]
      if int(row["id"]) in attempted:break
      ok=process_instagram(db,row,music); attempted.add(int(row["id"])); slots-=1
      if ok=="rate_limited": break
      continue
     if retry_limit:
      retry_row=next((dict(r) for r in db.latest(retry_limit,status="published",instagram_status="failed") if int(r["id"]) not in attempted and _retry_due(r,now)),None)
      if retry_row:
       ok=process_instagram(db,retry_row,music); attempted.add(int(retry_row["id"])); slots-=1
       if ok=="rate_limited": break
       continue
     break
   else:print(f"Instagram slot closed: last_publish_minutes={since}, interval={interval}, remaining_today={remaining}")
  elif paused and not priority_id:print("Instagram queue paused by admin")
 print(f"Website published={published}; held_for_bot={held}; repaired={repaired}; Instagram enabled={publish_instagram}; paused={paused}; priority={priority_id or 'none'}; attempted={len(attempted)}"); db.close()

if __name__=="__main__":main()
