from __future__ import annotations

"""Deterministic, license-aware news image acquisition.

Priority:
1. Keep an already-collected source image (existing behaviour) when present.
2. If there is no source image, search Openverse for openly licensed candidates.
3. Score candidates against headline/summary entities and event terms.
4. Reject licenses that do not allow commercial reuse/adaptation.
5. Download the selected image and keep full provenance metadata.

This module deliberately does not treat arbitrary Google Images results as
licensed. A search-engine result is not proof of reuse permission.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
ALLOWED_LICENSES = {"cc0", "pdm", "by", "by-sa"}
MIN_WIDTH = 640
MIN_HEIGHT = 360
MAX_RESULTS = 20
STOPWORDS = {
    "a","an","and","are","as","at","be","been","by","for","from","has","have",
    "in","into","is","it","its","of","on","or","that","the","their","this",
    "to","under","was","were","with","after","amid","over","new","latest",
    "says","said","will","would","about","against","during","following",
    "according","report","reports","news","update","today","yesterday",
}
EVENT_TERMS = {
    "war","conflict","attack","strike","missile","border","battle","election",
    "meeting","summit","tariff","trade","protest","earthquake","flood",
    "cyclone","fire","crash","explosion","ceasefire","deal","agreement",
    "arrest","verdict","court","launch","visit","speech","sanctions",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}", str(text or "").lower())
    return [w.strip("'-") for w in words if w not in STOPWORDS]


def _entity_phrases(text: str) -> list[str]:
    """Extract simple capitalized names/places without an LLM."""
    raw = re.findall(r"\b[A-Z][A-Za-z0-9'’-]*(?:\s+[A-Z][A-Za-z0-9'’-]*){0,3}", str(text or ""))
    out = []
    for value in raw:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value.lower() not in STOPWORDS and len(value) >= 3:
            out.append(value)
    return list(dict.fromkeys(out))


def build_image_queries(headline: str, summary: str = "", category: str = "") -> list[str]:
    """Build focused searches such as 'Donald Trump tariffs India' or 'India Pakistan border'."""
    headline = str(headline or "").strip()
    summary = str(summary or "").strip()
    text = f"{headline} {summary}"
    tokens = _tokens(text)
    entities = _entity_phrases(headline) + _entity_phrases(summary[:1200])
    entities = list(dict.fromkeys(entities))

    queries: list[str] = []
    # Strongest query: the actual headline, trimmed to a useful search phrase.
    if headline:
        headline_words = headline.split()
        if len(headline_words) > 10:
            headline_words = headline_words[:10]
        queries.append(" ".join(headline_words))

    # Named people/countries/organizations are much more useful than generic
    # words. Combine up to two entity phrases with one event term.
    event = next((w for w in tokens if w in EVENT_TERMS), "")
    for entity in entities[:5]:
        queries.append(f"{entity} {event}".strip())

    # Keep meaningful token combinations for stories like "India Pakistan war".
    if len(tokens) >= 2:
        meaningful = tokens[:8]
        if event:
            context = [w for w in meaningful if w != event][:4]
            queries.append(" ".join(context + [event]))
        queries.append(" ".join(meaningful[:5]))

    if category and tokens:
        queries.append(f"{category} {' '.join(tokens[:4])}")

    # Remove weak duplicates and overly short searches.
    final = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip(" -")
        if len(query.split()) >= 2 and query.lower() not in {q.lower() for q in final}:
            final.append(query)
    return final[:8]


def _license_allowed(value: str) -> bool:
    license_name = str(value or "").lower().strip()
    # Openverse uses short identifiers such as by, by-sa, cc0, pdm.
    return license_name in ALLOWED_LICENSES


def _candidate_text(item: dict) -> str:
    tags = item.get("tags") or []
    tag_text = " ".join(
        str(t.get("name", "")) if isinstance(t, dict) else str(t) for t in tags
    )
    return " ".join(
        str(item.get(k) or "") for k in ("title", "description", "creator", "provider", "source")
    ) + " " + tag_text


def _score_candidate(item: dict, headline: str, summary: str, query: str) -> int:
    hay = set(_tokens(_candidate_text(item)))
    wanted = set(_tokens(f"{headline} {summary}"))
    query_tokens = set(_tokens(query))
    score = 0

    score += min(45, len(query_tokens & hay) * 15)
    score += min(30, len(wanted & hay) * 5)

    # Exact entity matches are especially useful for person/country stories.
    for entity in _entity_phrases(headline):
        if set(_tokens(entity)) <= hay:
            score += 12

    width = int(item.get("width") or 0)
    height = int(item.get("height") or 0)
    if width >= 1280 and height >= 720:
        score += 12
    elif width >= MIN_WIDTH and height >= MIN_HEIGHT:
        score += 6

    license_name = str(item.get("license") or "").lower()
    if license_name in {"cc0", "pdm"}:
        score += 5
    elif license_name in {"by", "by-sa"}:
        score += 3

    return score


def _openverse_search(query: str) -> list[dict]:
    response = requests.get(
        OPENVERSE_URL,
        params={"q": query, "page_size": MAX_RESULTS, "mature": "false"},
        headers={"User-Agent": "PoliticsHubNewsBot/3.0 (+https://politicshub.in)"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results") or []


def _download_and_validate(url: str, destination: Path) -> tuple[int, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        url,
        headers={"User-Agent": "PoliticsHubNewsBot/3.0 (+https://politicshub.in)"},
        timeout=25,
    )
    response.raise_for_status()
    if len(response.content) > 15 * 1024 * 1024:
        raise ValueError("image exceeds 15 MB limit")
    destination.write_bytes(response.content)
    try:
        with Image.open(destination) as image:
            image.verify()
        with Image.open(destination) as image:
            width, height = image.size
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise ValueError(f"downloaded file is not a valid image: {exc}") from exc
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        destination.unlink(missing_ok=True)
        raise ValueError(f"image is too small: {width}x{height}")
    return width, height


def acquire_story_image(
    row: dict,
    output_dir: str | Path = "data/media/news_images",
) -> dict:
    """Return selected image URL + provenance, and download a local copy when possible."""
    headline = str(row.get("title") or "").strip()
    summary = str(row.get("bot_summary") or row.get("summary") or "").strip()
    category = str(row.get("category") or "general").strip()

    # Existing source image remains the first-choice path. We do not claim a
    # license that the source page did not provide.
    existing = str(row.get("image_url") or "").strip()
    if existing.startswith(("http://", "https://")):
        output = Path(output_dir) / f"{row.get('id') or 'story'}_source.jpg"
        try:
            width, height = _download_and_validate(existing, output)
            return {
                "image_url": existing,
                "image_source": "article-source",
                "image_license": "unknown-source-license",
                "image_credit": str(row.get("source_name") or "").strip(),
                "image_source_url": str(row.get("url") or "").strip(),
                "image_search_query": "",
                "image_selection_score": 100,
                "image_local_path": str(output),
                "image_width": width,
                "image_height": height,
                "image_selected_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            print(f"Source image unusable; trying licensed image search: {exc}")

    queries = build_image_queries(headline, summary, category)
    best = None
    best_score = -1
    used_query = ""

    for query in queries:
        try:
            results = _openverse_search(query)
        except Exception as exc:
            print(f"Openverse search failed for {query!r}: {exc}")
            continue
        for item in results:
            if not _license_allowed(item.get("license")):
                continue
            direct_url = str(item.get("url") or "").strip()
            landing_url = str(item.get("foreign_landing_url") or "").strip()
            if not direct_url.startswith(("http://", "https://")):
                continue
            if not landing_url.startswith(("http://", "https://")):
                continue
            score = _score_candidate(item, headline, summary, query)
            if score > best_score:
                best = item
                best_score = score
                used_query = query

    # Do not use a weak, generic open-licensed image merely to fill the panel.
    if not best or best_score < 25:
        # A weak image is worse than a clean Reel without one. Return metadata
        # instead of inventing a match or silently using an unlicensed result.
        return {
            "image_url": "",
            "image_source": "",
            "image_license": "",
            "image_credit": "",
            "image_source_url": "",
            "image_search_query": queries[0] if queries else "",
            "image_selection_score": 0,
            "image_local_path": "",
        }

    item_id = str(row.get("id") or "story")
    output = Path(output_dir) / f"{item_id}_news.jpg"
    try:
        width, height = _download_and_validate(str(best["url"]), output)
    except Exception as exc:
        print(f"Selected image download failed: {exc}")
        raise

    license_name = str(best.get("license") or "").upper()
    version = str(best.get("license_version") or "").strip()
    license_text = f"{license_name} {version}".strip()
    creator = str(best.get("creator") or "").strip()
    provider = str(best.get("provider") or best.get("source") or "").strip()
    credit = str(best.get("attribution") or "").strip()
    if not credit:
        credit = " / ".join(x for x in (creator, provider) if x)

    return {
        "image_url": str(best["url"]),
        "image_source": provider or "Openverse",
        "image_license": license_text or "open-license",
        "image_credit": credit,
        "image_source_url": str(best["foreign_landing_url"]),
        "image_search_query": used_query,
        "image_selection_score": best_score,
        "image_local_path": str(output),
        "image_width": width,
        "image_height": height,
        "image_selected_at": datetime.now(timezone.utc).isoformat(),
    }


def prepare_story_image(row: dict, output_dir: str | Path = "data/media/news_images") -> dict:
    """Idempotent acquisition helper used immediately before Reel rendering."""
    result = acquire_story_image(row, output_dir=output_dir)
    row.update(result)
    return result
