# Production deployment marker: deterministic newsroom + public source attribution.
from __future__ import annotations

import json, os, re, secrets, time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase
from app.models import NewsItem
from app.factcheck import run_cross_source_check
from app.newsroom import process_news
from app.worker import dispatch_worker
from app.phase_system import analytics as phase_analytics, cluster_stories, cluster_summary, train as train_agent
from app.reporting import operations_pdf
from app.advanced_ops import ensure_advanced_schema, live_dashboard, detailed_report, record_verification, classify_verification, audit_stage, duplicate_similarity
from app.advanced_system import admin_snapshot, historical_analytics, event_timeline, ensure_schema as ensure_upgrade_schema

app=Flask(__name__, static_folder="../public", static_url_path="")
_secret=os.getenv("FLASK_SECRET_KEY") or os.getenv("ADMIN_TOKEN") or os.getenv("ADMIN_SETUP_KEY")
if not _secret:_secret=secrets.token_urlsafe(32)
app.secret_key=_secret
app.config.update(SESSION_COOKIE_NAME="politicshub_admin_session",SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_PATH="/",SESSION_COOKIE_REFRESH_EACH_REQUEST=False)
_LOGIN_WINDOW_SECONDS=300; _LOGIN_MAX_FAILURES=8; _SETUP_MAX_FAILURES=5; _login_failures={}


def _ensure_admin_users(database):
 database.conn.execute("CREATE TABLE IF NOT EXISTS admin_users (username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'owner',created_at TEXT NOT NULL)")
 if not database._postgres:database.conn.commit()

def _bootstrap_news_snapshot(database):
 try:
  if database.count() != 0:return 0
  path=Path(app.static_folder or "public") / "news-data.json"
  if not path.exists():return 0
  payload=json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(payload,list):return 0
  imported=0
  for item in payload[:500]:
   if not isinstance(item,dict) or not item.get("title") or not item.get("url"):continue
   news=NewsItem(
    source_name=str(item.get("source_name") or "PoliticsHub"),
    source_type=str(item.get("source_type") or "snapshot"),
    title=str(item.get("title")),
    url=str(item.get("url")),
    published_at=item.get("published_at"),
    summary=str(item.get("summary") or ""),
    external_id=None,
    category=str(item.get("category") or "general"),
    image_url=item.get("image_url"),
    public_source=bool(item.get("public_source")),
   )
   if not database.insert(news):continue
   ph="%s" if database._postgres else "?"
   row=database.conn.execute("SELECT id FROM news_items WHERE url = "+ph+" ORDER BY id DESC LIMIT 1",(news.url,)).fetchone()
   if not row:continue
   item_id=int(row["id"] if database._postgres else row[0])
   database.update(item_id,
    status="published",
    bot_summary=str(item.get("bot_summary") or item.get("summary") or ""),
    bot_article=str(item.get("bot_article") or ""),
    published_at_site=item.get("published_at_site") or item.get("published_at"),
    fact_check_status="pending",
   )
   imported+=1
  return imported
 except Exception as exc:
  print(f"News snapshot bootstrap skipped: {exc}")
  return 0

def db():
 database=NewsDatabase(); _ensure_admin_users(database); _bootstrap_news_snapshot(database); return database

def admin_ok():
 if session.get("admin_user"):return True
 token=os.getenv("ADMIN_TOKEN",""); supplied=request.headers.get("X-Admin-Token",""); return bool(token and supplied and secrets.compare_digest(supplied,token))

def require_admin():return None if admin_ok() else (jsonify({"error":"admin authentication required"}),401)
def require_csrf():
 if not session.get("admin_user"):return None
 token=request.headers.get("X-CSRF-Token",""); expected=session.get("csrf_token",""); return None if token and expected and secrets.compare_digest(token,expected) else (jsonify({"error":"invalid CSRF token"}),403)

