import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from app.ai import AIService
from app.database import NewsDatabase
from app.factcheck import run_cross_source_check

app = Flask(__name__)


def db() -> NewsDatabase:
    return NewsDatabase()


def admin_ok() -> bool:
    token = os.getenv("ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(token and supplied and supplied == token)


def rows_json(rows):
    return [dict(row) for row in rows]


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
    search = request.args.get("search")
    limit = min(max(int(request.args.get("limit", "50")), 1), 100)
    if not admin_ok():
        status = "published"
    database = db()
    try:
        return jsonify(rows_json(database.latest(limit, category, status, search)))
    finally:
        database.close()


@app.get("/api/stats")
def stats():
    database = db()
    try:
        return jsonify({
            "total": database.count(),
            "pending": len(database.latest(100, status="pending")),
            "review": len(database.latest(100, status="review")),
            "approved": len(database.latest(100, status="approved")),
            "published": len(database.latest(100, status="published")),
        })
    finally:
        database.close()


@app.post("/api/news/<int:item_id>/approve")
def approve(item_id: int):
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    database = db()
    try:
        database.update(item_id, status="approved", approved_at=datetime.now(timezone.utc).isoformat())
        return jsonify({"ok": True, "status": "approved"})
    finally:
        database.close()


@app.post("/api/news/<int:item_id>/reject")
def reject(item_id: int):
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    database = db()
    try:
        database.update(item_id, status="rejected")
        return jsonify({"ok": True, "status": "rejected"})
    finally:
        database.close()


@app.post("/api/news/<int:item_id>/publish")
def publish(item_id: int):
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    database = db()
    try:
        database.update(item_id, status="published", published_at_site=datetime.now(timezone.utc).isoformat())
        return jsonify({"ok": True, "status": "published"})
    finally:
        database.close()


@app.post("/api/news/<int:item_id>/ai")
def ai_process(item_id: int):
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    database = db()
    try:
        rows = database.latest(100, status="all")
        row = next((r for r in rows if int(r["id"]) == item_id), None)
        if not row:
            return jsonify({"error": "not found"}), 404
        service = AIService()
        if not service.enabled:
            return jsonify({"error": "AI is not configured. Add AI_API_URL, AI_API_KEY and AI_MODEL."}), 503
        source_text = row["summary"] or row["title"]
        summary = service.summarize(row["title"], source_text)
        article = service.write_article(row["title"], source_text)
        database.update(item_id, ai_summary=summary, ai_article=article, status="review")
        return jsonify({"ok": True, "summary": summary, "article": article})
    finally:
        database.close()


@app.post("/api/fact-check")
def fact_check():
    if not admin_ok():
        return jsonify({"error": "admin authentication required"}), 401
    database = db()
    try:
        checked = run_cross_source_check(database)
        return jsonify({"ok": True, "checked": checked})
    finally:
        database.close()
