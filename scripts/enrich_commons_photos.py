"""Attach strictly matched, Commons-licensed *illustrative file photos* to the public feed."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.commons_photos import CACHE, SNAPSHOT, enrich

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not SNAPSHOT.exists():
        return
    try:
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > 300:
            raise ValueError("News snapshot must contain a bounded list")
    except (OSError, ValueError) as error:
        log.warning("Photo enrichment skipped: invalid snapshot (%s)", type(error).__name__)
        return
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    updated, next_cache, matches, queries = enrich(rows, cache, max_lookup=4)
    current = json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
    amended = json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n"
    if current != amended:
        SNAPSHOT.write_text(amended, encoding="utf-8")
    existing_cache = json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    next_text = json.dumps(next_cache, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if existing_cache != next_text:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(next_text, encoding="utf-8")
    log.info("Illustrative file photos: %s matching stories; %s Commons lookups; %s cache subjects",
             matches, queries, len(next_cache))


if __name__ == "__main__":
    main()
