"""Conservative automated prepublication corroboration, not a truth guarantee.

Only publishes low-risk, sufficiently sourced stories. Fail closed on uncertainty.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.editorial_gate import word_count, words
from app.publish_policy import risk_flags

_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:%|°)?(?![\w])")
_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)
_UNSAFE = re.compile(r"(?i)\b(?:alleged|accus(?:ed|ation)|fraud|scam|arrest(?:ed)?|killed|dead|death|"
                     r"terror(?:ism|ist)?|missile|war|election|vote|court|corrupt(?:ion)?|"
                     r"rape|assault|murder|communal|riot|suicide)\b")
_EXTERNAL = re.compile(r"https?://\S+")

def assess_automatic_publication(title: str, summary: str, article: str, research: dict) -> dict:
    """Structural and source-coverage safeguards; not independent fact-checking."""
    errors = []
    packets = list(research.get("sources") or [])
    hosts = {
        (urlparse(str(packet.get("url") or "")).hostname or "").lower().removeprefix("www.")
        for packet in packets
    }
    hosts.discard("")
    evidence = " ".join(str(p.get("excerpt") or "") for p in packets)
    article_text = str(article or "")
    if len(hosts) < 2:
        errors.append("two_distinct_publisher_domains_required")
    if int(research.get("evidence_words") or 0) < 500:
        errors.append("insufficient_source_material")
    if word_count(article_text) < 800:
        errors.append("insufficient_article_length")
    if _UNSAFE.search(f"{title} {summary} {article_text}") or risk_flags(title, summary):
        errors.append("sensitive_claims_need_manual_or_official_confirmation")
    normalized_evidence = set(w.casefold() for w in words(evidence) if len(w) > 3)
    meaningful = [w.casefold() for w in words(f"{title} {summary} {article_text}") if len(w) > 3]
    if not meaningful or sum(w in normalized_evidence for w in meaningful) / len(meaningful) < 0.38:
        errors.append("draft_not_sufficiently_grounded_in_sources")
    source_numbers = set(_NUMBER.findall(evidence))
    new_numbers = set(_NUMBER.findall(f"{title} {summary} {article_text}")) - source_numbers
    if new_numbers:
        errors.append("unsupported_numbers")
    return {
        "passed": not errors, "errors": errors,
        "source_domains": len(hosts),
        "source_material_words": int(research.get("evidence_words") or 0),
        "article_words": word_count(article_text),
        "unsupported_number_count": len(new_numbers),
        "automated_screen_only": True,
    }
