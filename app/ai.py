from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


class AIService:
    """OpenAI-compatible newsroom rewriting/enrichment service."""
    def __init__(self) -> None:
        self.base_url = os.getenv("AI_API_URL", "").rstrip("/")
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "")
        self.timeout = max(30, int(os.getenv("AI_TIMEOUT_SECONDS", "90")))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def chat(self, prompt: str, *, system: str | None = None, temperature: float = 0.15, max_tokens: int = 2500) -> str | None:
        if not self.enabled:
            return None
        url = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in content)
        return str(content).strip()

    @staticmethod
    def _json(text: str | None) -> dict[str, Any] | None:
        if not text:
            return None
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S).strip()
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None

    def newsroom_rewrite(self, original_title: str, source_text: str, category: str = "general") -> dict[str, str] | None:
        if not self.enabled:
            return None
        system = (
            "You are a professional digital newsroom editor. Produce factual, neutral, original journalism from supplied source material. "
            "Never invent facts, names, quotes, numbers, locations, dates, motives, or outcomes. If a claim is uncertain, attribute it as a claim. "
            "Do not copy source wording. Do not mention the source publication, Telegram, or URLs. Do not use emojis. "
            "Do not turn allegations into facts. Keep chronology clear and include all material facts present in the source. "
            "Return ONLY valid JSON with exactly three string fields: headline, summary, article."
        )
        prompt = f"""Rewrite this into an original newsroom story.

CATEGORY: {category}
ORIGINAL HEADLINE: {original_title}
SOURCE MATERIAL:
{source_text[:24000]}

Requirements:
- headline: accurate, concise, natural, no clickbait, 8-18 words.
- summary: 2-3 complete sentences for a front-page card; give the essential who/what/where/when/why-known-now.
- article: a complete 6-10 paragraph article, normally 450-900 words when the source supports it. Start with the key development, then context, chronology, confirmed details, and relevant uncertainty. Do not pad it and do not stop mid-sentence.
- Preserve important factual details from the source, but express them in fresh wording.
- Never invent missing details just to make the article longer.
"""
        raw = self.chat(prompt, system=system, temperature=0.1, max_tokens=3000)
        data = self._json(raw)
        if not data:
            return None
        headline = re.sub(r"\s+", " ", str(data.get("headline") or "")).strip()
        summary = re.sub(r"\s+", " ", str(data.get("summary") or "")).strip()
        article = str(data.get("article") or "").strip()
        if not headline or len(summary) < 80 or len(article) < 300:
            return None
        return {"headline": headline[:500], "summary": summary[:1800], "article": article[:14000]}

    def summarize(self, title: str, summary: str | None) -> str | None:
        result = self.newsroom_rewrite(title, summary or title)
        return result["summary"] if result else None

    def write_article(self, title: str, source_text: str) -> str | None:
        result = self.newsroom_rewrite(title, source_text)
        return result["article"] if result else None
