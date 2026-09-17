from __future__ import annotations

import re
from collections import Counter

URL_RE = re.compile(r"https?://\S+", re.I)
SPACE_RE = re.compile(r"\s+")
BAD_LINE_RE = re.compile(r"^(?:source|via|follow|subscribe|read more|click here|advertisement|ad)\b", re.I)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}")


def clean_text(text: str | None) -> str:
    value = text or ""
    value = URL_RE.sub("", value)
    value = HANDLE_RE.sub("", value)
    value = value.replace("\u200b", " ").replace("\xa0", " ")
    lines: list[str] = []
    for raw in re.split(r"\n+", value):
        line = SPACE_RE.sub(" ", raw).strip(" \t|•·")
        if not line or BAD_LINE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sentences(text: str) -> list[str]:
    value = SPACE_RE.sub(" ", clean_text(text).replace("\n", " ")).strip()
    if not value:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'‘])", value)
    return [p.strip(" \t-–—") for p in parts if len(p.strip()) >= 30 and not BAD_LINE_RE.search(p)]


def _words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]{2,}", value.lower())


def _score(sentence: str, index: int, total: int, frequency: Counter[str]) -> float:
    words = _words(sentence)
    if not words:
        return 0.0
    stop = {"the", "and", "for", "that", "with", "this", "from", "have", "has", "were", "was", "are", "their", "they", "said", "into", "after", "before", "about", "will", "been", "also"}
    useful = [w for w in words if w not in stop]
    score = sum(frequency[w] for w in useful) / max(len(useful), 1)
    if index == 0:
        score += 2.5
    elif index < max(3, total // 5):
        score += 1.0
    if re.search(r"\b\d+(?:\.\d+)?\b", sentence):
        score += 0.6
    if re.search(r"\b(?:said|announced|confirmed|reported|according|will|has|have|was|were)\b", sentence, re.I):
        score += 0.5
    return score


def select_sentences(text: str, limit: int) -> list[str]:
    items = sentences(text)
    if len(items) <= limit:
        return items
    frequency = Counter(w for item in items for w in _words(item))
    ranked = [(_score(item, i, len(items), frequency), i, item) for i, item in enumerate(items)]
    chosen = sorted(ranked, reverse=True)[:limit]
    return [item for _, _, item in sorted(chosen, key=lambda x: x[1])]


def make_headline(title: str, source_text: str) -> str:
    value = SPACE_RE.sub(" ", clean_text(title)).strip(" .:-")
    if 4 <= len(value.split()) <= 18 and len(value) <= 140:
        return value
    items = sentences(source_text)
    if items:
        value = re.sub(r"^(breaking|update|just in)\s*[:\-–—]?\s*", "", items[0], flags=re.I).rstrip(".!?")
        return (value[:137].rsplit(" ", 1)[0] + "…") if len(value) > 140 else value
    return value[:140] or "Latest news update"


def make_summary(title: str, source_text: str) -> str:
    chosen = select_sentences(source_text, 3)
    if not chosen:
        return make_headline(title, source_text) + "."
    return " ".join(item.rstrip(".!?") + "." for item in chosen)


def make_article(title: str, source_text: str) -> str:
    chosen = select_sentences(source_text, 14)
    if not chosen:
        return ""
    paragraphs = [chosen[0].rstrip(".!?") + "."]
    buckets = [chosen[1:3], chosen[3:6], chosen[6:9], chosen[9:12], chosen[12:14]]
    labels = ["What happened", "Key details", "What is known", "Context", "What comes next"]
    for label, bucket in zip(labels, buckets):
        if bucket:
            text = " ".join(item.rstrip(".!?") + "." for item in bucket)
            paragraphs.append(f"{label}: {text}")
    return "\n\n".join(paragraphs).strip()[:14000]


def process_news(title: str, source_text: str, category: str = "general") -> dict[str, str] | None:
    material = clean_text(source_text)
    if len(material) < 80:
        return None
    result = {
        "headline": make_headline(title, material),
        "summary": make_summary(title, material),
        "article": make_article(title, material),
    }
    if len(result["summary"]) < 50 or len(result["article"]) < 120:
        return None
    return result
