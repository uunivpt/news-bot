import os, json, secrets, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, session
from werkzeug.security import check_password_hash
from app.ai import AIService
from app.database import NewsDatabase
from app.factcheck import run_cross_source_check

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.getenv("ADMIN_TOKEN", "change-me"))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_FAILURES = 8
_login_failures: dict[str, list[float]] = {}


def db():
    return NewsDatabase()


def admin_ok():
    if session.get("admin_user"):
        return True
    token = os.getenv("ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(token and supplied and secrets.compare_digest(supplied, token))


def require_admin():
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    return None


def require_csrf():
    if not session.get("admin_user"):
        return None
    token = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    if not token or not expected or not secrets.compare_digest(token, expected):
        return jsonify({"error": "invalid CSRF token"}), 403
    return None


def rows_json(rows):
    return [dict(r) for r in rows]


def users():
    try:
        return json.loads(os.getenv("ADMIN_USERS_JSON", "{}"))
    except Exception:
        return {}


def _client_key():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def _login_allowed():
    now = time.time()
    values = [t for t in _login_failures.get(_client_key(), []) if now - t < _LOGIN_WINDOW_SECONDS]
    _login_failures[_client_key()] = values
    return len(values) < _LOGIN_MAX_FAILURES


def _login_failed():
    _login_failures.setdefault(_client_key(), []).append(time.time())


def _india_day_bounds():
    tz = ZoneInfo("Asia/Kolkata")
    today = datetime.now(tz).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/admin") else response.headers.get("Cache-Control", "no-cache")
    return response


@app.post("/api/admin/login")
def login():
    if not _login_allowed():
        return jsonify({"error": "too many login attempts; try again later"}), 429
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    record = users().get(username)
    if not record or not check_password_hash(record, password):
        _login_failed()
        return jsonify({"error": "invalid credentials"}), 401
    _login_failures.pop(_client_key(), None)
    session.clear()
    session["admin_user"] = username
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"ok": True, "username": username, "csrf_token": session["csrf_token"]})


@app.post("/api/admin/logout")
def logout():
    err = require_csrf()
    if err:
        return err
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/admin/me")
def me():
    return jsonify({
        "authenticated": bool(session.get("admin_user")),
        "username": session.get("admin_user"),
        "csrf_token": session.get("csrf_token") if session.get("admin_user") else None,
    })


@app.get("/api/health")
def health():
    database = db()
    try:
        return jsonify({"ok": True, "news_count": database.count()})
    finally:
        database.close()


@app.get("/api/news")
def news():
    category = request.args.get("category", "all")
    status = request.args.get("status", "published")
    review_status = request.args.get("review_status", "all")
    instagram_status = request.args.get("instagram_status", "all")
    search = request.args.get("search")
    try:
        limit = min(max(int(request.args.get("limit", "50")), 1), 100)
    except ValueError:
        limit = 50
    if not admin_ok():
        status = "published"
        review_status = "all"
        instagram_status = "all"
    database = db()
    try:
        return jsonify(rows_json(database.latest(limit, category, status, search, review_status, instagram_status)))
    finally:
        database.close()


@app.get("/api/news/<int:item_id>")
def article(item_id):
    database = db()
    try:
        rows = database.latest(1000, status="all")
        row = next((dict(r) for r in rows if int(r["id"]) == item_id), None)
        if not row:
            return jsonify({"error": "not found"}), 404
        if row["status"] != "published" and not admin_ok():
            return jsonify({"error": "not found"}), 404
        return jsonify(row)
    finally:
        database.close()


@app.get("/api/stats")
def stats():
    err = require_admin()
    if err:
        return err
    database = db()
    try:
        day_start, day_end = _india_day_bounds()
        settings = database.get_settings()
        return jsonify({
            "total": database.count(),
            "pending": len(database.latest(100, status="pending")),
            "review_needed": len(database.latest(100, status="published", review_status="needs_review")),
            "reviewed": len(database.latest(100, status="published", review_status="reviewed")),
            "published": len(database.latest(100, status="published")),
            "instagram_failed": len(database.latest(100, status="published", instagram_status="failed")),
            "instagram_today": database.instagram_daily_count(day_start, day_end),
            "instagram_limit": int(settings.get("instagram_daily_limit", "5")),
            "instagram_enabled": settings.get("instagram_enabled", "true") == "true",
        })
    finally:
        database.close()


