"""Embed the latest dated public feed in both static landing pages at deploy time."""
from datetime import datetime
from html import escape
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def render(rows, regional):
    cards = []
    for row in rows:
        source = str(row.get("source_name") or "")
        if not regional and (row.get("category") not in {"india","world"} or re.search(r"[\u0900-\u097f]",row.get("title","")) or any(x in source.lower() for x in ("abp majha","tv9 marathi","lokmat","loksatta","saamana"))):
            continue
        if regional and not any(x in source.lower() for x in ("abp majha", "tv9 marathi", "abp माझा")):
            continue
        if not row.get("public_source") or row.get("status", "published") != "published":
            continue
        url = str(row.get("url") or "")
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            continue
        stamp = row.get("published_at") or row.get("published_at_site")
        try:
            date = datetime.fromisoformat(stamp).astimezone(ZoneInfo("Asia/Kolkata"))
        except (ValueError, TypeError):
            continue
        number = str(row.get("news_number") or "")
        desk = row.get("category")
        href = f"/{desk}/{number}" if not regional and number.isdigit() and desk in {"india","world","politics","hindi"} else url
        cards.append((date, f'<li><a href="{escape(href, quote=True)}">{escape(row["title"])}</a> · {escape(source)} · <time datetime="{date.isoformat()}">{date:%d %b %Y, %H:%M} IST</time></li>'))
    return "<ul>" + "".join(card for _, card in sorted(cards, reverse=True)[:5]) + "</ul>" if cards else ""


if __name__ == "__main__":
    rows = json.loads((PUBLIC / "news-data.json").read_text())
    for name, regional in (("index.html", False), ("maharashtra/index.html", True)):
        path = PUBLIC / name
        before, rest = path.read_text().split("<!-- reader-feed -->", 1)
        _, after = rest.split("<!-- /reader-feed -->", 1)
        path.write_text(before + "<!-- reader-feed -->" + render(rows, regional) + "<!-- /reader-feed -->" + after)
