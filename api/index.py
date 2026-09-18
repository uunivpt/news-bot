# Production deployment marker: deterministic newsroom + public source attribution.
from __future__ import annotations

import json, os, secrets, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase
from app.factcheck import run_cross_source_check
from app.newsroom import process_news
from app.worker import dispatch_worker

app=Flask(__name__)
_secret=os.getenv("FLASK_SECRET_KEY") or os.getenv("ADMIN_TOKEN") or os.getenv("ADMIN_SETUP_KEY")
if not _secret:raise RuntimeError("Configure FLASK_SECRET_KEY in Vercel Environment Variables")
app.secret_key=_secret
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE="Lax")
_LOGIN_WINDOW_SECONDS=300; _LOGIN_MAX_FAILURES=8; _login_failures={}


def _ensure_admin_users(database):
 database.conn.execute("CREATE TABLE IF NOT EXISTS admin_users (username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'owner',created_at TEXT NOT NULL)")
 if not database._postgres:database.conn.commit()

def db():
 database=NewsDatabase(); _ensure_admin_users(database); return database

def admin_ok():
 if session.get("admin_user"):return True
 token=os.getenv("ADMIN_TOKEN",""); supplied=request.headers.get("X-Admin-Token",""); return bool(token and supplied and secrets.compare_digest(supplied,token))

def require_admin():return None if admin_ok() else (jsonify({"error":"admin authentication required"}),401)
def require_csrf():
 if not session.get("admin_user"):return None
 token=request.headers.get("X-CSRF-Token",""); expected=session.get("csrf_token",""); return None if token and expected and secrets.compare_digest(token,expected) else (jsonify({"error":"invalid CSRF token"}),403)

def _publicize(row):
 r=dict(row)
 if not admin_ok():
  # Public readers may see the originating source and its public article URL.
  # Internal moderation, Instagram state, hashes and processing fields stay private.
  for key in ("normalized_url","external_id","url_hash","title_hash","collected_at","fact_check_status","fact_check_notes","approved_at","instagram_status","instagram_media_id","instagram_error","instagram_published_at","instagram_attempts","instagram_last_attempt_at","instagram_next_retry_at","instagram_container_id","reel_cloudinary_public_id","instagram_selected","ai_summary","ai_article","bot_summary","bot_article","published_at_site"):
   r.pop(key,None)
  raw=dict(row).get("published_at_site") or dict(row).get("published_at")
  if raw:
   try:
    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc); r["published_at"]=dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M")
   except ValueError:pass
  r["summary"]=dict(row).get("bot_summary") or ""; r["article"]=dict(row).get("bot_article") or ""
 return r

def rows_json(rows):return [_publicize(r) for r in rows if admin_ok() or (r.get("status")=="published" and r.get("bot_article"))]
def users():
 try:return json.loads(os.getenv("ADMIN_USERS_JSON","{}"))
 except Exception:return {}
def _client_key():return request.headers.get("X-Forwarded-For",request.remote_addr or "unknown").split(",")[0].strip()
def _login_allowed():
 now=time.time(); values=[t for t in _login_failures.get(_client_key(),[]) if now-t<_LOGIN_WINDOW_SECONDS]; _login_failures[_client_key()]=values; return len(values)<_LOGIN_MAX_FAILURES
def _login_failed():_login_failures.setdefault(_client_key(),[]).append(time.time())
def _india_day_bounds():
 tz=ZoneInfo("Asia/Kolkata"); today=datetime.now(tz).date(); start=datetime.combine(today,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc); return start.isoformat(),(start+timedelta(days=1)).isoformat()

@app.after_request
def security_headers(response):
 response.headers["X-Content-Type-Options"]="nosniff"; response.headers["X-Frame-Options"]="DENY"; response.headers["Referrer-Policy"]="no-referrer"; response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"; response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
 if request.path.startswith("/api/admin"):response.headers["Cache-Control"]="no-store"
 return response

