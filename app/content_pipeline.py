"""Content preparation pipeline for website articles and Instagram reels.

The pipeline keeps the detailed website article separate from the concise
Instagram facts so one output does not get overloaded with the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEMPLATES = {
    "general": "general_news",
    "india": "breaking_news",
    "world": "world_news",
    "politics": "politics_news",
    "business": "market_data",
    "technology": "tech_news",
    "sports": "sports_news",
    "entertainment": "entertainment_news",
    "science": "science_news",
    "health": "health_news",
}


@dataclass(frozen=True)
class SocialBrief:
    headline: str
    key_facts: tuple[str, ...]
    template: str
    image_urls: tuple[str, ...]


def choose_template(category: str | None, title: str = "") -> str:
    """Select a deterministic template; keywords refine the generic choice."""
    text = f"{category or 'general'} {title}".lower()
    if any(k in text for k in ("map", "border", "war", "missile", "country")):
        return "geopolitics_map"
    if any(k in text for k in ("stock", "market", "shares", "₹", "rupee", "percent")):
        return "market_data"
    return TEMPLATES.get(category or "general", "general_news")


def build_social_brief(item: Any) -> SocialBrief:
    """Create the concise visual brief from an already-collected news item."""
    summary = (getattr(item, "summary", None) or "").strip()
    facts = tuple(x.strip() for x in summary.split("\n") if x.strip())[:5]
    return SocialBrief(
        headline=str(getattr(item, "title", "")).strip(),
        key_facts=facts,
        template=choose_template(getattr(item, "category", "general"), getattr(item, "title", "")),
        image_urls=tuple(x for x in (getattr(item, "image_url", None),) if x),
    )
