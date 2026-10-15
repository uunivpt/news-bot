from __future__ import annotations
import os, re, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase
from app.news_text import clean_news_text
from app.newsroom import process_news, validate_news_copy
from app.publish_policy import risk_flags
from app.phase_system import ensure_schema, run as agent_run, quality_gate, manager_route
from app.advanced_ops import audit_stage, state_transition, record_verification, find_duplicate_story
from app.advanced_system import ensure_schema as ensure_upgrade_schema, score_story, attach_event, publish_lock, mark_published, record_source

TRAILING_FRAGMENT_RE=re.compile(r"\b(?:a|an|and|as|at|by|for|from|in|including|into|of|on|or|the|their|this|to|under|via|was|were|with|without)\.?$",re.I)

SHORT_FINAL_TOKEN_RE=re.compile(r"\b[a-zA-Z]{1,2}\.$")

KNOWN_SHORT_ENDINGS={"US.","UK.","EU.","UN.","AI.","PM.","MP.","CM.","UP.","U.S.","U.K."}

def _bad_fragment(text):
 value=re.sub(r"\s+"," ",text or "").rstrip()
 if not value:return True
 if TRAILING_FRAGMENT_RE.search(value):return True
 match=SHORT_FINAL_TOKEN_RE.search(value)
 return bool(match and match.group(0) not in KNOWN_SHORT_ENDINGS)

def _process_content(db,row):
 try:
  source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or "")
  material=source.get("text") or row.get("summary") or row.get("title") or ""
  result=process_news(row.get("title") or "",material,row.get("category") or "general")
  if not result:return False
  fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"],"ai_summary":result.get("ai_summary") or None,"ai_article":result.get("ai_article") or None}
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
 # Do not turn captions, emoji-only posts or one-line fragments into thin
 # website articles. They stay unprocessed until usable source material exists.
 title=clean_news_text(row.get("title") or "",row.get("source_name") or "")
 raw=row.get("summary") or row.get("title") or ""
 summary=clean_news_text(raw,row.get("source_name") or "")
 if not title or not summary:return False
 title_words=[w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*",title) if w]
 summary_words=[w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*",summary) if w]
 if len(title_words)<3 or len(summary_words)<7 or len(summary)<35:
  return False
 article=summary
 copy_qa=validate_news_copy(title,summary,article)
 if not copy_qa["passed"]:
  print(f"Direct fallback blocked by copy completeness for item {row.get('id')}: {copy_qa['errors']}")
  return False
 qa=quality_gate(title,summary,article,allow_short=True)
 if not qa["passed"]:
  print(f"Direct fallback blocked by quality gate for item {row.get('id')}: {qa['errors']}")
  return False
 return {"title":title,"summary":summary,"bot_summary":summary,"bot_article":article}

def prepare_content(db,row):
 fields=_process_content(db,row)
 if fields:
  db.update(int(row["id"]),**fields)
  row.update(fields)
  return True
 fallback=_direct_fallback_content(row)
 if not fallback:return False
 db.update(int(row["id"]),**fallback); row.update(fallback)
 print(f"Using direct source fallback for short item {row['id']}")
 return True

def process_content(db,row):
 return prepare_content(db,row)

def _needs_content_repair(row):
 title=str(row.get("title") or "").strip()
 summary=str(row.get("bot_summary") or row.get("summary") or "").strip()
 article=str(row.get("bot_article") or "").strip()
 if not article or not summary:return True
 if title.endswith(("…","...")) or len(title.split())>18:return True
 if _bad_fragment(summary) or _bad_fragment(article):return True
 copy_qa=validate_news_copy(title,summary,article)
 return not copy_qa["passed"]

def publish_website_first(db,row,now):
 # Website policy: display only images supplied by the originating source.
 # Do not search/acquire replacement images for text-only source stories.
 flags=risk_flags(row["title"],row.get("bot_summary") or row.get("summary") or ""); review="reviewed" if row.get("source_type")=="x" and row.get("fact_check_status")=="reviewed" else ("needs_review" if flags else "pending")
 db.update(int(row["id"]),status="published",published_at_site=now,fact_check_status=review,fact_check_notes=", ".join(flags) if flags else None); row["status"]="published"; return row

def repair_published_content(db,limit):
 if limit<=0:return 0
 rows=[dict(r) for r in db.latest(max(limit*12,limit),status="published") if _needs_content_repair(r)][:limit]; repaired=0
 for row in rows:
  # Repair body fields only. Never silently rewrite an already-published title.
  if str(row.get("fact_check_status") or "").lower() in {"reviewed","approved"}:
   continue
  fields=_process_content(db,row)
  if fields:
   fields.pop("title",None)
   db.update(int(row["id"]),**fields)
   repaired+=1
 return repaired

def _website_candidates(db,limit):
 # Always work from the newest collected stories so a large historical pending
 # backlog can never hide today's news. Reserve part of each batch for India
 # while still leaving room for other desks.
 limit=max(1,int(limit))
 pool=[dict(r) for r in db.latest(max(100,limit*8),status="pending")]
 india_quota=max(1,min(5,limit//3))
 india=[r for r in pool if str(r.get("category") or "").strip().lower()=="india"][:india_quota]
 selected_ids={int(r["id"]) for r in india}
 selected=list(india)
 for row in pool:
  if int(row["id"]) in selected_ids:continue
  selected.append(row)
  if len(selected)>=limit:break
 return selected[:limit]

def main():
 db=NewsDatabase(); ensure_schema(db); ensure_upgrade_schema(db)
 settings=db.get_settings()
 publish_website=os.getenv("PUBLISH_WEBSITE","true").lower() in {"1","true","yes"} and settings.get("website_enabled","true")=="true"
 try:max_items=max(1,int(os.getenv("MAX_ITEMS","15")))
 except ValueError:max_items=15
 try:repair_items=max(0,int(os.getenv("BOT_REPAIR_ITEMS","5")))
 except ValueError:repair_items=5
 now=datetime.now(timezone.utc)
 pending=_website_candidates(db,max_items) if publish_website else []
 published=held=0
 for row in pending:
  if row.get("source_type")=="x" and row.get("fact_check_status")!="reviewed":
   held+=1
   print(f"X story {row['id']} held for source/context review")
   continue
  # Always regenerate pending content from the freshest source. If the newsroom
  # processor rejects a very short alert, fall back to cleaned source wording.
  duplicate=find_duplicate_story(db,int(row["id"]),row.get("title") or "")
  if duplicate:
   audit_stage(db,int(row["id"]),"DUPLICATE_CHECK","flagged",{"similarity":round(duplicate[0],3),"existing_id":duplicate[1].get("id")})
  p="%s" if db._postgres else "?"
  cluster_row=db.conn.execute("SELECT cluster_id FROM ph_cluster_items WHERE news_item_id="+p+" ORDER BY created_at DESC LIMIT 1",(int(row["id"]),)).fetchone()
  if cluster_row:
   vr=db.conn.execute("SELECT source_name FROM ph_cluster_items WHERE cluster_id="+p+" ORDER BY created_at ASC",(cluster_row["cluster_id"],)).fetchall()
  else:
   vr=[]
  names=list(dict.fromkeys(str(x["source_name"]) for x in vr if str(x["source_name"] or "").strip()))
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
 repaired=repair_published_content(db,repair_items)
 print(f"Website published={published}; held_for_bot={held}; repaired={repaired}")
 db.close()

if __name__=="__main__":main()