@app.post("/api/admin/setup")
def setup_owner():
 if session.get("admin_user"):return jsonify({"error":"owner setup is disabled after sign-in"}),403
 key=os.getenv("ADMIN_SETUP_KEY","").strip() or os.getenv("ADMIN_TOKEN","").strip(); body=request.get_json(silent=True) or {}
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
 body=request.get_json(silent=True) or {}; username=str(body.get("username","")).strip(); password=str(body.get("password","")); database=db(); valid=False; role=None
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
 try:return jsonify({"ok":True,"news_count":database.count()})
 finally:database.close()

@app.get("/api/news")
def news():
 category=request.args.get("category","all"); status=request.args.get("status","published"); review=request.args.get("review_status","all"); ig=request.args.get("instagram_status","all"); search=request.args.get("search")
 try:limit=min(max(int(request.args.get("limit","100")),1),100)
 except ValueError:limit=100
 if not admin_ok():status,review,ig="published","all","all"
 database=db()
 try:return jsonify(rows_json(database.latest(limit,category,status,search,review,ig)))
 finally:database.close()

@app.get("/api/news/<int:item_id>")
def article(item_id):
 database=db()
 try:
  row=next((dict(r) for r in database.latest(1000,status="all") if int(r["id"])==item_id),None)
  if not row or (row["status"]!="published" and not admin_ok()) or (not admin_ok() and not row.get("bot_article")):return jsonify({"error":"not found"}),404
  return jsonify(_publicize(row))
 finally:database.close()

@app.get("/api/stats")
def stats():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds(); return jsonify({"total":database.count(),"pending":len(database.latest(100,"all","pending")),"review_needed":len(database.latest(100,"all","published",None,"needs_review")),"published":len(database.latest(100,"all","published")),"instagram_failed":len(database.latest(100,"all","published",None,"all","failed")),"instagram_today":database.instagram_daily_count(a,b),"instagram_limit":int(settings.get("instagram_daily_limit","5")),"instagram_interval_minutes":int(settings.get("instagram_interval_minutes","60")),"instagram_enabled":settings.get("instagram_enabled","true")=="true","instagram_paused":settings.get("instagram_paused","false")=="true","instagram_priority_id":settings.get("instagram_priority_id",""),"website_enabled":settings.get("website_enabled","true")=="true"})
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
 try:database.set_settings(values); settings_now=database.get_settings()
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
  database.update(item_id,**fields); return jsonify({"ok":True,**fields})
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
 try:database.update(item_id,**fields); return jsonify({"ok":True,"fields":fields})
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
  database.update(item_id,**fields); return jsonify({"ok":True,"mode":"deterministic_bot","headline":result["headline"],"summary":result["summary"],"article":result["article"]})
 finally:database.close()

@app.post("/api/news/<int:item_id>/ai")
def legacy_process(item_id):return process_item(item_id)

@app.post("/api/news/<int:item_id>/instagram/queue")
def instagram_queue(item_id):
 result=change(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)
@app.post("/api/news/<int:item_id>/instagram/unqueue")
def instagram_unqueue(item_id):return change(item_id,instagram_selected=0)
@app.post("/api/news/<int:item_id>/instagram/retry")
def instagram_retry(item_id):
 result=change(item_id,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_selected=1)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)
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
  if not row.get("bot_article"):return jsonify({"error":"story has not been processed by the newsroom bot"}),422
  if row.get("instagram_status")=="published":return jsonify({"error":"already published to Instagram"}),409
  database.set_settings({"instagram_priority_id":str(item_id),"instagram_paused":"true"}); database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
 finally:database.close()
 dispatch=dispatch_worker(); return jsonify({"ok":True,"priority_id":item_id,"queue_paused":True,"worker_dispatched":dispatch.get("ok",False),"worker_dispatch":dispatch})
@app.post("/api/news/<int:item_id>/instagram/cancel-priority")
def instagram_cancel_priority(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  if str(database.get_settings().get("instagram_priority_id",""))!=str(item_id):return jsonify({"error":"this story is not the active priority"}),409
  database.set_settings({"instagram_priority_id":"","instagram_paused":"false"}); return jsonify({"ok":True})
 finally:database.close()

@app.post("/api/fact-check")
def fact_check():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:return jsonify({"ok":True,"checked":run_cross_source_check(database)})
 finally:database.close()
