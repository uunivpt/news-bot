"""Publisher-attributed Maharashtra news feeds. No fake translations or scraped articles."""
from __future__ import annotations
import calendar
import html
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
import feedparser
import requests

CACHE_SECONDS = 20 * 60
FEEDS = (
    ("TV9 Marathi", "https://www.tv9marathi.com/maharashtra/feed", ("www.tv9marathi.com", "tv9marathi.com")),
    ("ABP माझा", "https://marathi.abplive.com/news/maharashtra/feed", ("marathi.abplive.com",)),
)
ENGLISH_FEEDS = (
    ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", ("www.thehindu.com", "thehindu.com")),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", ("www.bbc.com", "bbc.com", "www.bbc.co.uk", "bbc.co.uk")),
)
_lock = threading.Lock()
_cache: dict = {}
_devanagari = re.compile(r"[\u0900-\u097f]")
_maharashtra = re.compile(r"\b(?:maharashtra|mumbai|pune|nagpur|nashik|thane|amravati|vidarbha|marathwada|konkan|wardha|sambhajinagar|aurangabad|kolhapur|solapur|sangli|nanded|beed|akola|jalgaon|latur|palghar|raigad|ahilyanagar|shirdi|ratnagiri|satara|navi mumbai)\b", re.I)
_tags = re.compile(r"<[^>]*>")
_space = re.compile(r"\s+")

def _clean(text: str) -> str:
    return _space.sub(" ", html.unescape(_tags.sub(" ", str(text or "")))).strip()

def _when(entry: dict) -> str | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if stamp:
        try: return datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError): pass
    return None

def _read_one(name: str, feed_url: str, hosts: tuple[str, ...], language="mr") -> list[dict]:
    response = requests.get(
        feed_url, timeout=(3,7),
        headers={"User-Agent": "PoliticsHubNewsBot/1.0 (attributed RSS reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("RSS feed exceeds size budget")
    parsed = feedparser.parse(response.content)
    if not parsed.entries or not getattr(parsed,"version",""):
        raise ValueError("Publisher returned no valid RSS or Atom entries")
    result = []
    for entry in parsed.entries[:80]:
        title = _clean(entry.get("title"))[:300]
        url = str(entry.get("link") or "").strip()
        try: dest = urlsplit(url)
        except ValueError: continue
        if dest.scheme != "https" or (dest.hostname or "").lower() not in hosts or dest.username or dest.password:
            continue
        if language=="mr":
            if not _devanagari.search(title): continue
        elif language=="en":
            if _devanagari.search(title) or not _maharashtra.search(title): continue
        else: continue
        result.append({
            "title":title, "url":url, "source_name":name,
            "published_at":_when(entry),"category":"maharashtra",
            "language":language,"kind":"publisher_rss",
        })
    return result

def get_feed(language="mr") -> dict:
    language = "en" if str(language).lower()=="en" else "mr"
    now = time.monotonic()
    with _lock:
        cached=_cache.get(language)
        if cached and now < cached["expires"]:
            return dict(cached["result"])
        items, statuses = [], {}
        for name,url,hosts in (ENGLISH_FEEDS if language=="en" else FEEDS):
            try:
                found=_read_one(name,url,hosts,language=language)
                statuses[name]={"available":bool(found),"count":len(found)}
                items.extend(found)
            except (requests.RequestException,ValueError,TypeError):
                statuses[name]={"available":False,"count":0}
        seen,unique=set(),[]
        for item in items:
            key=item["url"].split("?")[0].rstrip("/")
            if key in seen: continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda x:x.get("published_at") or "",reverse=True)
        result={
            "items":unique[:100],
            "sources":statuses,
            "last_checked":datetime.now(timezone.utc).isoformat(),
            "refresh_minutes":20,"language":language,
            "status":"ok" if unique else "unavailable",
            "editorial_note":("English-language Maharashtra reports from English publishers, not automatic translations of Marathi articles." if language=="en" else "Original Marathi publisher headlines and source links."),
        }
        _cache[language]={"expires":now + CACHE_SECONDS,"result":result}
        return dict(result)

