from typing import Any

import feedparser
from .models import NewsItem
from .source_http import fetch_source, public_http_url
from .source_text import source_text
from urllib.parse import urlsplit


HEADERS = {"User-Agent": "PoliticsHubNewsBot/1.0 (+public-source-collector)"}


def _image(entry: Any) -> str | None:
    for key in ("media_content", "media_thumbnail", "enclosures"):
        media = entry.get(key) or []
        for item in media[:8] if isinstance(media, list) else []:
            if not isinstance(item, dict):
                continue
            candidate = item.get("url") or item.get("href")
            if public_http_url(candidate):
                return candidate
    return None


def collect_rss(source: dict[str, Any]) -> list[NewsItem]:
    url = str(source.get("url") or "").strip()
    if not url:
        return []

    timeout = min(max(int(source.get("timeout_seconds", 12)), 3), 30)
    allowed_hosts = source.get("allowed_hosts") or [(urlsplit(url).hostname or "").removeprefix("www.")]
    response = fetch_source(url, headers=HEADERS, timeout=timeout, allowed_hosts=allowed_hosts)
    feed = feedparser.parse(response.content)
    if not feed.entries and (getattr(feed, "bozo", False) or not getattr(feed, "version", "")):
        raise ValueError("Source did not return a valid RSS or Atom feed")

    items: list[NewsItem] = []
    max_items = min(max(int(source.get("max_items", 50)), 1), 200)
    for entry in feed.entries[:max_items]:
        title = source_text(entry.get("title"))
        item_url = str(entry.get("link") or "").strip()
        if not title or not public_http_url(item_url):
            continue
        published = entry.get("published") or entry.get("updated")
        summary = source_text(entry.get("summary"))
        external_id = entry.get("id") or entry.get("guid") or item_url
        items.append(
            NewsItem(
                source_name=source["name"],
                source_type=source.get("source_class", "rss"),
                title=title,
                url=item_url,
                published_at=published,
                summary=summary,
                external_id=str(external_id),
                category=source.get("category", "general"),
                image_url=_image(entry),
                public_source=bool(source.get("public_source", False)),
            )
        )
    return items
