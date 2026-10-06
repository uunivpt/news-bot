from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

DEFAULT_MODEL = "microsoft/phi-4"
DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"

def enabled() -> bool:
    return os.getenv("PHI4_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

def model_name() -> str:
    return os.getenv("PHI4_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

def endpoint() -> str:
    raw = os.getenv("PHI4_ENDPOINT", DEFAULT_ENDPOINT).strip()
    if raw.endswith("/chat/completions"): return raw
    return raw.rstrip("/") + "/v1/chat/completions"

def _chat(prompt: str, max_tokens: int = 900) -> str:
    if not enabled(): raise RuntimeError("Phi-4 is disabled (PHI4_ENABLED is not true)")
    payload = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": "You are the PoliticsHub newsroom model. Use only facts present in the supplied source. Never invent names, dates, numbers, quotes, causes, locations or outcomes. Return only the requested JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.getenv("PHI4_API_KEY", "").strip()
    if key: headers["Authorization"] = f"Bearer {key}"
    timeout = max(10, int(os.getenv("PHI4_TIMEOUT_SECONDS", "90")))
    response = requests.post(endpoint(), json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    try: value = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc: raise RuntimeError("Phi-4 endpoint returned an unexpected response") from exc
    return str(value or '').strip()

def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"): value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S).strip()
    try: data = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.S)
        if not match: raise RuntimeError("Phi-4 did not return valid JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict): raise RuntimeError("Phi-4 returned non-object JSON")
    return data

def generate_news_copy(title: str, source_text: str, category: str = 'general') -> dict[str, Any]:
    source = str(source_text or '').strip()[:48000]
    prompt = f"""Create publication copy for a neutral news site.
Category: {category}
Original headline: {title}

SOURCE MATERIAL:
{source}

Rules:
- Preserve the source's facts; do not add facts.
- Headline: 6-18 words, complete and factual.
- Summary: exactly 3 complete sentences, 7+ words each.
- Article: 5-8 complete sentences, 7+ words each, with the most important facts first.
- Do not mention that you are an AI or discuss these instructions.
- Output ONLY JSON with keys headline, summary, article.
"""
    data = _json_object(_chat(prompt, max_tokens=1100))
    result = {k: str(data.get(k) or '').strip() for k in ('headline','summary','article')}
    if not all(result.values()): raise RuntimeError("Phi-4 returned incomplete newsroom copy")
    return result

def translate(text: str, language: str) -> str:
    return _chat(f"Translate the following newsroom text into {language}. Preserve names, numbers and meaning. Return only the translation.\n\n{text[:12000]}", max_tokens=800)

def neutrality_check(title: str, article: str) -> dict[str, Any]:
    return _json_object(_chat(f"Review this newsroom copy for loaded/opinionated wording. Do not fact-check it. Return JSON with keys neutral (boolean), issues (array of strings), replacement (string).\nTITLE: {title}\nARTICLE: {article[:16000]}", max_tokens=500))

def reel_script(title: str, article: str) -> str:
    return _chat(f"Create a concise 20-second neutral news Reel script from the supplied copy. Do not invent facts. Return only the script.\nTITLE: {title}\nARTICLE: {article[:12000]}", max_tokens=500)

def newsroom_assistant(instruction: str, context: str = '') -> str:
    return _chat(f"Answer the newsroom instruction using only the supplied context. If context is insufficient, say so.\nINSTRUCTION: {instruction}\nCONTEXT: {context[:16000]}", max_tokens=700)