def _strip_promo_nav(value):
 r=str(value or "")
 r=re.sub(r"\b(?:socials|donate|advertising)\b(?:\s*[|•·/,-]\s*\b(?:socials|donate|advertising)\b)*"," ",r,flags=re.I)
 return re.sub(r"\s{2,}"," ",r).strip(" |•·/-")

def _publicize(row):
 r=dict(row)
 if not admin_ok():
  # Public readers may see the originating source and its public article URL.
  # Internal moderation, Instagram state, hashes and processing fields stay private.
  for key in ("normalized_url","external_id","url_hash","title_hash","collected_at","fact_check_status","fact_check_notes","approved_at","instagram_status","instagram_media_id","instagram_error","instagram_published_at","instagram_attempts","instagram_last_attempt_at","instagram_next_retry_at","instagram_scheduled_at","instagram_queue_order","instagram_container_id","reel_cloudinary_public_id","instagram_selected","ai_summary","ai_article","bot_summary","bot_article","published_at_site"):
   r.pop(key,None)
  raw=dict(row).get("published_at_site") or dict(row).get("published_at")
  if raw:
   try:
    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc); r["published_at"]=dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M")
   except ValueError:pass
  r["title"]=_strip_promo_nav(r.get("title")); r["summary"]=_strip_promo_nav(dict(row).get("bot_summary") or dict(row).get("summary") or ""); r["article"]=_strip_promo_nav(dict(row).get("bot_article") or dict(row).get("bot_summary") or dict(row).get("summary") or "")
 return r

def rows_json(rows,compact=False):
 out=[]
 for row in rows:
  if not (admin_ok() or row.get("status")=="published"):continue
  item=_publicize(row)
  if compact and admin_ok():
   item={k:item.get(k) for k in ("id","title","source_name","category","status","instagram_status","instagram_attempts","instagram_error","instagram_selected","instagram_scheduled_at","instagram_queue_order","fact_check_status","bot_summary")}
  out.append(item)
 return out
def users():
 try:return json.loads(os.getenv("ADMIN_USERS_JSON","{}"))
 except Exception:return {}
def _client_key():return (request.remote_addr or "unknown").strip()
def _auth_key(username):return "login:user:"+str(username).strip().lower()[:128]
def _setup_key():return "setup:global"
def _auth_allowed(database,attempt_key,maximum):
 now=datetime.now(timezone.utc); since=(now-timedelta(seconds=_LOGIN_WINDOW_SECONDS)).isoformat(); return database.login_failures(attempt_key,since)<maximum
def _auth_failed(database,attempt_key):database.record_login_failure(attempt_key,datetime.now(timezone.utc).isoformat())
def _auth_clear(database,attempt_key):database.clear_login_failures(attempt_key)
def _india_day_bounds():
 tz=ZoneInfo("Asia/Kolkata"); today=datetime.now(tz).date(); start=datetime.combine(today,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc); return start.isoformat(),(start+timedelta(days=1)).isoformat()

def log_admin(database,action,item_id=None,details=None):
 try:database.log_activity(session.get("admin_user") or "token",action,item_id,details)
 except Exception:pass

@app.after_request
def security_headers(response):
 response.headers["X-Content-Type-Options"]="nosniff"
 response.headers["X-Frame-Options"]="DENY"
 response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
 response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=(), payment=(), usb=()"
 response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
 response.headers["Content-Security-Policy"]="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; media-src 'self' https:; font-src 'self' data:; connect-src 'self'; frame-src 'none'; worker-src 'self'; upgrade-insecure-requests"
 response.headers["Cross-Origin-Opener-Policy"]="same-origin"
 response.headers["Cross-Origin-Resource-Policy"]="same-origin"
 response.headers["X-Permitted-Cross-Domain-Policies"]="none"
 if request.path.startswith("/api/admin"):response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
 return response

