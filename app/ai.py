import json
import os
from typing import Any

import requests


class AIService:
    """Optional OpenAI-compatible AI service. Disabled when AI_API_URL/AI_API_KEY are absent."""
    def __init__(self) -> None:
        self.base_url = os.getenv("AI_API_URL", "").rstrip("/")
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "")

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def chat(self, prompt: str) -> str | None:
        if not self.enabled:
            return None
        url = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            timeout=60,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def summarize(self, title: str, summary: str | None) -> str | None:
        return self.chat(
            "Write a neutral 2-3 sentence news summary. Do not add facts that are not in the source. "
            f"Title: {title}\nSource text: {summary or title}"
        )

    def write_article(self, title: str, source_text: str) -> str | None:
        return self.chat(
            "Draft a neutral news article from the supplied source text. Clearly attribute claims, "
            "do not invent facts, and do not copy long passages. Include a short headline and concise body.\n"
            f"Title: {title}\nSource: {source_text}"
        )
