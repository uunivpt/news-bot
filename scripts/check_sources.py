"""Read-only RSS diagnostics. Does not publish articles or access the database.

Run: PYTHONPATH=. python scripts/check_sources.py --output artifacts/sources.json
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app.collector import load_sources
from app.rss import collect_rss
from scripts.offline_snapshot import parse_date


def inspect_source(source, now):
    result = {"name": source["name"], "checked_at": now.isoformat(), "items": 0}
    try:
        items = collect_rss(source)
        result["items"] = len(items)
        dates = [stamp for item in items if (stamp := parse_date(item.published_at))]
        newest = max(dates, default=None)
        result["latest_published_at"] = newest.isoformat() if newest else None
        result["status"] = ("empty" if not items else "undated" if not newest else
                            "future-dated" if newest > now + timedelta(minutes=30) else
                            "stale" if newest < now - timedelta(hours=72) else "available")
    except Exception as error:
        result.update(status="unavailable", error=type(error).__name__)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    config = load_sources()
    sources = [source for group in ("rss", "hindi_rss") for source in config.get(group, [])
               if source.get("enabled", True) and source.get("public_source")]
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(lambda source: inspect_source(source, now), sources))
    report = {"checked_at": now.isoformat(), "scope": "Configured public RSS metadata; no database or publishing writes",
              "sources": checks}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