@app.post("/api/admin/setup")
def setup_owner():
 if session.get("admin_user"):return jsonify({"error":"owner setup is disabled after sign-in"}),403
 key=os.getenv("ADMIN_SETUP_KEY","").strip() or os.getenv("ADMIN_TOKEN","").strip(); body=request.get_json(silent=True) or request.form.to_dict() or {}
 if not key:return jsonify({"error":"owner setup is disabled; configure ADMIN_SETUP_KEY or ADMIN_TOKEN first"}),503
 if not secrets.compare_digest(str(body.get("setup_key","")),key):return jsonify({"error":"invalid setup key"}),403
 username=str(body.get("username","")).strip(); password=str(body.get("password",""))
 if len(username)<3 or len(username)>40 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in username):return jsonify({"error":"invalid username"}),400
 if len(password)<12:return jsonify({"error":"password must be at least 12 characters"}),400
 database=db()
 try:
  count=int(database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()["count"] if database._postgres else database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()[0])
  if count:return jsonify({"error":"owner already exists; setup is permanently closed"}),409
  now=datetime.now(timezone.utc).isoformat(); ph="%s" if database._postgres else "?"; database.conn.execute(f"INSERT INTO admin_users (username,password_hash,role,created_at) VALUES ({ph},{ph},{ph},{ph})",(username,generate_password_hash(password),"owner",now));
  if not database._postgres:database.conn.commit()
  session.clear(); session["admin_user"]=username; session["admin_role"]="owner"; session["csrf_token"]=secrets.token_urlsafe(32); return jsonify({"ok":True,"username":username,"role":"owner","csrf_token":session["csrf_token"]})
 finally:database.close()

@app.post("/api/admin/login")
def login():
 if not _login_allowed():return jsonify({"error":"too many login attempts; try again later"}),429
 body=request.get_json(silent=True) or request.form.to_dict() or {}; username=str(body.get("username","")).strip(); password=str(body.get("password","")); database=db(); valid=False; role=None
 try:
  ph="%s" if database._postgres else "?"; row=database.conn.execute("SELECT username,password_hash,role FROM admin_users WHERE username = "+ph,(username,)).fetchone(); valid=bool(row and check_password_hash(row["password_hash"] if database._postgres else row[1],password)); role=(row["role"] if database._postgres else row[2]) if row else None
  if not valid and username=="admin":
   count=int(database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()["count"] if database._postgres else database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()[0]); bootstrap=os.getenv("ADMIN_SETUP_KEY","") or os.getenv("ADMIN_TOKEN","")
   if count==0 and bootstrap and secrets.compare_digest(password,bootstrap):
    now=datetime.now(timezone.utc).isoformat(); database.conn.execute(f"INSERT INTO admin_users (username,password_hash,role,created_at) VALUES ({ph},{ph},{ph},{ph})",("admin",generate_password_hash(password),"owner",now)); valid=True; role="owner"
 finally:database.close()
 if not valid:
  record=users().get(username); valid=bool(record and check_password_hash(record,password)); role="owner" if valid else None
 if not valid:_login_failed(); return jsonify({"error":"invalid credentials"}),401
 _login_failures.pop(_client_key(),None); session.clear(); session["admin_user"]=username; session["admin_role"]=role or "owner"; session["csrf_token"]=secrets.token_urlsafe(32); return jsonify({"ok":True,"username":username,"role":session["admin_role"],"csrf_token":session["csrf_token"]})

@app.post("/api/admin/logout")
def logout():
 err=require_csrf()
 if err:return err
 session.clear(); return jsonify({"ok":True})

@app.get("/api/admin/me")
def me():return jsonify({"authenticated":bool(session.get("admin_user")),"username":session.get("admin_user"),"role":session.get("admin_role"),"csrf_token":session.get("csrf_token") if session.get("admin_user") else None})

@app.get("/api/health")
def health():
 database=db()
 try:return jsonify({"ok":True})
 finally:database.close()

@app.get("/api/news")
def news():
 category=request.args.get("category","all"); status=request.args.get("status","published"); review=request.args.get("review_status","all"); ig=request.args.get("instagram_status","all"); search=request.args.get("search"); compact=request.args.get("compact","0")=="1"
 try:limit=min(max(int(request.args.get("limit","100")),1),100)
 except ValueError:limit=100
 if not admin_ok():status,review,ig="published","all","all"
 database=db()
 try:return jsonify(rows_json(database.latest(limit,category,status,search,review,ig),compact=compact))
 finally:database.close()

