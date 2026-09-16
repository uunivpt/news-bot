import os, json, secrets
from datetime import datetime, timezone
from flask import Flask, jsonify, request, session
from werkzeug.security import check_password_hash
from app.ai import AIService
from app.database import NewsDatabase
from app.factcheck import run_cross_source_check

app=Flask(__name__); app.secret_key=os.getenv("FLASK_SECRET_KEY",os.getenv("ADMIN_TOKEN","change-me"))
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE="Lax")
def db(): return NewsDatabase()
def admin_ok():
    if session.get("admin_user"): return True
    token=os.getenv("ADMIN_TOKEN",""); supplied=request.headers.get("X-Admin-Token","")
    return bool(token and supplied and secrets.compare_digest(supplied,token))
def require_admin():
    if not admin_ok(): return jsonify({"error":"admin authentication required"}),401
    return None
def rows_json(rows): return [dict(r) for r in rows]
def users():
    try:return json.loads(os.getenv("ADMIN_USERS_JSON","{}"))
    except Exception:return {}

@app.post("/api/admin/login")
def login():
    body=request.get_json(silent=True) or {}; username=str(body.get("username","")).strip(); password=str(body.get("password","")); record=users().get(username)
    if not record or not check_password_hash(record,password):return jsonify({"error":"invalid credentials"}),401
    session["admin_user"]=username; return jsonify({"ok":True,"username":username})
@app.post("/api/admin/logout")
def logout(): session.clear(); return jsonify({"ok":True})
@app.get("/api/admin/me")
def me(): return jsonify({"authenticated":bool(session.get("admin_user")),"username":session.get("admin_user")})
@app.get("/api/health")
def health():
    database=db()
    try:return jsonify({"ok":True,"news_count":database.count()})
    finally:database.close()
@app.get("/api/news")
def news():
    category=request.args.get("category","all"); status=request.args.get("status","published"); search=request.args.get("search"); limit=min(max(int(request.args.get("limit","50")),1),100)
    if not admin_ok():status="published"
    database=db()
    try:return jsonify(rows_json(database.latest(limit,category,status,search)))
    finally:database.close()
@app.get("/api/news/<int:item_id>")
def article(item_id):
    database=db()
    try:
        rows=database.latest(100,status="all"); row=next((dict(r) for r in rows if int(r["id"])==item_id),None)
        if not row:return jsonify({"error":"not found"}),404
        if row["status"]!="published" and not admin_ok():return jsonify({"error":"not found"}),404
        return jsonify(row)
    finally:database.close()
@app.get("/api/stats")
def stats():
    err=require_admin()
    if err:return err
    database=db()
    try:return jsonify({"total":database.count(),"pending":len(database.latest(100,status="pending")),"review":len(database.latest(100,status="review")),"approved":len(database.latest(100,status="approved")),"published":len(database.latest(100,status="published"))})
    finally:database.close()
def change(item_id,status,**extra):
    err=require_admin()
    if err:return err
    database=db()
    try:database.update(item_id,status=status,**extra);return jsonify({"ok":True,"status":status})
    finally:database.close()
@app.post("/api/news/<int:item_id>/approve")
def approve(item_id):return change(item_id,"approved",approved_at=datetime.now(timezone.utc).isoformat())
@app.post("/api/news/<int:item_id>/reject")
def reject(item_id):return change(item_id,"rejected")
@app.post("/api/news/<int:item_id>/publish")
def publish(item_id):return change(item_id,"published",published_at_site=datetime.now(timezone.utc).isoformat())
@app.post("/api/news/<int:item_id>/ai")
def ai_process(item_id):
    err=require_admin()
    if err:return err
    database=db()
    try:
        row=next((dict(r) for r in database.latest(100,status="all") if int(r["id"])==item_id),None)
        if not row:return jsonify({"error":"not found"}),404
        service=AIService()
        if not service.enabled:return jsonify({"error":"AI not configured"}),503
        source=row.get("summary") or row["title"]; summary=service.summarize(row["title"],source); article=service.write_article(row["title"],source)
        database.update(item_id,ai_summary=summary,ai_article=article,status="review");return jsonify({"ok":True,"summary":summary,"article":article})
    finally:database.close()
@app.post("/api/fact-check")
def fact_check():
    err=require_admin()
    if err:return err
    database=db()
    try:return jsonify({"ok":True,"checked":run_cross_source_check(database)})
    finally:database.close()
