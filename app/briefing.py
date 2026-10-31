"""A bounded reading list from published reports, without invented summaries."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .source_text import source_text

DESKS = (("all", "All desks"), ("india", "India"), ("politics", "Politics"),
         ("world", "World"), ("hindi", "Hindi"))


def briefing_excerpt(value):
    text = source_text(value)
    return text if len(text) <= 320 else text[:317].rsplit(" ", 1)[0] + "…"


def select_briefing(rows, *, timestamp, desk="all", days=1, now=None, limit=6):
    current = (now or datetime.now(timezone.utc)).timestamp()
    candidates, identities, urls = [], set(), set()
    for row in rows:
        if row.get("status", "published") != "published" or not row.get("public_source"):
            continue
        if desk != "all" and row.get("category") != desk:
            continue
        try:
            identity = int(row.get("id") or 0)
            source_url = str(row.get("url") or "").strip()
            source = urlsplit(source_url)
            published = timestamp(row)
            if (identity <= 0 or source.scheme not in {"https", "http"} or not source.hostname
                    or source.username or source.password or not str(row.get("title") or "").strip()
                    or not current - days * 86400 <= published <= current):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        candidates.append((published, identity, source_url, row))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    unique = []
    for published, identity, source_url, row in candidates:
        if identity in identities or source_url in urls:
            continue
        identities.add(identity)
        urls.add(source_url)
        unique.append(row)
    # Represent each available desk before filling remaining slots by recency.
    selected, desks = [], set()
    for row in unique:
        category = row.get("category") or "india"
        if category not in desks:
            selected.append(row)
            desks.add(category)
        if len(selected) >= limit:
            return selected
    selected_ids = {int(row["id"]) for row in selected}
    selected.extend(row for row in unique if int(row["id"]) not in selected_ids)
    return selected[:limit]
