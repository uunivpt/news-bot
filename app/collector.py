import json
import logging
from pathlib import Path
from typing import Any, Callable

from .database import NewsDatabase
from .rss import collect_rss
from .telegram_public import collect_public_telegram

logger = logging.getLogger(__name__)


COLLECTORS: dict[str, Callable[[dict[str, Any]], list]] = {
    "rss": collect_rss,
    "telegram": collect_public_telegram,
}


def load_sources(path: str = "config/sources.json") -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy config/sources.example.json to {path} and add your sources."
        )
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def collect_once(config: dict[str, Any], db: NewsDatabase) -> tuple[int, int]:
    added = skipped = 0
    for source_type, sources in config.items():
        collector = COLLECTORS.get(source_type)
        if collector is None:
            logger.warning("Unknown source type: %s", source_type)
            continue
        for source in sources:
            if not source.get("enabled", True):
                continue
            try:
                items = collector(source)
                source_added, source_skipped = db.insert_many(items)
                added += source_added
                skipped += source_skipped
                logger.info(
                    "%s/%s: found=%d added=%d duplicate=%d",
                    source_type,
                    source.get("name", "unknown"),
                    len(items),
                    source_added,
                    source_skipped,
                )
            except Exception:
                logger.exception("Collector failed for %s", source.get("name", "unknown"))
    return added, skipped