@app.get("/api/news/<int:item_id>")
def article(item_id):
 database=db()
 try:
  row=next((dict(r) for r in database.latest(1000,status="all") if int(r["id"])==item_id),None)
  if not row or (row["status"]!="published" and not admin_ok()):return jsonify({"error":"not found"}),404
  return jsonify(_publicize(row))
 finally:database.close()

@app.get("/api/stats")
def stats():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds(); return jsonify({"total":database.count(),"pending":len(database.latest(100,"all","pending")),"review_needed":len(database.latest(100,"all","published",None,"needs_review")),"published":len(database.latest(100,"all","published")),"instagram_failed":len(database.latest(100,"all","published",None,"all","failed")),"instagram_today":database.instagram_daily_count(a,b),"instagram_limit":int(settings.get("instagram_daily_limit","5")),"instagram_interval_minutes":int(settings.get("instagram_interval_minutes","0")),"instagram_enabled":settings.get("instagram_enabled","true")=="true","instagram_paused":settings.get("instagram_paused","false")=="true","instagram_priority_id":settings.get("instagram_priority_id",""),"website_enabled":settings.get("website_enabled","true")=="true"})
 finally:database.close()


@app.get("/api/admin/dashboard")
def admin_dashboard():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds();
  payload={"settings":settings,"stats":{"total":database.count(),"pending":len(database.latest(100,"all","pending")),"review_needed":len(database.latest(100,"all","published",None,"needs_review")),"published":len(database.latest(100,"all","published")),"instagram_failed":len(database.latest(100,"all","published",None,"all","failed")),"instagram_today":database.instagram_daily_count(a,b),"instagram_limit":int(settings.get("instagram_daily_limit","5")),"instagram_interval_minutes":int(settings.get("instagram_interval_minutes","0")),"instagram_enabled":settings.get("instagram_enabled","true")=="true","instagram_paused":settings.get("instagram_paused","false")=="true","instagram_priority_id":settings.get("instagram_priority_id",""),"website_enabled":settings.get("website_enabled","true")=="true"}, "activity":rows_json(database.recent_activity(20))}
  payload["settings"]["instagram_today"]=str(payload["stats"]["instagram_today"]); payload["settings"]["instagram_last_published_at"]=database.instagram_last_published_at() or ""
  return jsonify(payload)
 finally:database.close()

@app.get("/api/admin/health")
def admin_health():
 err=require_admin()
 if err:return err
 database=db()
 try:
  s=database.get_settings(); worker_ready=bool(os.getenv("WORKFLOW_TOKEN", "").strip() or os.getenv("GITHUB_WORKFLOW_TOKEN", "").strip()); instagram_marker=os.getenv("INSTAGRAM_WORKER_CONFIGURED", "").strip().lower()=="true"; return jsonify({"ok":True,"database":"connected","instagram":{"configured":bool(worker_ready or instagram_marker or os.getenv("META_ACCESS_TOKEN", "").strip()),"credentials_source":"github_actions" if worker_ready and not os.getenv("META_ACCESS_TOKEN", "").strip() else ("vercel" if os.getenv("META_ACCESS_TOKEN", "").strip() else "marker"),"enabled":s.get("instagram_enabled","true")=="true","paused":s.get("instagram_paused","false")=="true"},"worker_dispatch_configured":worker_ready,"website_enabled":s.get("website_enabled","true")=="true","news_count":database.count()})
 finally:database.close()

@app.get("/api/admin/activity")
def admin_activity():
 err=require_admin()
 if err:return err
 database=db()
 try:return jsonify([dict(r) for r in database.recent_activity(request.args.get("limit",50))])
 finally:database.close()

