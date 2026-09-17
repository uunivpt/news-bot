from typing import Any

import feedparser

from .models import NewsItem


def _image(entry: Any) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail") or []
    if media and isinstance(media, list):
        return media[0].get("url")
    enclosure = entry.get("enclosures") or []
    if enclosure:
        return enclosure[0].get("href") or enclosure[0].get("url")
    return None


def collect_rss(source: dict[str, Any]) -> list[NewsItem]:
    feed = feedparser.parse(source["url"])
    if getattr(feed, "bozo", False) and not feed.entries:
        return []

    items: list[NewsItem] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue
        published = entry.get("published") or entry.get("updated")
        summary = entry.get("summary")
        external_id = entry.get("id") or entry.get("guid") or url
        items.append(
            NewsItem(
                source_name=source["name"],
                source_type=source.get("source_class", "rss"),
                title=title,
                url=url,
                published_at=published,
                summary=summary,
                external_id=str(external_id),
                category=source.get("category", "general"),
                image_url=_image(entry),
                public_source=bool(source.get("public_source", False)),
            )
        )
    return items
