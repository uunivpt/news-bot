from __future__ import annotations
import os
import re
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase
from app.newsroom import process_news

TRAILING_FRAGMENT_RE=re.compile(r"\b(?:a|an|and|as|at|by|for|from|in|including|into|of|on|or|such|than|that|the|their|this|to|under|via|was|were|with|without)\.?$",re.I)

def needs_repair(row):
    title=str(row.get("title") or "").strip(); summary=str(row.get("bot_summary") or row.get("summary") or "").strip(); article=str(row.get("bot_article") or "").strip()
    if not article or not summary:return True
    if title.endswith(("…","...")) or len(title.split())>18:return True
    return any(TRAILING_FRAGMENT_RE.search(re.sub(r"\s+"," ",text).rstrip()) for text in (summary,article))

def main():
    try:limit=max(1,int(os.getenv("BOT_REPAIR_BATCH","50")))
    except ValueError:limit=50
    database=NewsDatabase(); repaired=failed=0
    try:
        rows=[dict(r) for r in database.latest(1000,status="published") if needs_repair(r)][:limit]
        for row in rows:
            try:
                source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or "")
                material=source.get("text") or row.get("summary") or row.get("title") or ""
                result=process_news(source.get("title") or row.get("title") or "",material,row.get("category") or "general")
                if not result:
                    failed+=1; continue
                fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"]}
                if source.get("image_url") and not row.get("image_url"):fields["image_url"]=source["image_url"]
                database.update(int(row["id"]),**fields); repaired+=1
            except Exception as exc:
                failed+=1; print(f"Repair failed for item {row.get('id')}: {exc}")
        print(f"Bot repair: repaired={repaired}; failed={failed}; scanned={len(rows)}")
    finally:database.close()
if __name__=="__main__":main()
