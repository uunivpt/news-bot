"""Opt-in X (Twitter) official API v2 collector.

Accounts are explicitly configured; no scraping, screenshots or implied
verification of a post's claims. Republishing of attached photos is disabled.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import requests

from .models import NewsItem

X_API = "https://api.x.com/2"
HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
POST_ID = re.compile(r"^[0-9]+$")


def _get(path: str, token: str, params: dict | None = None) -> dict:
    response = requests.get(
        X_API + path,
        params=params,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("errors") and not data.get("data"):
        raise RuntimeError("X API returned an error instead of account/post data")
    return data


def _excerpt(value: object, max_chars: int = 200) -> str:
    # Short extract + source link, not a copied full post/article.
    value = re.sub(r"https?://\S+", "", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_chars:
        return value
    head = value[:max_chars - 1].rsplit(" ", 1)[0].rstrip()
    return (head or value[:max_chars - 1]) + "…"


def collect_x(source: dict) -> list[NewsItem]:
    token = os.getenv("X_API_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("X_API_BEARER_TOKEN is missing; X news collection is not active")
    handle = str(source.get("handle") or "").lstrip("@").strip()
    if not HANDLE.fullmatch(handle):
        raise ValueError("Invalid configured X handle")
    account = _get(
        "/users/by/username/" + handle,
        token,
        {"user.fields": "username,name,verified"},
    ).get("data") or {}
    # Prevent accidental relabeling after a username changes or wrong lookup.
    if not account.get("id") or str(account.get("username", "")).lower() != handle.lower():
        raise RuntimeError("Configured X username did not match returned account")
    user_id = str(account["id"])
    count = max(5, min(int(source.get("max_results", 10)), 100))
    data = _get(
        "/users/" + user_id + "/tweets",
        token,
        {"max_results": count, "exclude": "retweets,replies", "tweet.fields": "created_at"},
    )
    items = []
    for post in data.get("data") or []:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or "")
        excerpt = _excerpt(post.get("text"), 200)
        if not POST_ID.fullmatch(post_id) or len(excerpt) < 16:
            continue
        label = str(source.get("name") or "X @" + handle)
        # This explicitly attributes the statement rather than endorsing its claim.
        first = _excerpt(excerpt, 90).strip(" .")
        title = f"{handle} posted on X: {first}"
        date = str(post.get("created_at") or "").strip()
        if not date:
            date = datetime.now(timezone.utc).isoformat()
        summary = (
            f"In an X post dated {date}, @{handle} wrote: “{excerpt}” "
            "This describes the account's statement and has not been independently verified."
        )
        items.append(NewsItem(
            source_name=label, source_type="x", title=title,
            url=f"https://x.com/{handle}/status/{post_id}",
            published_at=date, summary=summary, external_id=post_id,
            category=source.get("category") or "politics",
            # Never presume a media attachment is licensed for republication.
            image_url=None, public_source=True,
        ))
    return items
