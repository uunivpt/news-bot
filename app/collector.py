import json
import logging
from pathlib import Path
from typing import Any, Callable

from .database import NewsDatabase
from .rss import collect_rss
from .news_api import collect_newsapi, collect_newsdata
from .telegram_public import collect_public_telegram
from .website_monitor import collect_website
from .phase_system import ensure_schema, run as agent_run, cluster_stories

logger = logging.getLogger(__name__)

COLLECTORS: dict[str, Callable[[dict[str, Any]], list]] = {
    "rss": collect_rss,
    "telegram": collect_public_telegram,
    "website": collect_website,
    "newsapi": collect_newsapi,
    "newsdata": collect_newsdata,
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
    ensure_schema(db)
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
                with agent_run(db, "trend", "collect_source", metadata={"source": source.get("name","unknown"), "type": source_type}):
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
    try:
        with agent_run(db, "research", "cluster_stories"):
            cluster_stories(db, 250)
    except Exception:
        logger.exception("Story clustering failed")
    return added, skipped
