"""Conservative publication gate for PoliticsHub long-form editorial reports.

Length is an internal editorial target, not a Google AdSense requirement.
This gate checks format and automated evidence screening; it does not prove truth.
"""
from __future__ import annotations
import os
import unicodedata


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

def longform_review(row: dict, *, minimum: int = 800, verification: dict | None = None) -> dict:
    article = str(row.get("bot_article") or "").strip()
    summary = str(row.get("bot_summary") or row.get("summary") or "").strip()
    errors = []
    if word_count(article) < minimum:
        errors.append("insufficient_original_longform_material")
    if not summary or word_count(summary) < 12:
        errors.append("insufficient_summary")
    if not verification or not verification.get("passed"):
        errors.append("automated_evidence_check_required")
    if len(set(words(article.casefold()))) < 120:
        errors.append("insufficient_distinct_information")
    return {"passed": not errors, "errors": errors, "words": word_count(article)}

def longform_mode_enabled() -> bool:
    return os.getenv("EDITORIAL_LONGFORM_ONLY", "true").lower() not in {"0","false","no"}
