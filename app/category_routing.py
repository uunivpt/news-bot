"""Stable public categories; retired desks are rehomed, not deleted.

Only India, World, Politics, Hindi and Maharashtra remain visible. Retired
Entertainment/Business/Technology/Sports/Science/Health news retains its
original article ID, URL and publication status while its desk is updated.
"""
from __future__ import annotations

import re

RETIRED_DESKS = frozenset({
    "entertainment", "business", "technology", "sports", "science", "health",
})
INDIAN_SIGNAL = re.compile(
    r"\b(?:india|indian|bollywood|marathi|maharashtra|hindi cinema|"
    r"telugu cinema|tamil cinema|malayalam cinema|bengali cinema|"
    r"indian cinema|indian film|padma shri|padma bhushan|deepika|ranveer)\b"
    r"|भारत|भारतीय|महाराष्ट्र|बॉलीवुड|मुंबई|दिल्ली", re.IGNORECASE,
)
POLITICS_SIGNAL = re.compile(
    r"\b(?:elections?|vot(?:e|es|ing)|polling|ballot|politic(?:s|al|ian)|"
    r"parliament|lok sabha|rajya sabha|legislature|assembly|"
    r"bjp|congress|cabinet|government formation|coalition|"
    r"prime minister|chief minister|minister|opposition|"
    r"president(?:ial)? election|manifesto)\b"
    r"|चुनाव|राजनीति|संसद|विधानसभा|प्रधानमंत्री|मुख्यमंत्री", re.IGNORECASE,
)
WORLD_SIGNAL = re.compile(
    r"\b(?:hollywood|oscars?|grammys?|k[- ]?pop|korea|china|japan|"
    r"united states|usa|u\\.s\\.|american|british|united kingdom|"
    r"london|europe|european|russia|ukraine|israel|gaza|iran|"
    r"france|germany|canada|australia|international|global|world)\b"
    r"|अमेरिका|ब्रिटेन|चीन|रूस|यूक्रेन|दुनिया|विदेश", re.IGNORECASE,
)
NANA = re.compile(r"\bNana\s+Patekar\b", re.IGNORECASE)


def normalize_category(category: str | None, title: str = "", summary: str = "") -> str:
    name = str(category or "india").strip().lower()
    text = f"{title or ''} {summary or ''}"
    if NANA.search(text):
        return "india"
    if name in RETIRED_DESKS:
        if POLITICS_SIGNAL.search(text):
            return "politics"
        if WORLD_SIGNAL.search(text) and not INDIAN_SIGNAL.search(text):
            return "world"
        return "india"
    return name or "india"
