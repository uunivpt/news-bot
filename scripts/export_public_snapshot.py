from __future__ import annotations

import json
import re
from pathlib import Path

from app.database import NewsDatabase
from app.category_routing import normalize_category

SITE = "https://politicshub.in"
PUBLIC_LIMIT = 100
CATEGORIES = {"india","world","politics","business","technology","sports","entertainment","science","health","hindi"}

def esc_xml(value):
    return (str(value or "")
        .replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        .replace('"',"&quot;").replace("'","&apos;"))

def slug(value):
    return re.sub(r"[^a-z0-9]+","-",str(value or "").lower()).strip("-")[:110] or "story"

def section(value):
    value=str(value or "general").lower().strip()
    return "india" if value=="general" else (value if value in CATEGORIES else "india")

def main():
    db=NewsDatabase()
    try:
        rows=[dict(r) for r in db.latest(PUBLIC_LIMIT,status="published")]
        sitemap_rows=[dict(r) for r in db.conn.execute(
            "SELECT id,title,category,published_at_site,published_at FROM news_items "
            "WHERE status='published' ORDER BY COALESCE(published_at_site,published_at) DESC,id DESC"
        ).fetchall()]
    finally:
        db.close()

    public=[]
    for row in rows:
        if not row.get("bot_article"):
            continue
        public.append({
            "id":row.get("id"),
            "source_name":row.get("source_name"),
            "source_type":row.get("source_type"),
            "title":row.get("title"),
            "url":row.get("url"),
            "published_at":row.get("published_at"),
            "summary":row.get("summary") or "",
            "bot_summary":row.get("bot_summary") or row.get("summary") or "",
            "bot_article":row.get("bot_article") or "",
            "category":normalize_category(row.get("category") or "general", row.get("title") or "", row.get("bot_summary") or row.get("summary") or ""),
            "image_url":row.get("image_url"),
            "public_source":bool(row.get("public_source")),
            "published_at_site":row.get("published_at_site") or row.get("published_at"),
        })

    Path("public").mkdir(exist_ok=True)
    Path("public/news-data.json").write_text(
        json.dumps(public,ensure_ascii=False,separators=(",",":")),encoding="utf-8"
    )

    # Sitemap XML is generated live by /api/seo-news-sitemap from the database,
    # with this snapshot as the outage fallback. Never publish stale archive URLs.
    print(f"Public snapshot rows: {len(public)}; sitemap served dynamically.")

if __name__=="__main__":
    main()
