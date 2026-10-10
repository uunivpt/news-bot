import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Callable

from .database import NewsDatabase
from .rss import collect_rss
from .news_api import collect_newsapi, collect_newsdata
from .telegram_public import collect_public_telegram
from .website_monitor import collect_website
from .x_source import collect_x
from .phase_system import ensure_schema, run as agent_run, cluster_stories

logger = logging.getLogger(__name__)

def _safe_http_url(value: str) -> bool:
    try:
        parsed=urlparse(str(value or "").strip())
        return parsed.scheme.lower() in {"http","https"} and bool(parsed.netloc)
    except Exception:
        return False

def _source_due(db: NewsDatabase, source_type: str, source: dict[str, Any]) -> bool:
    try:
        minutes=max(0,int(source.get("check_every_minutes",0)))
    except (TypeError,ValueError):
        minutes=0
    if minutes<=0:
        return True
    key=f"collector_last:{source_type}:{source.get('name','unknown')}"
    raw=db.get_settings().get(key)
    if not raw:
        return True
    try:
        last=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        last=last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)-last >= timedelta(minutes=minutes)
    except ValueError:
        return True

COLLECTORS: dict[str, Callable[[dict[str, Any]], list]] = {
    "rss": collect_rss,
    "telegram": collect_public_telegram,
    "website": collect_website,
    "newsapi": collect_newsapi,
    "newsdata": collect_newsdata,
    "x": collect_x,
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
    healthy = 0
    failures = []
    for source_type, sources in config.items():
        collector = COLLECTORS.get(source_type)
        if collector is None:
            logger.warning("Unknown source type: %s", source_type)
            continue
        for source in sources:
            if not source.get("enabled", True):
                continue
            if source_type == "x" and not os.getenv("X_API_BEARER_TOKEN", "").strip():
                logger.warning("X source %s skipped: X_API_BEARER_TOKEN not configured", source.get("name", "unknown"))
                continue
            try:
                if not _source_due(db, source_type, source):
                    logger.info("%s/%s: skipped; check_every_minutes has not elapsed",source_type,source.get("name","unknown"))
                    continue
                with agent_run(db, "trend", "collect_source", metadata={"source": source.get("name","unknown"), "type": source_type}):
                    items = collector(source)
                    healthy += 1
                    safe_items=[]
                    rejected_urls=0
                    for item in items:
                        if _safe_http_url(getattr(item,"url","")):
                            safe_items.append(item)
                        else:
                            rejected_urls+=1
                    if rejected_urls:
                        logger.warning("%s/%s: rejected %d item(s) with non-http(s) URLs",source_type,source.get("name","unknown"),rejected_urls)
                    source_added, source_skipped = db.insert_many(safe_items)
                added += source_added
                skipped += source_skipped
                db.set_settings({f"collector_last:{source_type}:{source.get('name','unknown')}":datetime.now(timezone.utc).isoformat()})
                logger.info(
                    "%s/%s: found=%d added=%d duplicate=%d",
                    source_type,
                    source.get("name", "unknown"),
                    len(safe_items),
                    source_added,
                    source_skipped,
                )
            except Exception:
                name = source.get("name", "unknown")
                failures.append(name)
                logger.exception("Collector failed for %s", name)
                if os.getenv("GITHUB_ACTIONS"):
                    print("::warning::A news source failed; see the collection summary.")
    try:
        with agent_run(db, "research", "cluster_stories"):
            cluster_stories(db, 250)
    except Exception:
        logger.exception("Story clustering failed")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as report:
            report.write(f"\n### Source collection\nSuccessful checks: {healthy}; failed checks: {len(failures)}; new items: {added}.\n")
            for name in failures:
                report.write(f"- Failed source: {name}\n")
    if failures and not healthy:
        raise RuntimeError("All attempted news sources failed")
    return added, skipped
