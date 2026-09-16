import os
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import NewsItem
from .normalize import fingerprint, normalize_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    published_at TEXT,
    summary TEXT,
    external_id TEXT,
    url_hash TEXT NOT NULL UNIQUE,
    title_hash TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(source_name, external_id)
);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source_name);
"""

class NewsDatabase:
    """Use PostgreSQL when DATABASE_URL exists; otherwise local SQLite."""
    def __init__(self, path: str = "data/news.db", database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self._postgres = bool(self.database_url)
        if self._postgres:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(self.database_url, row_factory=dict_row)
            self.conn.autocommit = True
            self.conn.execute(SCHEMA)
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            sqlite_schema = SCHEMA.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(sqlite_schema)
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert(self, item: NewsItem) -> bool:
        normalized_url = normalize_url(item.url)
        url_hash, title_hash = fingerprint(normalized_url, item.title)
        params = (item.source_name, item.source_type, item.title.strip(), item.url,
                  normalized_url, item.published_at, item.summary, item.external_id,
                  url_hash, title_hash, NewsItem.now_iso())
        sql = """INSERT INTO news_items
            (source_name, source_type, title, url, normalized_url, published_at,
             summary, external_id, url_hash, title_hash, collected_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"""
        if self._postgres:
            try:
                self.conn.execute(sql.format(p="%s") + " ON CONFLICT DO NOTHING", params)
                return self.conn.info.transaction_status == 0
            except Exception:
                return False
        try:
            self.conn.execute(sql.format(p="?"), params)
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_many(self, items: Iterable[NewsItem]) -> tuple[int, int]:
        added = skipped = 0
        for item in items:
            if self.insert(item): added += 1
            else: skipped += 1
        return added, skipped

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0])

    def latest(self, limit: int = 20):
        placeholder = "%s" if self._postgres else "?"
        return self.conn.execute(f"SELECT * FROM news_items ORDER BY id DESC LIMIT {placeholder}", (limit,)).fetchall()
