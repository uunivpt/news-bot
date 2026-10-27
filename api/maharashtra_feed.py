"""Independent public Marathi RSS brief endpoint; does not depend on Neon."""
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
_lock = threading.Lock()
_cache = {"expires": 0.0, "result": None}
_dev_re = re.compile(r"[\u0900-\u097f]")
_tag_re = re.compile(r"<[^>]*>")
_space_re = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = html.unescape(_tag_re.sub(" ", str(text or "")))
    return _space_re.sub(" ", text).strip()


def _when(entry: dict) -> str | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if stamp:
        try:
            return datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _read_one(name: str, feed_url: str, hosts: tuple[str, ...]) -> list[dict]:
    response = requests.get(
        feed_url,
        timeout=(3, 7),
        headers={"User-Agent": "PoliticsHubNewsBot/1.0 (source-linked RSS reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("RSS feed exceeds size budget")
    parsed = feedparser.parse(response.content)
    if not parsed.entries or not getattr(parsed, "version", ""):
        raise ValueError("Publisher returned no valid RSS or Atom entries")
    result = []
    for entry in parsed.entries[:60]:
        title = _clean(entry.get("title"))[:300]
        url = str(entry.get("link") or "").strip()
        try:
            dest = urlsplit(url)
        except ValueError:
            continue
        if (
            not _dev_re.search(title)
            or dest.scheme != "https"
            or (dest.hostname or "").lower() not in hosts
        ):
            continue
        result.append({
            "title": title, "url": url, "source_name": name,
            "published_at": _when(entry), "category": "maharashtra",
            "kind": "publisher_rss",
            # Publisher RSS titles are attributed links, not unverified original reporting.
        })
    return result


def get_feed() -> dict:
    now = time.monotonic()
    with _lock:
        if now < _cache["expires"] and _cache["result"] is not None:
            return dict(_cache["result"])
        items, statuses = [], {}
        for name, url, hosts in FEEDS:
            try:
                found = _read_one(name, url, hosts)
                statuses[name] = {"available": bool(found), "count": len(found)}
                items.extend(found)
            except (requests.RequestException, ValueError, TypeError):
                statuses[name] = {"available": False, "count": 0}
        unique, seen = [], set()
        for item in items:
            k = item["url"].split("?")[0].rstrip("/")
            if k in seen:
                continue
            seen.add(k)
            unique.append(item)
        unique.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        result = {
            "items": unique[:100], "sources": statuses,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "refresh_minutes": 20, "status": "ok" if any(s["available"] for s in statuses.values()) else "unavailable",
        }
        _cache.update(result=result, expires=now + CACHE_SECONDS)
        return dict(result)

