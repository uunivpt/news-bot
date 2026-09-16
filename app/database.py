import sqlite3
from pathlib import Path
from typing import Iterable

from .models import NewsItem
from .normalize import fingerprint, normalize_url


SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    def __init__(self, path: str = "data/news.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert(self, item: NewsItem) -> bool:
        normalized_url = normalize_url(item.url)
        url_hash, title_hash = fingerprint(normalized_url, item.title)
        try:
            self.conn.execute(
                """INSERT INTO news_items
                (source_name, source_type, title, url, normalized_url,
                 published_at, summary, external_id, url_hash, title_hash, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.source_name, item.source_type, item.title.strip(), item.url,
                    normalized_url, item.published_at, item.summary, item.external_id,
                    url_hash, title_hash, NewsItem.now_iso(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_many(self, items: Iterable[NewsItem]) -> tuple[int, int]:
        added = skipped = 0
        for item in items:
            if self.insert(item):
                added += 1
            else:
                skipped += 1
        return added, skipped

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0])

    def latest(self, limit: int = 20):
        return self.conn.execute(
            "SELECT * FROM news_items ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
