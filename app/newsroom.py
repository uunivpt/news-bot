from __future__ import annotations

import re
from collections import Counter

URL_RE = re.compile(r"https?://\S+", re.I)
SPACE_RE = re.compile(r"\s+")
BAD_LINE_RE = re.compile(r"^(?:source|via|follow|subscribe|read more|click here|advertisement|ad)\b", re.I)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}")
TRAILING_FRAGMENT_RE = re.compile(r"\b(?:a|an|and|as|at|by|for|from|in|including|into|of|on|or|such|than|that|the|their|this|to|under|via|was|were|with|without)\.?$", re.I)


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
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'‘“])", value)
    result: list[str] = []
    for part in parts:
        item = part.strip(" \t-–—")
        if len(item) < 30 or BAD_LINE_RE.search(item):
            continue
        # Never publish a final-looking fragment such as: "including the sum, models, and the."
        if TRAILING_FRAGMENT_RE.search(item):
            continue
        result.append(item.rstrip(".!?") + ".")
    return result


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


def _first_complete_sentence(value: str) -> str:
    items = sentences(value)
    return items[0] if items else ""


def make_headline(title: str, source_text: str) -> str:
    value = SPACE_RE.sub(" ", clean_text(title)).strip(" .:-")
    # Telegram posts frequently put the headline and body in the same field.
    # Keep only the first complete sentence when the collected title is clearly a full post.
    if value:
        first = _first_complete_sentence(value)
        if first and (len(value.split()) > 18 or len(value) > 140 or first.casefold() != value.casefold()):
            value = first.rstrip(".!?")
        if 4 <= len(value.split()) <= 18 and len(value) <= 140:
            return value
    items = sentences(source_text)
    if items:
        return items[0].rstrip(".!?")
    return value[:140] or "Latest news update"


def make_summary(title: str, source_text: str) -> str:
    chosen = select_sentences(source_text, 3)
    if not chosen:
        headline = make_headline(title, source_text)
        return headline + "." if headline else ""
    return " ".join(chosen)


def make_article(title: str, source_text: str) -> str:
    # Use complete sentences only. Do not cut the article at an arbitrary character.
    chosen = select_sentences(source_text, 40)
    if not chosen:
        return ""
    paragraphs: list[str] = []
    first = chosen[:3]
    if first:
        paragraphs.append(" ".join(first))
    buckets = [chosen[3:8], chosen[8:14], chosen[14:20], chosen[20:28], chosen[28:40]]
    labels = ["Key details", "What is known", "Context", "What comes next", "Additional details"]
    for label, bucket in zip(labels, buckets):
        if bucket:
            paragraphs.append(f"{label}: {' '.join(bucket)}")
    return "\n\n".join(paragraphs).strip()


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