@app.get("/api/admin/instagram/analytics")
def instagram_analytics():
 err=require_admin()
 if err:return err
 database=db()
 try:
  now=datetime.now(timezone.utc); start=now-timedelta(days=7); rows=[dict(r) for r in database.latest(500,"all","published")]; published=[r for r in rows if r.get("instagram_status")=="published"]
  daily={};
  for row in published:
   raw=row.get("instagram_published_at")
   if raw:
    try:day=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat(); daily[day]=daily.get(day,0)+1
    except ValueError:pass
  recent=[{"id":r["id"],"title":r["title"],"published_at":r.get("instagram_published_at"),"media_id":r.get("instagram_media_id")} for r in published[:20]]
  return jsonify({"last_7_days":{k:v for k,v in daily.items() if k>=start.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()},"total_published":len(published),"failed":len([r for r in rows if r.get("instagram_status")=="failed"]),"processing":len([r for r in rows if r.get("instagram_status")=="processing"]),"queued":len([r for r in rows if r.get("instagram_status")=="pending" and int(r.get("instagram_selected") or 0)==1]),"recent":recent})
 finally:database.close()

@app.get("/api/admin/live")
def admin_live():
 err=require_admin()
 if err:return err
 database=db()
 try:
  ensure_advanced_schema(database)
  return jsonify(live_dashboard(database))
 finally: database.close()

@app.get("/api/admin/upgrade")
def admin_upgrade():
 err=require_admin()
 if err:return err
 database=db()
 try:
  ensure_upgrade_schema(database)
  snapshot=admin_snapshot(database)
  event_id=str(request.args.get("event_id","")).strip()
  if event_id:
   snapshot["event_timeline"]=event_timeline(database,event_id)
  else:
   snapshot["event_timeline"]=[]
  return jsonify(snapshot)
 finally: database.close()

@app.get("/api/admin/history")
def admin_history():
 err=require_admin()
 if err:return err
 try: days=max(1,min(int(request.args.get("days","30")),365))
 except ValueError: days=30
 database=db()
 try:
  ensure_upgrade_schema(database)
  return jsonify(historical_analytics(database,days))
 finally: database.close()

@app.get("/api/admin/report")
def admin_detailed_report():
 err=require_admin()
 if err:return err
 try: days=max(1,min(int(request.args.get("days","7")),90))
 except ValueError: days=7
 database=db()
 try:
  payload=detailed_report(database,days)
  payload["generated_at"]=datetime.now(timezone.utc).isoformat()
  return jsonify(payload)
 finally: database.close()

@app.post("/api/admin/verification/<int:item_id>")
def admin_verify(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}
 database=db()
 try:
  classification=record_verification(database,item_id,int(body.get("source_count",0)),body.get("source_names") or [],body.get("conflicts") or [])
  audit_stage(database,item_id,"VERIFICATION","completed",{"classification":classification})
  return jsonify({"ok":True,"classification":classification})
 finally: database.close()

@app.get("/api/admin/operations")
def admin_operations():
 err=require_admin()
 if err:return err
 database=db()
 try:
  cluster_stories(database,250)
  with __import__("app.phase_system",fromlist=["run"]).run(database,"reporting","generate_operations_report"):
   ops=phase_analytics(database,7)
  recent_errors=[dict(r) for r in database.conn.execute("SELECT agent_id,operation,error,started_at FROM ph_agent_runs WHERE status='failed' ORDER BY id DESC LIMIT 20").fetchall()]
  # Instagram failures are stored on news_items as well as agent telemetry. Surface them
  # in the Command Center so a failed Reel never looks like a silent queue stall.
  instagram_errors=[dict(r) for r in database.conn.execute("SELECT id,title,instagram_error,instagram_status,instagram_attempts,instagram_last_attempt_at FROM news_items WHERE instagram_error IS NOT NULL AND instagram_error <> '' ORDER BY id DESC LIMIT 20").fetchall()]
  for item in instagram_errors:
   recent_errors.append({
    "agent_id":"instagram",
    "operation":"publish_reel",
    "error":f"#{item.get('id')} {item.get('title')}: {item.get('instagram_error')}",
    "started_at":item.get("instagram_last_attempt_at") or ""
   })
  recent_errors=recent_errors[-20:]
  clusters=cluster_summary(database)
  total=database.count()
  published=len(database.latest(1000,"all","published"))
  published_rows=[dict(r) for r in database.latest(1000,"all","published")]
  with_article=len([r for r in published_rows if r.get("bot_article")])
  images=len([r for r in published_rows if r.get("image_url")])
  ops["content_quality"]={"published":published,"with_article":with_article,"article_coverage_percent":round(with_article/published*100,1) if published else None,"with_image":images,"image_coverage_percent":round(images/published*100,1) if published else None,"cluster_count":len(clusters)}
  ops["recent_errors"]=recent_errors
  return jsonify(ops)
 finally:database.close()

