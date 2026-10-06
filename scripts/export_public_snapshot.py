from __future__ import annotations

import json
import re
from pathlib import Path

from app.database import NewsDatabase

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
            "category":row.get("category") or "general",
            "image_url":row.get("image_url"),
            "public_source":bool(row.get("public_source")),
            "published_at_site":row.get("published_at_site") or row.get("published_at"),
        })

    Path("public").mkdir(exist_ok=True)
    Path("public/news-data.json").write_text(
        json.dumps(public,ensure_ascii=False,separators=(",",":")),encoding="utf-8"
    )

    static_urls=["/","/about.html","/contact.html","/editorial-policy.html","/corrections.html",
                 "/privacy.html","/cookies.html","/terms.html","/disclaimer.html","/newsletter.html"]
    static_xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +         "".join("<url><loc>"+esc_xml(SITE+p)+"</loc></url>" for p in static_urls) + "</urlset>"
    Path("public/static-sitemap.xml").write_text(static_xml,encoding="utf-8")

    urls=[]
    for row in sitemap_rows:
        if not row.get("id") or not row.get("title"):
            continue
        urls.append("<url><loc>"+esc_xml(
            SITE+"/"+section(row.get("category"))+"/"+str(int(row["id"]))+"-"+slug(row.get("title"))
        )+"</loc></url>")

    for old in Path("public").glob("news-sitemap-*.xml"):
        old.unlink()

    chunks=[urls[i:i+45000] for i in range(0,len(urls),45000)] or [[]]
    if len(chunks)==1:
        Path("public/news-sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
            "".join(chunks[0])+"</urlset>",encoding="utf-8"
        )
    else:
        refs=[]
        for index,chunk in enumerate(chunks,1):
            filename=Path("public")/f"news-sitemap-{index}.xml"
            filename.write_text(
                '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
                "".join(chunk)+"</urlset>",encoding="utf-8"
            )
            refs.append("<sitemap><loc>"+esc_xml(SITE+f"/news-sitemap-{index}.xml")+"</loc></sitemap>")
        Path("public/news-sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
            "".join(refs)+"</sitemapindex>",encoding="utf-8"
        )

    Path("public/sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
        "<sitemap><loc>"+SITE+"/static-sitemap.xml</loc></sitemap>"+
        "<sitemap><loc>"+SITE+"/news-sitemap.xml</loc></sitemap></sitemapindex>",encoding="utf-8"
    )
    print(f"Public snapshot rows: {len(public)}; archive sitemap URLs: {len(urls)}")

if __name__=="__main__":
    main()
