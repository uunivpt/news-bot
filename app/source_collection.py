"""Persist actual collector checks; dashboard reads never create this table."""
from datetime import datetime, timezone
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def ensure_collection_schema(database):
    database.conn.execute("""CREATE TABLE IF NOT EXISTS ph_source_collection (
        source_type TEXT NOT NULL, source_name TEXT NOT NULL,
        last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
        status TEXT NOT NULL, item_count INTEGER, added_count INTEGER,
        duplicate_count INTEGER, PRIMARY KEY(source_type,source_name))""")
    if not database._postgres:
        database.conn.commit()


def record_collection(database, source_type, source_name, *, status,
                      item_count=None, added_count=None, duplicate_count=None,
                      error=None):
    """Save one attempted check without exception text, URLs or credentials."""
    if status not in {"checking", "healthy", "failed", "not_configured"}:
        raise ValueError("Unknown collection status")
    now = datetime.now(timezone.utc).isoformat()
    # Exception messages can contain an API key, URL, hostname or SQL details.
    safe_error = type(error).__name__ if isinstance(error, BaseException) else error
    if safe_error and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", str(safe_error)):
        safe_error = "CollectionError"
    values = (str(source_type), str(source_name), now,
              now if status == "healthy" else None, safe_error, status,
              item_count, added_count, duplicate_count)
    p = "%s" if database._postgres else "?"
    database.conn.execute(
        "INSERT INTO ph_source_collection(source_type,source_name,last_attempt_at,"
        "last_success_at,last_error,status,item_count,added_count,duplicate_count) "
        "VALUES (" + ",".join([p] * len(values)) + ") "
        "ON CONFLICT(source_type,source_name) DO UPDATE SET "
        "last_attempt_at=excluded.last_attempt_at,"
        "last_success_at=COALESCE(excluded.last_success_at,ph_source_collection.last_success_at),"
        "last_error=excluded.last_error,status=excluded.status,"
        "item_count=excluded.item_count,added_count=excluded.added_count,"
        "duplicate_count=excluded.duplicate_count", values)
    if not database._postgres:
        database.conn.commit()
