from __future__ import annotations

import json
import os
from pathlib import Path
from flask import jsonify, request

# Public /api/news compatibility endpoint.
# It prefers the live newsroom database and falls back to the published snapshot
# so a database outage never turns the public news feed into HTTP 500.
def handler(request):
    category = str(request.args.get("category", "all") or "all").strip().lower()
    try:
        limit = max(1, min(int(request.args.get("limit", "200")), 500))
    except (TypeError, ValueError):
        limit = 200

    try:
        from app.database import NewsDatabase
        database = NewsDatabase()
        try:
            rows = [dict(row) for row in database.latest(limit, category, "published")]
        finally:
            database.close()
        if rows:
            return jsonify(rows)
    except Exception as exc:
        print(f"/api/news database fallback: {exc}")

    snapshot = Path(__file__).resolve().parent.parent / "public" / "news-data.json"
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            payload = []
    except Exception as exc:
        print(f"/api/news snapshot fallback failed: {exc}")
        payload = []

    out = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        item_category = str(item.get("category") or "general").lower()
        if category not in ("all", "general") and item_category != category:
            continue
        # Snapshot entries are public content; never expose private admin/Instagram fields.
        out.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "source_name": item.get("source_name"),
            "source_type": item.get("source_type"),
            "url": item.get("url"),
            "published_at": item.get("published_at"),
            "summary": item.get("summary") or "",
            "bot_summary": item.get("bot_summary") or item.get("summary") or "",
            "bot_article": item.get("bot_article") or "",
            "category": item.get("category") or "general",
            "image_url": item.get("image_url"),
            "public_source": bool(item.get("public_source")),
            "status": "published",
        })
        if len(out) >= limit:
            break
    return jsonify(out)