@app.get("/api/admin/operations.pdf")
def admin_operations_pdf():
 err=require_admin()
 if err:return err
 database=db()
 try:
  pdf=operations_pdf(database,7)
  from flask import Response
  return Response(pdf,mimetype="application/pdf",headers={"Content-Disposition":"attachment; filename=politicshub-operations-report.pdf","Cache-Control":"no-store"})
 finally:database.close()

@app.post("/api/admin/training")
def admin_training():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}
 agent_id=str(body.get("agent_id","")).strip()
 notes=str(body.get("notes","")).strip()
 if not agent_id or agent_id not in __import__("app.phase_system",fromlist=["AGENTS"]).AGENTS:return jsonify({"error":"unknown agent"}),400
 database=db()
 try:
  with __import__("app.phase_system",fromlist=["run"]).run(database,"hr","record_training",metadata={"agent_id":agent_id}):
   train_agent(database,agent_id,str(body.get("event_type") or "knowledge_update"),notes)
  log_admin(database,"agent.training",None,agent_id)
  return jsonify({"ok":True,"agent_id":agent_id})
 finally:database.close()

@app.get("/api/admin/settings")
def admin_settings():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds(); settings["instagram_today"]=str(database.instagram_daily_count(a,b)); settings["instagram_last_published_at"]=database.instagram_last_published_at() or ""; return jsonify(settings)
 finally:database.close()

@app.post("/api/admin/settings")
def save_settings():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; values={}
 for key in ("instagram_enabled","website_enabled","instagram_paused"):
  if key in body:values[key]="true" if bool(body[key]) else "false"
 for key,maximum in (("instagram_daily_limit",100),("instagram_interval_minutes",1440)):
  if key in body:
   try:value=int(body[key])
   except (TypeError,ValueError):return jsonify({"error":f"{key} must be a number"}),400
   if value<0 or value>maximum:return jsonify({"error":f"{key} is out of range"}),400
   values[key]=str(value)
 if "instagram_selection_mode" in body:
  mode=str(body["instagram_selection_mode"]).lower()
  if mode not in {"auto","manual"}:return jsonify({"error":"selection mode must be auto or manual"}),400
  values["instagram_selection_mode"]=mode
 database=db()
 try:database.set_settings(values); settings_now=database.get_settings(); log_admin(database,"settings.update",None,",".join(values.keys()))
 finally:database.close()
 dispatch=dispatch_worker() if any(k.startswith("instagram_") for k in values) else None; payload={"ok":True,"settings":settings_now}
 if dispatch is not None:payload.update({"worker_dispatched":dispatch.get("ok",False),"worker_dispatch":dispatch})
 return jsonify(payload)


def change(item_id,status=None,**extra):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  fields=dict(extra); 
  if status is not None:fields["status"]=status
  database.update(item_id,**fields); log_admin(database,"news.update",item_id,",".join(fields.keys())); return jsonify({"ok":True,**fields})
 finally:database.close()

@app.post("/api/news/<int:item_id>/approve")
def approve(item_id):return change(item_id,fact_check_status="reviewed",approved_at=datetime.now(timezone.utc).isoformat())
@app.post("/api/news/<int:item_id>/reject")
def reject(item_id):return change(item_id,status="rejected",instagram_selected=0)
@app.post("/api/news/<int:item_id>/publish")
def publish(item_id):return change(item_id,status="published",published_at_site=datetime.now(timezone.utc).isoformat())

