from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class NewsItem:
    source_name: str
    source_type: str
    title: str
    url: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    external_id: Optional[str] = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
