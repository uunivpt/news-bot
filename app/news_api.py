from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from .models import NewsItem
from .category_routing import normalize_category

_TIMEOUT = max(5, int(os.getenv("NEWS_API_TIMEOUT_SECONDS", "12")))


def _get_json(url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers or {}, timeout=_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("News API returned a non-object response")
    return data


def collect_newsapi(source: dict[str, Any]) -> list[NewsItem]:
    key = os.getenv("NEWSAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("Required news API key is missing")

    params: dict[str, Any] = {
        "country": source.get("country", "in"),
        "pageSize": min(int(source.get("page_size", 100)), 100),
    }
    if source.get("category"):
        params["category"] = source["category"]
    if source.get("q"):
        params["q"] = source["q"]

    data = _get_json(
        "https://newsapi.org/v2/top-headlines",
        params=params,
        headers={"X-Api-Key": key, "Accept": "application/json"},
    )
    if data.get("status") != "ok":
        raise RuntimeError(str(data.get("message") or "NewsAPI request failed"))

    items: list[NewsItem] = []
    for article in data.get("articles") or []:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        if not title or not url or title == "[Removed]":
            continue
        src = article.get("source") or {}
        source_name = str(src.get("name") or source.get("name") or "NewsAPI").strip()
        published = article.get("publishedAt") or datetime.now(timezone.utc).isoformat()
        external_id = url
        items.append(NewsItem(
            source_name=source_name,
            source_type="newsapi",
            title=title,
            url=url,
            published_at=published,
            summary=str(article.get("description") or article.get("content") or "").strip(),
            external_id=external_id,
            category=normalize_category(source.get("route_category") or ("india" if str(source.get("country") or "").lower() == "in" else source.get("category", "general")), title, str(article.get("description") or article.get("content") or "")),
            image_url=str(article.get("urlToImage") or "").strip() or None,
            public_source=True,
        ))
    return items


def collect_newsdata(source: dict[str, Any]) -> list[NewsItem]:
    key = os.getenv("NEWSDATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Required news API key is missing")

    params: dict[str, Any] = {
        "apikey": key,
        "country": source.get("country", "in"),
        "language": source.get("language", "en"),
    }
    for field in ("q", "qInTitle", "category"):
        if source.get(field):
            params[field] = source[field]
    # Geographic routing labels are not NewsData topic categories.
    if params.get("category") in {"india", "general"}:
        params.pop("category")
    if source.get("size"):
        params["size"] = min(int(source["size"]), 50)

    data = _get_json(
        "https://newsdata.io/api/1/latest",
        params=params,
        headers={"Accept": "application/json"},
    )
    if str(data.get("status") or "").lower() not in {"success", "ok"}:
        raise RuntimeError(str(data.get("message") or data.get("results") or "NewsData request failed"))

    items: list[NewsItem] = []
    for article in data.get("results") or []:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("link") or "").strip()
        if not title or not url:
            continue
        source_name = str(article.get("source_name") or source.get("name") or "NewsData.io").strip()
        published = article.get("pubDate") or article.get("pubDateTZ") or datetime.now(timezone.utc).isoformat()
        external_id = str(article.get("article_id") or url)
        # NewsData's own guidance permits publishing title/short description/
        # publisher/date metadata, while warning against republishing full
        # article content and images. Keep collection inside that safer scope.
        description = str(article.get("description") or "").strip()[:1200]
        # NewsData's article-level category is authoritative for topic routing.
        # The source config only supplies the geographic fallback ("india").
        raw_categories = article.get("category") or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]
        normalized_categories = {str(value).strip().lower() for value in raw_categories if str(value).strip()}
        category_map = {
            "politics": "politics",
            "business": "business",
            "sports": "sports",
            "technology": "technology",
            "science": "science",
            "health": "health",
            "entertainment": "entertainment",
            "world": "world",
        }
        category = next((category_map[value] for value in normalized_categories if value in category_map), "india")
        category = normalize_category(category, title, description)

        items.append(NewsItem(
            source_name=source_name,
            source_type="newsdata",
            title=title,
            url=url,
            published_at=published,
            summary=description,
            external_id=external_id,
            category=category,
            image_url=None,
            public_source=True,
        ))
    return items
