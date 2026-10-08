"""Editorial category rules shared by the main newsroom and emergency feed.

PoliticsHub routes reports about Nana Patekar and obituaries of Indian cultural
figures to India, even when syndication metadata labels them Entertainment.
Ordinary film releases, reviews and celebrity coverage stay in Entertainment.
"""
from __future__ import annotations

import re

INDIAN_SIGNAL = re.compile(
    r"\b(?:India|Indian|Bollywood|Marathi|Maharashtra|Hindi cinema|"
    r"Telugu cinema|Tamil cinema|Malayalam cinema|Bengali cinema|"
    r"Indian cinema|Indian film|Padma Shri|Padma Bhushan)\b",
    re.IGNORECASE,
)
OBITUARY_SIGNAL = re.compile(
    r"\b(?:dies|died|death|dead|passes? away|passed away|passing|"
    r"demise|obituary|no more|last rites|funeral|laid to rest|"
    r"mourns?|condolences?|tributes? to (?:late|veteran))\b",
    re.IGNORECASE,
)
NANA = re.compile(r"\bNana\s+Patekar\b", re.IGNORECASE)


def normalize_category(category: str | None, title: str = "", summary: str = "") -> str:
    name = str(category or "india").strip().lower()
    title_text = str(title or "")
    summary_text = str(summary or "")
    if NANA.search(title_text) or NANA.search(summary_text):
        return "india"
    if name == "entertainment":
        text = f"{title_text} {summary_text}"
        if INDIAN_SIGNAL.search(text) and OBITUARY_SIGNAL.search(text):
            return "india"
    return name
