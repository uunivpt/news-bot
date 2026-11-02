"""Conservative publication gate for PoliticsHub long-form editorial reports.

Length is an internal editorial target, not a Google AdSense requirement.
This gate cannot verify originality or factual truth; human editorial sign-off
must attest independent reporting/added value before automatic publication.
"""
from __future__ import annotations
import os
import unicodedata

_ALLOWED = {"reviewed", "approved"}

def words(value: str) -> list[str]:
    tokens, current = [], []
    for char in str(value or ""):
        if unicodedata.category(char)[:1] in {"L", "M", "N"}:
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens

def word_count(text: str) -> int:
    return len(words(text))

def longform_review(row: dict, *, minimum: int = 800) -> dict:
    article = str(row.get("bot_article") or "").strip()
    summary = str(row.get("bot_summary") or row.get("summary") or "").strip()
    status = str(row.get("fact_check_status") or "").strip().lower()
    errors = []
    if word_count(article) < minimum:
        errors.append("insufficient_original_longform_material")
    if not summary or word_count(summary) < 12:
        errors.append("insufficient_summary")
    # The review status must be set by an actual human editor following source
    # verification. Do not infer editorial approval from source count or length.
    if status not in _ALLOWED:
        errors.append("editorial_review_required")
    if len(set(words(article.casefold()))) < 120:
        errors.append("insufficient_distinct_information")
    return {"passed": not errors, "errors": errors, "words": word_count(article)}

def longform_mode_enabled() -> bool:
    return os.getenv("EDITORIAL_LONGFORM_ONLY", "true").lower() not in {"0","false","no"}
