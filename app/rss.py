from typing import Any

import feedparser
import requests

from .models import NewsItem


HEADERS = {"User-Agent": "PoliticsHubNewsBot/1.0 (+public-source-collector)"}


def _image(entry: Any) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail") or []
    if media and isinstance(media, list):
        return media[0].get("url")
    enclosure = entry.get("enclosures") or []
    if enclosure:
        return enclosure[0].get("href") or enclosure[0].get("url")
    return None


def collect_rss(source: dict[str, Any]) -> list[NewsItem]:
    url = str(source.get("url") or "").strip()
    if not url:
        return []

    timeout = min(max(int(source.get("timeout_seconds", 12)), 3), 30)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if not feed.entries and (getattr(feed, "bozo", False) or not getattr(feed, "version", "")):
        raise ValueError("Source did not return a valid RSS or Atom feed")

    items: list[NewsItem] = []
    max_items = min(max(int(source.get("max_items", 50)), 1), 200)
    for entry in feed.entries[:max_items]:
        title = (entry.get("title") or "").strip()
        item_url = (entry.get("link") or "").strip()
        if not title or not item_url:
            continue
        published = entry.get("published") or entry.get("updated")
        summary = entry.get("summary")
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