@app.post("/api/news/<int:item_id>/edit")
def edit_news(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; fields={k:str(body[k] or "").strip() for k in ("title","summary","category","image_url","bot_summary","bot_article") if k in body}
 if not fields:return jsonify({"error":"no editable fields supplied"}),400
 if "title" in fields and not fields["title"]:return jsonify({"error":"title cannot be empty"}),400
 database=db()
 try:database.update(item_id,**fields); log_admin(database,"news.edit",item_id,",".join(fields.keys())); return jsonify({"ok":True,"fields":fields})
 finally:database.close()

@app.post("/api/news/<int:item_id>/process")
def process_item(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  row=next((dict(r) for r in database.latest(1000,status="all") if int(r["id"])==item_id),None)
  if not row:return jsonify({"error":"not found"}),404
  source=enrich_source_text(row.get("title") or "",row.get("summary") or ""); material=source.get("text") or row.get("summary") or row.get("title") or ""; result=process_news(row["title"],material,row.get("category") or "general")
  if not result:return jsonify({"error":"bot could not produce complete content from available material"}),422
  fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"]}
  if source.get("image_url") and not row.get("image_url"):fields["image_url"]=source["image_url"]
  database.update(item_id,**fields); log_admin(database,"news.process",item_id,"deterministic_bot"); return jsonify({"ok":True,"mode":"deterministic_bot","headline":result["headline"],"summary":result["summary"],"article":result["article"]})
 finally:database.close()

@app.post("/api/news/<int:item_id>/ai")
def legacy_process(item_id):return process_item(item_id)

@app.post("/api/news/<int:item_id>/instagram/queue")
def instagram_queue(item_id):
 result=change(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_queue_order=0,instagram_scheduled_at=None)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)
@app.post("/api/news/<int:item_id>/instagram/unqueue")
def instagram_unqueue(item_id):return change(item_id,instagram_selected=0)
@app.post("/api/news/<int:item_id>/instagram/retry")
def instagram_retry(item_id):
 result=change(item_id,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_selected=1)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)

@app.post("/api/admin/instagram/bulk")
def instagram_bulk():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; ids=[]; action=str(body.get("action","")).lower()
 for value in body.get("ids",[]):
  try: ids.append(int(value))
  except (TypeError,ValueError): pass
 ids=list(dict.fromkeys(ids))[:100]
 if action not in {"queue","unqueue","retry","cancel_schedule"}:return jsonify({"error":"unsupported bulk action"}),400
 database=db(); changed=0
 try:
  for item_id in ids:
   row=next((dict(r) for r in database.latest(1000,status="all",instagram_status="all") if int(r["id"])==item_id),None)
   if not row:continue
   if action=="queue":
    order=database.next_instagram_queue_order(); database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_scheduled_at=None,instagram_queue_order=order)
   elif action=="unqueue":database.update(item_id,instagram_selected=0)
   elif action=="retry":database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
   elif action=="cancel_schedule":database.update(item_id,instagram_scheduled_at=None)
   changed+=1
  log_admin(database,"instagram.bulk",None,f"{action}:{changed}")
 finally:database.close()
 dispatch=dispatch_worker() if action in {"queue","retry"} else {"ok":False,"configured":False}
 return jsonify({"ok":True,"changed":changed,"worker_dispatched":dispatch.get("ok",False)})

