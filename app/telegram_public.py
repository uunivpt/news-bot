import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import NewsItem

HEADERS = {"User-Agent": "PoliticsHubNewsBot/1.0 (+public-source-collector)"}
URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)


def _image(message: Any) -> str | None:
    photo = message.select_one(".tgme_widget_message_photo_wrap")
    if not photo:
        return None
    style = photo.get("style", "")
    match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
    return match.group(1) if match else None


def _link_metadata(text: str, timeout: int = 6) -> tuple[str | None, str | None, str | None, str | None]:
    """Read public metadata only; article body is handled later by the AI pipeline."""
    match = URL_RE.search(text or "")
    if not match:
        return None, None, None, None
    link = match.group(0).rstrip(".,);]}")
    try:
        response = requests.get(link, headers=HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        if "html" not in content_type:
            return None, None, None, link
        soup = BeautifulSoup(response.text[:2_000_000], "html.parser")

        def meta(*names: str) -> str | None:
            for name in names:
                node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
                if node and node.get("content"):
                    return str(node["content"]).strip()
            return None

        image = meta("og:image", "twitter:image")
        title = meta("og:title", "twitter:title")
        description = meta("og:description", "twitter:description", "description")
        return image, title, description, response.url
    except Exception:
        return None, None, None, link


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
        raw_text = text_node.get_text(" ", strip=True) if text_node else "Telegram post"
        title = raw_text
        summary = raw_text
        image_url = _image(message)

        if URL_RE.search(raw_text):
            preview_image, preview_title, preview_description, _ = _link_metadata(raw_text, timeout=min(timeout, 6))
            if not image_url:
                image_url = preview_image
            if preview_title:
                title = preview_title
            if preview_description:
                summary = f"{preview_description}\n\n{raw_text}"

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
                summary=summary[:8000],
                external_id=external_id,
                category=source.get("category", "general"),
                image_url=image_url,
            )
        )
    return items
