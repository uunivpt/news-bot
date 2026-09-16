from typing import Any

import feedparser

from .models import NewsItem


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
                source_type="rss",
                title=title,
                url=url,
                published_at=published,
                summary=summary,
                external_id=str(external_id),
            )
        )
    return items
