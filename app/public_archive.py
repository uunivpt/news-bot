"""Durable copies of previously public feed records; never imports into Neon.

The rolling homepage feed is not an archive. Keep its published records here
before they age out, using only public fields and original IDs/dates.
"""
import hashlib
import gzip
import json
from .news_numbers import news_number, number_index
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ARCHIVE_PATH = Path(__file__).parent / "data" / "public-archive.json.gz"
_identity_cache = (None, {})
FIELDS = ("id", "title", "summary", "bot_summary", "bot_article", "source_name",
          "source_type", "url", "published_at", "published_at_site", "category",
          "image_url", "image_source", "image_license", "image_credit", "public_source", "legacy_ids", "news_number", "phone_public_id", "canonical_public_id", "editorial_featured", "editorial_featured_at")


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
    from .news_search import matching
    records=[dict(row) for row in _load()]
    return matching(records,search) if search else records


def by_id(item_id):
    global _identity_cache
    records = _load()
    if _identity_cache[0] is not records:
        identities = {str(row['id']): row for row in records}
        identities.update({str(alias): row for row in records for alias in row.get('legacy_ids', [])})
        identities.update({news_number({'id':alias}): row for row in records for alias in row.get('legacy_ids', [])})
        identities.update(number_index(records))
        _identity_cache = (records, identities)
    row = _identity_cache[1].get(str(item_id))
    return dict(row) if row is not None else None


def retain_public_records(incoming, path=ARCHIVE_PATH):
    """Only call with already-published snapshots. Latest version wins by URL."""
    saved = []
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
    withheld_path=Path(__file__).parent/'data/archive-withheld.json'
    withheld=set(json.loads(withheld_path.read_text())) if withheld_path.exists() else set()
    allowed=lambda row: hashlib.sha256(str(row.get('url') or '').encode()).hexdigest() not in withheld
    from app.live_publication import publication_key
    merged = {publication_key(row): row for row in saved if allowed(row)}
    for row in incoming:
        if not isinstance(row, dict) or not row.get("url") or not row.get("title") or not allowed(row):
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
        previous = merged.get(publication_key(row), {})
        aliases = set(previous.get('legacy_ids', [])) | set(row.get('legacy_ids', []))
        if previous.get('id') and previous['id'] != item_id: aliases.add(previous['id'])
        safe.update(id=item_id, status="published", legacy_ids=sorted(aliases - {item_id}))
        safe['news_number'] = news_number(safe)
        merged[publication_key(row)] = safe
    result = sorted(merged.values(), key=lambda row: (timestamp(row), row["id"]), reverse=True)
    # A duplicate ID must not silently serve the wrong article.
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("Public archive contains conflicting article IDs")
    for row in result: row['news_number'] = news_number(row)
    number_index(result)  # Fail closed rather than publish an ambiguous public number.
    content = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    compressed = gzip.compress(content, mtime=0)
    if not path.exists() or path.read_bytes() != compressed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(compressed)
        temporary.replace(path)
    _load.cache_clear()
    return len(result)
