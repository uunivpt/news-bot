import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any

from .models import NewsItem
from .normalize import fingerprint, normalize_url

CATEGORIES = ("general", "india", "world", "politics", "business", "technology", "sports", "entertainment", "science", "health")
STATUSES = ("pending", "review", "approved", "published", "rejected")

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
    category TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'pending',
    image_url TEXT,
    ai_summary TEXT,
    ai_article TEXT,
    fact_check_status TEXT NOT NULL DEFAULT 'pending',
    fact_check_notes TEXT,
    approved_at TEXT,
    published_at_site TEXT,
    UNIQUE(source_name, external_id)
)
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source_name);
CREATE INDEX IF NOT EXISTS idx_news_category ON news_items(category);
CREATE INDEX IF NOT EXISTS idx_news_status ON news_items(status);
"""

MIGRATIONS = {
    "category": "ALTER TABLE news_items ADD COLUMN category TEXT NOT NULL DEFAULT 'general'",
    "status": "ALTER TABLE news_items ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'",
    "image_url": "ALTER TABLE news_items ADD COLUMN image_url TEXT",
    "ai_summary": "ALTER TABLE news_items ADD COLUMN ai_summary TEXT",
    "ai_article": "ALTER TABLE news_items ADD COLUMN ai_article TEXT",
    "fact_check_status": "ALTER TABLE news_items ADD COLUMN fact_check_status TEXT NOT NULL DEFAULT 'pending'",
    "fact_check_notes": "ALTER TABLE news_items ADD COLUMN fact_check_notes TEXT",
    "approved_at": "ALTER TABLE news_items ADD COLUMN approved_at TEXT",
    "published_at_site": "ALTER TABLE news_items ADD COLUMN published_at_site TEXT",
}


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
            # Existing databases may not have newly added columns. Run migrations
            # before creating indexes that depend on those columns.
            self.conn.execute(SCHEMA)
            self._migrate_postgres()
            for statement in INDEXES.split(";"):
                statement = statement.strip()
                if statement:
                    self.conn.execute(statement)
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            sqlite_schema = SCHEMA.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute(sqlite_schema)
            self._migrate_sqlite()
            self.conn.executescript(INDEXES)
            self.conn.commit()

    def _migrate_postgres(self) -> None:
        for sql in MIGRATIONS.values():
            try:
                self.conn.execute(sql)
            except Exception as exc:
                if "already exists" not in str(exc).lower():
                    raise

    def _migrate_sqlite(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(news_items)").fetchall()}
        for name, sql in MIGRATIONS.items():
            if name not in cols:
                self.conn.execute(sql)

    def close(self) -> None:
        self.conn.close()

    def insert(self, item: NewsItem) -> bool:
        normalized_url = normalize_url(item.url)
        url_hash, title_hash = fingerprint(normalized_url, item.title)
        params = (
            item.source_name, item.source_type, item.title.strip(), item.url,
            normalized_url, item.published_at, item.summary, item.external_id,
            url_hash, title_hash, NewsItem.now_iso(), item.category or "general",
            item.image_url,
        )
        sql = """INSERT INTO news_items
            (source_name, source_type, title, url, normalized_url, published_at,
             summary, external_id, url_hash, title_hash, collected_at, category, image_url)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"""
        if self._postgres:
            cur = self.conn.execute(sql.format(p="%s") + " ON CONFLICT DO NOTHING", params)
            return cur.rowcount == 1
        try:
            self.conn.execute(sql.format(p="?"), params)
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
        row = self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()
        return int(row["count"] if self._postgres else row[0])

    def latest(self, limit: int = 20, category: str | None = None, status: str | None = None, search: str | None = None):
        clauses, params = [], []
        if category and category != "all":
            clauses.append("category = " + ("%s" if self._postgres else "?")); params.append(category)
        if status and status != "all":
            clauses.append("status = " + ("%s" if self._postgres else "?")); params.append(status)
        if search:
            ph = "%s" if self._postgres else "?"
            clauses.append(f"(LOWER(title) LIKE LOWER({ph}) OR LOWER(summary) LIKE LOWER({ph}))")
            params.extend([f"%{search}%", f"%{search}%"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        ph = "%s" if self._postgres else "?"
        return self.conn.execute(
            f"SELECT * FROM news_items{where} ORDER BY id DESC LIMIT {ph}",
            (*params, limit),
        ).fetchall()

    def update(self, item_id: int, **fields: Any) -> None:
        allowed = {"category", "status", "ai_summary", "ai_article", "fact_check_status", "fact_check_notes", "image_url", "approved_at", "published_at_site"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        sets, params = [], []
        ph = "%s" if self._postgres else "?"
        for key, value in fields.items():
            sets.append(f"{key} = {ph}"); params.append(value)
        params.append(item_id)
        self.conn.execute(f"UPDATE news_items SET {', '.join(sets)} WHERE id = {ph}", params)
        if not self._postgres:
            self.conn.commit()