@app.get("/api/admin/settings")
def admin_settings():
    err = require_admin()
    if err:
        return err
    database = db()
    try:
        settings = database.get_settings()
        day_start, day_end = _india_day_bounds()
        settings["instagram_today"] = str(database.instagram_daily_count(day_start, day_end))
        return jsonify(settings)
    finally:
        database.close()


@app.post("/api/admin/settings")
def save_settings():
    err = require_admin()
    if err:
        return err
    err = require_csrf()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    values = {}
    if "instagram_enabled" in body:
        values["instagram_enabled"] = "true" if bool(body["instagram_enabled"]) else "false"
    if "instagram_daily_limit" in body:
        try:
            limit = int(body["instagram_daily_limit"])
        except (TypeError, ValueError):
            return jsonify({"error": "daily limit must be a number"}), 400
        if limit < 0 or limit > 100:
            return jsonify({"error": "daily limit must be between 0 and 100"}), 400
        values["instagram_daily_limit"] = str(limit)
    if "instagram_selection_mode" in body:
        mode = str(body["instagram_selection_mode"]).lower()
        if mode not in {"auto", "manual"}:
            return jsonify({"error": "selection mode must be auto or manual"}), 400
        values["instagram_selection_mode"] = mode
    database = db()
    try:
        database.set_settings(values)
        return jsonify({"ok": True, "settings": database.get_settings()})
    finally:
        database.close()


def change(item_id, status=None, **extra):
    err = require_admin()
    if err:
        return err
    err = require_csrf()
    if err:
        return err
    database = db()
    try:
        fields = dict(extra)
        if status is not None:
            fields["status"] = status
        database.update(item_id, **fields)
        return jsonify({"ok": True, **fields})
    finally:
        database.close()


@app.post("/api/news/<int:item_id>/approve")
def approve(item_id):
    return change(item_id, fact_check_status="reviewed", approved_at=datetime.now(timezone.utc).isoformat())


@app.post("/api/news/<int:item_id>/reject")
def reject(item_id):
    return change(item_id, status="rejected", instagram_selected=0)


@app.post("/api/news/<int:item_id>/publish")
def publish(item_id):
    return change(item_id, status="published", published_at_site=datetime.now(timezone.utc).isoformat())


@app.post("/api/news/<int:item_id>/instagram/queue")
def instagram_queue(item_id):
    return change(item_id, instagram_selected=1, instagram_status="pending", instagram_error=None, instagram_next_retry_at=None)


@app.post("/api/news/<int:item_id>/instagram/unqueue")
def instagram_unqueue(item_id):
    return change(item_id, instagram_selected=0)


@app.post("/api/news/<int:item_id>/instagram/retry")
def instagram_retry(item_id):
    return change(item_id, instagram_status="pending", instagram_error=None, instagram_next_retry_at=None, instagram_selected=1)


@app.post("/api/news/<int:item_id>/ai")
def ai_process(item_id):
    err = require_admin()
    if err:
        return err
    err = require_csrf()
    if err:
        return err
    database = db()
    try:
        row = next((dict(r) for r in database.latest(1000, status="all") if int(r["id"]) == item_id), None)
        if not row:
            return jsonify({"error": "not found"}), 404
        service = AIService()
        if not service.enabled:
            return jsonify({"error": "AI not configured"}), 503
        source = row.get("summary") or row["title"]
        summary = service.summarize(row["title"], source)
        article = service.write_article(row["title"], source)
        database.update(item_id, ai_summary=summary, ai_article=article)
        return jsonify({"ok": True, "summary": summary, "article": article})
    finally:
        database.close()


@app.post("/api/fact-check")
def fact_check():
    err = require_admin()
    if err:
        return err
    err = require_csrf()
    if err:
        return err
    database = db()
    try:
        return jsonify({"ok": True, "checked": run_cross_source_check(database)})
    finally:
        database.close()
