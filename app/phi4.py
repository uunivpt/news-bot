"""Microsoft Phi-4 AI adapter for PoliticsHub.

All calls are server-side and optional. If Phi-4 is unavailable, callers can
fall back to the deterministic newsroom pipeline.
"""
from __future__ import annotations

import os
from typing import Any
import requests

_TIMEOUT = max(5, int((os.getenv("PHI4_TIMEOUT_SECONDS") or "25").strip()))
_ENDPOINT = os.getenv("PHI4_ENDPOINT", "").rstrip("/")
_API_KEY = os.getenv("PHI4_API_KEY", "").strip()
_MODEL = os.getenv("PHI4_MODEL", "Phi-4").strip()
_ENABLED = os.getenv("PHI4_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def available() -> bool:
    return bool(_ENABLED and _ENDPOINT and _API_KEY and _MODEL)


def _chat(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1800) -> str:
    if not available():
        raise RuntimeError("Phi-4 is not configured")
    # AICredits is OpenAI-compatible. Its base URL already includes /v1,
    # so use /chat/completions and Bearer authentication.
    if _ENDPOINT.endswith("/v1"):
        url = f"{_ENDPOINT}/chat/completions"
    elif _ENDPOINT.endswith("/openai/v1"):
        url = f"{_ENDPOINT}/chat/completions"
    else:
        url = f"{_ENDPOINT}/v1/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Phi-4 returned no choices")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("Phi-4 returned empty content")
    return content


_NEWS_SYSTEM = """You are the senior editor for PoliticsHub. Accuracy, source fidelity, and neutral wording are mandatory.
Use ONLY facts present in supplied source material. Never invent, guess, infer, embellish, or silently change names, dates, numbers, quotes, allegations, locations, motives, or claims. Preserve uncertainty and attribution exactly in meaning.
Separate reported claims from established facts. Use neutral, non-partisan language.
Do not praise or attack political parties, politicians, governments, countries, or
ideologies. If sources disagree, preserve the disagreement instead of choosing a
side. Do not mention that you are an AI. Return plain text only."""


def rewrite_article(title: str, source_text: str, category: str = "general") -> dict[str, str]:
    prompt = f"""Rewrite this news item into publication-ready copy.

Category: {category}
Original headline: {title}

Source material:
{source_text[:30000]}

Return exactly these four labelled sections:
HEADLINE:
SUMMARY:
ARTICLE:
NEUTRALITY:
For NEUTRALITY, give PASS or REVIEW followed by one short reason.
"""
    raw = _chat(_NEWS_SYSTEM, prompt, temperature=0.15, max_tokens=2600)
    return _parse_sections(raw, ("HEADLINE", "SUMMARY", "ARTICLE", "NEUTRALITY"))


def synthesize_sources(title: str, source_materials: list[dict[str, Any]], category: str = "general") -> dict[str, str]:
    packets = []
    for item in source_materials[:8]:
        name = str(item.get("source_name") or "Source")
        text = str(item.get("text") or "").strip()
        if text:
            packets.append(f"--- {name} ---\n{text[:10000]}")
    if not packets:
        return rewrite_article(title, "", category)
    prompt = f"""Synthesize the following independent reports into one neutral article.

Category: {category}
Working headline: {title}

{chr(10).join(packets)}

Return exactly:
HEADLINE:
SUMMARY:
ARTICLE:
NEUTRALITY:
Use only information present in the reports. Preserve source disagreement and do
not manufacture consensus. Keep the article factual and suitable for publication.
"""
    raw = _chat(_NEWS_SYSTEM, prompt, temperature=0.15, max_tokens=3200)
    return _parse_sections(raw, ("HEADLINE", "SUMMARY", "ARTICLE", "NEUTRALITY"))


def neutrality_check(title: str, article: str) -> dict[str, str]:
    prompt = f"""Audit this PoliticsHub copy for political neutrality and factual wording.

HEADLINE: {title}
ARTICLE:
{article[:30000]}

Return exactly:
VERDICT: PASS or REVIEW
REASON: one concise reason
CHANGES: concise list of wording changes, or NONE
Do not add facts.
"""
    raw = _chat(_NEWS_SYSTEM, prompt, temperature=0.0, max_tokens=500)
    return _parse_sections(raw, ("VERDICT", "REASON", "CHANGES"))


def translate(text: str, target_language: str) -> str:
    language = target_language.strip().lower()
    if language not in {"english", "hindi", "marathi"}:
        raise ValueError("target_language must be English, Hindi, or Marathi")
    return _chat(
        "Translate faithfully. Preserve every factual detail, name, number, date, "
        "qualification and uncertainty. Do not add or remove claims. Return only "
        f"the {language.title()} translation.",
        text[:30000],
        temperature=0.0,
        max_tokens=2200,
    )


def reel_script(title: str, article: str) -> str:
    return _chat(
        """Create a concise neutral Instagram news Reel script from the supplied
final article. Use only supplied facts. Do not add claims. No emojis, source-name
promotions, clickbait, or political persuasion. Return 5-7 short spoken/text
lines, ending with a neutral follow-for-updates line.""",
        f"HEADLINE: {title}\nARTICLE:\n{article[:18000]}",
        temperature=0.2,
        max_tokens=700,
    )


def newsroom_assistant(instruction: str, context: str = "") -> str:
    return _chat(
        """You are the internal PoliticsHub newsroom assistant. Help with editorial
operations, source comparison, headlines, summaries, translations, and QA. Never
invent facts or make political persuasion. If context is insufficient, say so.""",
        f"Instruction:\n{instruction}\n\nContext:\n{context[:30000]}",
        temperature=0.2,
        max_tokens=1600,
    )


def _parse_sections(raw: str, names: tuple[str, ...]) -> dict[str, str]:
    result = {name: "" for name in names}
    current = None
    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        match = next((name for name in names if upper.startswith(name + ":")), None)
        if match:
            current = match
            result[match] = stripped.split(":", 1)[1].strip()
        elif current:
            result[current] = (result[current] + "\n" + stripped).strip()
    return result
