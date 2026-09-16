"""Automatic publication policy.

Normal stories can be published automatically. Stories containing signals
that need extra verification are flagged instead of silently presenting an
uncertain claim as established fact.
"""

from __future__ import annotations

import re

HIGH_RISK_PATTERNS = (
    r"\balleged\b", r"\baccused\b", r"\bscam\b", r"\bfraud\b",
    r"\barrested\b", r"\bdead\b", r"\bkilled\b", r"\bexplosion\b",
    r"\bterror\w*\b", r"\bwar\b", r"\bmissile\b", r"\belection\b",
)


def risk_flags(title: str, summary: str = "") -> list[str]:
    text = f"{title} {summary}".lower()
    return [p for p in HIGH_RISK_PATTERNS if re.search(p, text)]


def publication_status(title: str, summary: str = "") -> str:
    """Return 'published' or 'review' based on simple conservative signals."""
    return "review" if risk_flags(title, summary) else "published"
