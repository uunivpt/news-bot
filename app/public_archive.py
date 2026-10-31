"""Durable copies of previously public feed records; never imports into Neon.

The rolling homepage feed is not an archive. Keep its published records here
before they age out, using only public fields and original IDs/dates.
"""
import gzip
import json
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ARCHIVE_PATH = Path(__file__).parent / "data" / "public-archive.json.gz"
_identity_cache = (None, {})
FIELDS = ("id", "title", "summary", "bot_summary", "bot_article", "source_name",
          "source_type", "url", "published_at", "published_at_site", "category",
          "image_url", "image_source", "image_license", "public_source")


def timestamp(row):
    raw = str(row.get("published_at_site") or row.get("published_at") or "")
    try:
        date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(raw)
        except (ValueError, TypeError):
            return 0
    return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()


@lru_cache(maxsize=1)
def _load():
    if not ARCHIVE_PATH.exists():
        return ()
    with gzip.open(ARCHIVE_PATH, "rt", encoding="utf-8") as stream:
        return tuple(json.load(stream))


def rows(search=None):
    query = str(search or "").casefold()
    return [dict(row) for row in _load() if not query or query in " ".join(
        str(row.get(key) or "") for key in ("title", "summary", "bot_summary", "bot_article", "source_name")
    ).casefold()]


def by_id(item_id):
    global _identity_cache
    records = _load()
    if _identity_cache[0] is not records:
        _identity_cache = (records, {str(row['id']): row for row in records})
    row = _identity_cache[1].get(str(item_id))
    return dict(row) if row is not None else None


def retain_public_records(incoming, path=ARCHIVE_PATH):
    """Only call with already-published snapshots. Latest version wins by URL."""
    saved = []
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
    merged = {row["url"]: row for row in saved}
    for row in incoming:
        if not isinstance(row, dict) or not row.get("url") or not row.get("title"):
            continue
        if row.get("status", "published") != "published":
            continue
        try:
            item_id = int(row["id"])
        except (KeyError, ValueError, TypeError):
            continue
        if item_id <= 0:
            continue
        safe = {key: row[key] for key in FIELDS if key in row}
        safe.update(id=item_id, status="published")
        merged[row["url"]] = safe
    result = sorted(merged.values(), key=lambda row: (timestamp(row), row["id"]), reverse=True)
    # A duplicate ID must not silently serve the wrong article.
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("Public archive contains conflicting article IDs")
    content = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    compressed = gzip.compress(content, mtime=0)
    if not path.exists() or path.read_bytes() != compressed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(compressed)
        temporary.replace(path)
    _load.cache_clear()
    return len(result)
