from __future__ import annotations

import re

from app.database import NewsDatabase
from app.category_routing import normalize_category


POLITICS_RE = re.compile(
    r"\b(?:"
    r"election|elections|polling|polls|voting|vote|ballot|"
    r"politics|political|politician|party|parties|"
    r"bjp|congress|aap|tmc|ncp|shiv\s+sena|dmk|aiadmk|"
    r"lok\s+sabha|rajya\s+sabha|parliament|assembly|"
    r"mla|mp|chief\s+minister|prime\s+minister|"
    r"opposition|ruling\s+party|manifesto|campaign|"
    r"cabinet|minister|governor|chief\s+minister|"
    r"constituency|by[-\s]?poll|political\s+row"
    r")\b",
    re.I,
)

TOPIC_PATTERNS = [
    ("sports", re.compile(r"\b(?:cricket|football|tennis|hockey|ipl|match|tournament|athlete|olympic|medal|sporting)\b", re.I)),
    ("technology", re.compile(r"\b(?:technology|tech|ai|artificial intelligence|smartphone|iphone|android|software|cyber|chip|semiconductor|gadget)\b", re.I)),
    ("business", re.compile(r"\b(?:stocks?|shares?|market|markets|economy|economic|inflation|rbi|sebi|banking|bank|finance|financial|trade|exports?|imports?|company|companies|startup|investment|investor|gdp|interest rates?)\b", re.I)),
    ("health", re.compile(r"\b(?:health|hospital|doctor|medical|medicine|disease|vaccine|patients?|healthcare)\b", re.I)),
    ("science", re.compile(r"\b(?:science|scientists?|space|isro|research|researchers?|nasa|satellite|astronomy)\b", re.I)),
    ("entertainment", re.compile(r"\b(?:movie|film|actor|actress|bollywood|celebrity|music|singer|television|ott|web series)\b", re.I)),
]


def classify(title: str, summary: str) -> str:
    text = f"{title} {summary}".strip()
    if normalize_category("entertainment", title, summary) == "india":
        return "india"
    if POLITICS_RE.search(text):
        return "politics"
    for category, pattern in TOPIC_PATTERNS:
        if pattern.search(text):
            return category
    return "india"


def main() -> None:
    db = NewsDatabase()
    changed = 0
    try:
        rows = [dict(row) for row in db.latest(5000, category="all", status="all")]
        for row in rows:
            current_category = str(row.get("category") or "india").lower()
            title = str(row.get("title") or "")
            summary = str(row.get("bot_summary") or row.get("summary") or "")
            new_category = normalize_category(current_category, title, summary)
            # Preserve legacy repair for incorrectly categorized NewsData politics.
            if new_category == current_category and current_category == "politics" and str(row.get("source_type") or "").lower() == "newsdata":
                new_category = classify(title, summary)
            if new_category != current_category:
                db.update(int(row["id"]), category=new_category)
                changed += 1
        print(f"Reclassified legacy NewsData rows: {changed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
