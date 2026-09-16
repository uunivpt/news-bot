import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import NewsItem


HEADERS = {"User-Agent": "news-bot/1.0 (+Phase-1 collector)"}


def collect_public_telegram(source: dict[str, Any], timeout: int = 15) -> list[NewsItem]:
    username = source["username"].lstrip("@").strip()
    if not username:
        return []

    url = f"https://t.me/s/{username}"
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    items: list[NewsItem] = []
    for message in soup.select(".tgme_widget_message"):
        post_link = message.select_one("a.tgme_widget_message_date")
        if not post_link:
            continue
        post_url = urljoin("https://t.me/", post_link.get("href", ""))
        text_node = message.select_one(".tgme_widget_message_text")
        title = text_node.get_text(" ", strip=True) if text_node else ""
        if not title:
            title = "Telegram post"
        post_id_match = re.search(r"/(\d+)$", post_url.rstrip("/"))
        external_id = post_id_match.group(1) if post_id_match else post_url
        date_node = post_link.select_one("time")
        published = date_node.get("datetime") if date_node else None
        items.append(
            NewsItem(
                source_name=source["name"],
                source_type="telegram",
                title=title[:500],
                url=post_url,
                published_at=published,
                external_id=external_id,
            )
        )
    return items
