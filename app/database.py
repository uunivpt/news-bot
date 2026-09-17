import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any

from .models import NewsItem
from .normalize import fingerprint, normalize_url

CATEGORIES = ("general", "india", "world", "politics", "business", "technology", "sports", "entertainment", "science", "health")
STATUSES = ("pending", "published", "rejected")

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
    instagram_status TEXT NOT NULL DEFAULT 'pending',
    instagram_media_id TEXT,
    instagram_error TEXT,
    instagram_published_at TEXT,
    instagram_attempts INTEGER NOT NULL DEFAULT 0,
    instagram_last_attempt_at TEXT,
    instagram_next_retry_at TEXT,
    instagram_container_id TEXT,
    reel_cloudinary_public_id TEXT,
    instagram_selected INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_name, external_id)
)
"""

ADMIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source_name);
CREATE INDEX IF NOT EXISTS idx_news_category ON news_items(category);
CREATE INDEX IF NOT EXISTS idx_news_status ON news_items(status);
CREATE INDEX IF NOT EXISTS idx_news_review ON news_items(fact_check_status);
CREATE INDEX IF NOT EXISTS idx_news_instagram ON news_items(instagram_status);
CREATE INDEX IF NOT EXISTS idx_news_instagram_retry ON news_items(instagram_status, instagram_next_retry_at);
CREATE INDEX IF NOT EXISTS idx_news_instagram_selected ON news_items(instagram_selected, instagram_status);
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
    "instagram_status": "ALTER TABLE news_items ADD COLUMN instagram_status TEXT NOT NULL DEFAULT 'pending'",
    "instagram_media_id": "ALTER TABLE news_items ADD COLUMN instagram_media_id TEXT",
    "instagram_error": "ALTER TABLE news_items ADD COLUMN instagram_error TEXT",
    "instagram_published_at": "ALTER TABLE news_items ADD COLUMN instagram_published_at TEXT",
    "instagram_attempts": "ALTER TABLE news_items ADD COLUMN instagram_attempts INTEGER NOT NULL DEFAULT 0",
    "instagram_last_attempt_at": "ALTER TABLE news_items ADD COLUMN instagram_last_attempt_at TEXT",
    "instagram_next_retry_at": "ALTER TABLE news_items ADD COLUMN instagram_next_retry_at TEXT",
    "instagram_container_id": "ALTER TABLE news_items ADD COLUMN instagram_container_id TEXT",
    "reel_cloudinary_public_id": "ALTER TABLE news_items ADD COLUMN reel_cloudinary_public_id TEXT",
    "instagram_selected": "ALTER TABLE news_items ADD COLUMN instagram_selected INTEGER NOT NULL DEFAULT 0",
}

DEFAULT_SETTINGS = {
    "instagram_enabled": "true",
    "instagram_daily_limit": "5",
    "instagram_selection_mode": "auto",
    "website_enabled": "true",
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
            self.conn.execute(SCHEMA)
            self.conn.execute(ADMIN_SCHEMA)
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
            self.conn.executescript(sqlite_schema)
            self.conn.executescript(ADMIN_SCHEMA)
            self._migrate_sqlite()
            self.conn.executescript(INDEXES)
            self.conn.commit()
        self._seed_settings()

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

    def _seed_settings(self) -> None:
        now = NewsItem.now_iso()
        for key, value in DEFAULT_SETTINGS.items():
            if self._postgres:
                self.conn.execute("INSERT INTO admin_settings (key, value, updated_at) VALUES (%s, %s, %s) ON CONFLICT (key) DO NOTHING", (key, value, now))
            else:
                self.conn.execute("INSERT OR IGNORE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)", (key, value, now))
        if not self._postgres:
            self.conn.commit()

    def get_settings(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM admin_settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        result.update({str(r["key"] if self._postgres else r[0]): str(r["value"] if self._postgres else r[1]) for r in rows})
        return result

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self.get_settings().get(key, default)

    def set_settings(self, values: dict[str, Any]) -> None:
        now = NewsItem.now_iso()
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            value = str(value)
            if self._postgres:
                self.conn.execute("INSERT INTO admin_settings (key, value, updated_at) VALUES (%s, %s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at", (key, value, now))
            else:
                self.conn.execute("INSERT INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, now))
        if not self._postgres:
            self.conn.commit()

    def instagram_daily_count(self, day_start_iso: str, day_end_iso: str) -> int:
        ph = "%s" if self._postgres else "?"
        row = self.conn.execute(f"SELECT COUNT(*) AS count FROM news_items WHERE instagram_status='published' AND instagram_published_at >= {ph} AND instagram_published_at < {ph}", (day_start_iso, day_end_iso)).fetchone()
        return int(row["count"] if self._postgres else row[0])

    def close(self) -> None:
        self.conn.close()

    def insert(self, item: NewsItem) -> bool:
        normalized_url = normalize_url(item.url)
        url_hash, title_hash = fingerprint(normalized_url, item.title)
        params = (item.source_name, item.source_type, item.title.strip(), item.url, normalized_url, item.published_at, item.summary, item.external_id, url_hash, title_hash, NewsItem.now_iso(), item.category or "general", item.image_url)
        sql = """INSERT INTO news_items (source_name, source_type, title, url, normalized_url, published_at, summary, external_id, url_hash, title_hash, collected_at, category, image_url) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})"""
        if self._postgres:
            cur = self.conn.execute(sql.format(p="%s") + " ON CONFLICT DO NOTHING", params)
            return cur.rowcount == 1
        try:
            self.conn.execute(sql.format(p="?"), params); self.conn.commit(); return True
        except sqlite3.IntegrityError:
            return False

    def insert_many(self, items: Iterable[NewsItem]) -> tuple[int, int]:
        added = skipped = 0
        for item in items:
            if self.insert(item): added += 1
            else: skipped += 1
        return added, skipped

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()
        return int(row["count"] if self._postgres else row[0])

    def latest(self, limit: int = 20, category: str | None = None, status: str | None = None, search: str | None = None, review_status: str | None = None, instagram_status: str | None = None):
        clauses, params = [], []
        if category and category != "all": clauses.append("category = " + ("%s" if self._postgres else "?")); params.append(category)
        if status and status != "all": clauses.append("status = " + ("%s" if self._postgres else "?")); params.append(status)
        if review_status and review_status != "all": clauses.append("fact_check_status = " + ("%s" if self._postgres else "?")); params.append(review_status)
        if instagram_status and instagram_status != "all": clauses.append("instagram_status = " + ("%s" if self._postgres else "?")); params.append(instagram_status)
        if search:
            ph = "%s" if self._postgres else "?"; clauses.append(f"(LOWER(title) LIKE LOWER({ph}) OR LOWER(summary) LIKE LOWER({ph}))"); params.extend([f"%{search}%", f"%{search}%"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""; ph = "%s" if self._postgres else "?"
        return self.conn.execute(f"SELECT * FROM news_items{where} ORDER BY id DESC LIMIT {ph}", (*params, limit)).fetchall()

    def update(self, item_id: int, **fields: Any) -> None:
        allowed = {"title", "summary", "category", "status", "ai_summary", "ai_article", "fact_check_status", "fact_check_notes", "image_url", "approved_at", "published_at_site", "instagram_status", "instagram_media_id", "instagram_error", "instagram_published_at", "instagram_attempts", "instagram_last_attempt_at", "instagram_next_retry_at", "instagram_container_id", "reel_cloudinary_public_id", "instagram_selected"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields: return
        sets, params = [], []; ph = "%s" if self._postgres else "?"
        for key, value in fields.items(): sets.append(f"{key} = {ph}"); params.append(value)
        params.append(item_id); self.conn.execute(f"UPDATE news_items SET {', '.join(sets)} WHERE id = {ph}", params)
        if not self._postgres: self.conn.commit()
