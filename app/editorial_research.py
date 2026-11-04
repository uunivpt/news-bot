"""Structured evidence packets for editorial research.

This module never treats source-derived facts as independent reporting. Every
claim remains attributed to its source URL. No text is padded to meet length.
"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse
from app.editorial_gate import word_count

@dataclass(frozen=True)
class Evidence:
    publisher: str
    url: str
    excerpt: str
    official: bool = False

def build_research_brief(title: str, evidence: list[Evidence]) -> dict:
    kept = []
    seen_urls = set()
    hosts = set()
    for packet in evidence:
        url = (packet.url or "").strip()
        host = (urlparse(url).hostname or "").lower()
        excerpt = " ".join((packet.excerpt or "").split())[:16000]
        if not url.startswith(("https://", "http://")) or not host or not excerpt:
            continue
        canonical = url.split("#", 1)[0]
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        hosts.add(host.removeprefix("www."))
        kept.append({"publisher": packet.publisher, "url": canonical,
                     "excerpt": excerpt, "official": packet.official})
    return {
        "title": title,
        "sources": kept[:6],
        "source_count": min(len(kept), 6),
        "distinct_hosts": len(hosts),
        "evidence_words": sum(word_count(p["excerpt"]) for p in kept[:6]),
        # Independent source domains do not guarantee independent verification.
        "requires_human_verification": True,
        "ready_for_longform_draft": bool(kept) and sum(word_count(p["excerpt"]) for p in kept[:6]) >= 500,
    }