@app.post("/api/news/<int:item_id>/instagram/publish-now")
def instagram_publish_now(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  row=next((dict(r) for r in database.latest(1000,status="published",instagram_status="all") if int(r["id"])==item_id),None)
  if not row:return jsonify({"error":"published story not found"}),404
  if not row.get("bot_article") or not row.get("bot_summary"):
   source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or ""); material=source.get("text") or row.get("summary") or row.get("title") or ""; result=process_news(row.get("title") or "",material,row.get("category") or "general")
   if not result:return jsonify({"error":"story could not be processed by the newsroom bot"}),422
   fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"]}
   if source.get("image_url") and not row.get("image_url"):fields["image_url"]=source["image_url"]
   database.update(item_id,**fields); row.update(fields); log_admin(database,"news.process",item_id,"auto before Instagram")
  if row.get("instagram_status")=="published":return jsonify({"error":"already published to Instagram"}),409
  database.set_settings({"instagram_priority_id":str(item_id),"instagram_paused":"false"}); database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_scheduled_at=None); log_admin(database,"instagram.priority",item_id,"post_now")
 finally:database.close()
 dispatch=dispatch_worker(); return jsonify({"ok":True,"priority_id":item_id,"queue_paused":True,"worker_dispatched":dispatch.get("ok",False),"worker_dispatch":dispatch})

@app.post("/api/news/<int:item_id>/instagram/schedule")
def instagram_schedule(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; raw=str(body.get("scheduled_at","")).strip()
 if raw:
  try:due=datetime.fromisoformat(raw.replace("Z","+00:00")); due=due if due.tzinfo else due.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
  except ValueError:return jsonify({"error":"invalid scheduled_at; use ISO date/time"}),400
  if due.astimezone(timezone.utc)<=datetime.now(timezone.utc):return jsonify({"error":"scheduled time must be in the future"}),400
  value=due.astimezone(timezone.utc).isoformat()
 else:value=None
 database=db()
 try:
  database.update(item_id,instagram_scheduled_at=value,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
  log_admin(database,"instagram.schedule",item_id,value or "cleared")
  return jsonify({"ok":True,"scheduled_at":value})
 finally:database.close()

@app.post("/api/news/<int:item_id>/instagram/order")
def instagram_order(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; direction=str(body.get("direction","")).lower()
 if direction not in {"up","down"}:return jsonify({"error":"direction must be up or down"}),400
 database=db()
 try:
  rows=[dict(r) for r in database.latest(200,"all","published",None,"all","pending") if int(r.get("instagram_selected") or 0)==1]
  rows.sort(key=lambda r:(int(r.get("instagram_queue_order") or 0) if int(r.get("instagram_queue_order") or 0)>0 else 10**9,-int(r["id"])))
  index=next((i for i,r in enumerate(rows) if int(r["id"])==item_id),-1)
  target=index-1 if direction=="up" else index+1
  if index<0 or target<0 or target>=len(rows):return jsonify({"ok":True,"moved":False})
  a,b=rows[index],rows[target]; ao=int(a.get("instagram_queue_order") or 0); bo=int(b.get("instagram_queue_order") or 0)
  if ao<=0:ao=database.next_instagram_queue_order()
  if bo<=0:bo=max(1,ao-1)
  database.update(int(a["id"]),instagram_queue_order=bo); database.update(int(b["id"]),instagram_queue_order=ao); log_admin(database,"instagram.reorder",item_id,direction); return jsonify({"ok":True,"moved":True})
 finally:database.close()

@app.post("/api/news/<int:item_id>/instagram/cancel-priority")
def instagram_cancel_priority(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  if str(database.get_settings().get("instagram_priority_id",""))!=str(item_id):return jsonify({"error":"this story is not the active priority"}),409
  database.set_settings({"instagram_priority_id":"","instagram_paused":"false"}); log_admin(database,"instagram.priority.cancel",item_id); return jsonify({"ok":True})
 finally:database.close()

@app.post("/api/fact-check")
def fact_check():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  checked=run_cross_source_check(database); log_admin(database,"fact_check.run",None,str(checked)); return jsonify({"ok":True,"checked":checked})
 finally:database.close()


# Render web-service compatibility: serve the existing public frontend from the same Flask app.
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def _render_public(path):
 if path.startswith("api/"):
  return jsonify({"error":"not found"}),404
 target=path or "home.html"
 if target.endswith("/"):
  target += "index.html"
 return send_from_directory(app.static_folder, target)
