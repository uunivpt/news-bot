from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any
from datetime import datetime, timedelta
from .models import NewsItem
from .normalize import fingerprint, normalize_url

CATEGORIES = ("general", "india", "world", "politics", "business", "technology", "sports", "entertainment", "science", "health")
STATUSES = ("pending", "published", "rejected")
SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
 id BIGSERIAL PRIMARY KEY, source_name TEXT NOT NULL, source_type TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT NOT NULL, normalized_url TEXT NOT NULL, published_at TEXT,
 summary TEXT, external_id TEXT, url_hash TEXT NOT NULL UNIQUE, title_hash TEXT NOT NULL,
 collected_at TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', status TEXT NOT NULL DEFAULT 'pending',
 image_url TEXT, public_source INTEGER NOT NULL DEFAULT 0,
 ai_summary TEXT, ai_article TEXT, bot_summary TEXT, bot_article TEXT,
 fact_check_status TEXT NOT NULL DEFAULT 'pending', fact_check_notes TEXT, approved_at TEXT, published_at_site TEXT,
 instagram_status TEXT NOT NULL DEFAULT 'pending', instagram_media_id TEXT, instagram_error TEXT,
 instagram_published_at TEXT, instagram_attempts INTEGER NOT NULL DEFAULT 0, instagram_last_attempt_at TEXT,
 instagram_next_retry_at TEXT, instagram_container_id TEXT, reel_cloudinary_public_id TEXT, reel_cloudinary_url TEXT,
 instagram_selected INTEGER NOT NULL DEFAULT 0, image_source TEXT, image_license TEXT, image_credit TEXT, image_source_url TEXT, image_search_query TEXT, image_selection_score INTEGER, image_local_path TEXT, image_width INTEGER, image_height INTEGER, image_selected_at TEXT, UNIQUE(source_name, external_id)
)
"""
ADMIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
)
"""
ACTIVITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_activity (
 id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL, action TEXT NOT NULL, item_id BIGINT,
 details TEXT, created_at TEXT NOT NULL
)
"""
# Persistent authentication throttling must be defined before connection-time schema creation.
NEWSLETTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
 email TEXT PRIMARY KEY, subscribed_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'website', confirmed INTEGER NOT NULL DEFAULT 0
)
"""
AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_login_attempts (
 id BIGSERIAL PRIMARY KEY, attempt_key TEXT NOT NULL, attempted_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_news_instagram_schedule ON news_items(instagram_status, instagram_scheduled_at);
CREATE INDEX IF NOT EXISTS idx_news_instagram_queue_order ON news_items(instagram_selected, instagram_queue_order);
CREATE INDEX IF NOT EXISTS idx_news_views ON news_items(view_count DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_login_attempts_key_time ON admin_login_attempts(attempt_key, attempted_at);
"""
MIGRATIONS = {
 "category":"ALTER TABLE news_items ADD COLUMN category TEXT NOT NULL DEFAULT 'general'", "status":"ALTER TABLE news_items ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'",
 "image_url":"ALTER TABLE news_items ADD COLUMN image_url TEXT", "public_source":"ALTER TABLE news_items ADD COLUMN public_source INTEGER NOT NULL DEFAULT 0",
 "ai_summary":"ALTER TABLE news_items ADD COLUMN ai_summary TEXT", "ai_article":"ALTER TABLE news_items ADD COLUMN ai_article TEXT",
 "bot_summary":"ALTER TABLE news_items ADD COLUMN bot_summary TEXT", "bot_article":"ALTER TABLE news_items ADD COLUMN bot_article TEXT",
 "fact_check_status":"ALTER TABLE news_items ADD COLUMN fact_check_status TEXT NOT NULL DEFAULT 'pending'", "fact_check_notes":"ALTER TABLE news_items ADD COLUMN fact_check_notes TEXT",
 "approved_at":"ALTER TABLE news_items ADD COLUMN approved_at TEXT", "published_at_site":"ALTER TABLE news_items ADD COLUMN published_at_site TEXT",
 "instagram_status":"ALTER TABLE news_items ADD COLUMN instagram_status TEXT NOT NULL DEFAULT 'pending'", "instagram_media_id":"ALTER TABLE news_items ADD COLUMN instagram_media_id TEXT",
 "instagram_error":"ALTER TABLE news_items ADD COLUMN instagram_error TEXT", "instagram_published_at":"ALTER TABLE news_items ADD COLUMN instagram_published_at TEXT",
 "instagram_attempts":"ALTER TABLE news_items ADD COLUMN instagram_attempts INTEGER NOT NULL DEFAULT 0", "instagram_last_attempt_at":"ALTER TABLE news_items ADD COLUMN instagram_last_attempt_at TEXT",
 "instagram_next_retry_at":"ALTER TABLE news_items ADD COLUMN instagram_next_retry_at TEXT", "instagram_container_id":"ALTER TABLE news_items ADD COLUMN instagram_container_id TEXT",
 "reel_cloudinary_public_id":"ALTER TABLE news_items ADD COLUMN reel_cloudinary_public_id TEXT", "reel_cloudinary_url":"ALTER TABLE news_items ADD COLUMN reel_cloudinary_url TEXT", "instagram_selected":"ALTER TABLE news_items ADD COLUMN instagram_selected INTEGER NOT NULL DEFAULT 0",
 "instagram_scheduled_at":"ALTER TABLE news_items ADD COLUMN instagram_scheduled_at TEXT",
 "instagram_queue_order":"ALTER TABLE news_items ADD COLUMN instagram_queue_order INTEGER NOT NULL DEFAULT 0", "image_source":"ALTER TABLE news_items ADD COLUMN image_source TEXT", "image_license":"ALTER TABLE news_items ADD COLUMN image_license TEXT", "image_credit":"ALTER TABLE news_items ADD COLUMN image_credit TEXT", "image_source_url":"ALTER TABLE news_items ADD COLUMN image_source_url TEXT", "image_search_query":"ALTER TABLE news_items ADD COLUMN image_search_query TEXT", "image_selection_score":"ALTER TABLE news_items ADD COLUMN image_selection_score INTEGER", "image_local_path":"ALTER TABLE news_items ADD COLUMN image_local_path TEXT", "image_width":"ALTER TABLE news_items ADD COLUMN image_width INTEGER", "image_height":"ALTER TABLE news_items ADD COLUMN image_height INTEGER", "image_selected_at":"ALTER TABLE news_items ADD COLUMN image_selected_at TEXT",
 "view_count":"ALTER TABLE news_items ADD COLUMN view_count INTEGER NOT NULL DEFAULT 0",
 "last_viewed_at":"ALTER TABLE news_items ADD COLUMN last_viewed_at TEXT",
}
DEFAULT_SETTINGS={"instagram_enabled":"true","instagram_daily_limit":"5","instagram_selection_mode":"auto","instagram_interval_minutes":"0","website_enabled":"true","instagram_paused":"false","instagram_priority_id":""}

class DatabaseUnavailable(RuntimeError):
 """Safe, actionable connection failure without credentials or host details."""

class NewsDatabase:
 _schema_initialized=set()
 def __init__(self,path="data/news.db",database_url=None):
  self.database_url=database_url or os.getenv("DATABASE_URL"); self._postgres=bool(self.database_url)
  if self._postgres:
   # Render PostgreSQL requires TLS; add sslmode when a connection string does not specify it.
   if "sslmode=" not in self.database_url.lower():
    self.database_url += ("&" if "?" in self.database_url else "?") + "sslmode=require"
   import psycopg
   from psycopg.rows import dict_row
   # Mobile DNS/Wi-Fi can briefly lose the database hostname. Retry the initial
   # connection here so a transient network drop does not kill the whole worker.
   last_error = None
   for attempt, delay in enumerate((0, 1, 2), start=1):
    if delay:
     import time
     time.sleep(delay)
    try:
     self.conn=psycopg.connect(self.database_url,row_factory=dict_row,connect_timeout=5)
     break
    except psycopg.OperationalError as exc:
     last_error = exc
     detail=str(exc).lower()
     if "exceeded the quota" in detail or "quota exceeded" in detail:
      raise DatabaseUnavailable("Database quota exhausted; restore capacity in the database provider console.") from None
     if "password authentication failed" in detail:
      raise DatabaseUnavailable("Database credentials rejected; check DATABASE_URL.") from None
     print(f"Database connection attempt {attempt}/3 failed")
   else:
    raise DatabaseUnavailable("Database connection unavailable after three attempts") from None
   self.conn.autocommit=True
   schema_key="postgres:"+self.database_url
   if schema_key not in self._schema_initialized:
    for statement in (SCHEMA, ADMIN_SCHEMA, ACTIVITY_SCHEMA, NEWSLETTER_SCHEMA, AUTH_SCHEMA):
     self.conn.execute(statement.strip())
    self._migrate_postgres()
    for statement in INDEXES.split(";"):
     if statement.strip(): self.conn.execute(statement.strip())
    self._seed_settings()
    self._schema_initialized.add(schema_key)
  else:
   # Vercel's filesystem is read-only. SQLite is only a local-development fallback.
   if os.getenv("VERCEL") and not self.database_url:
    raise RuntimeError("DATABASE_URL is required on Vercel; refusing to use local SQLite")
   self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(self.path); self.conn.row_factory=sqlite3.Row
   schema_key="sqlite:"+str(self.path.resolve())
   if schema_key not in self._schema_initialized:
    self.conn.executescript(SCHEMA.replace("BIGSERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT")); self.conn.executescript(ADMIN_SCHEMA); self.conn.executescript(ACTIVITY_SCHEMA.replace("BIGSERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT")); self.conn.executescript(NEWSLETTER_SCHEMA); self.conn.executescript(AUTH_SCHEMA.replace("BIGSERIAL PRIMARY KEY","INTEGER PRIMARY KEY AUTOINCREMENT")); self._migrate_sqlite(); self.conn.executescript(INDEXES); self.conn.commit()
    self._seed_settings()
    self._schema_initialized.add(schema_key)
 def _migrate_postgres(self):
  for sql in MIGRATIONS.values():
   try:self.conn.execute(sql)
   except Exception as exc:
    if "already exists" not in str(exc).lower():raise
 def _migrate_sqlite(self):
  cols={r[1] for r in self.conn.execute("PRAGMA table_info(news_items)").fetchall()}
  for name,sql in MIGRATIONS.items():
   if name not in cols:self.conn.execute(sql)
 def _seed_settings(self):
  now=NewsItem.now_iso()
  for key,value in DEFAULT_SETTINGS.items():
   if self._postgres:self.conn.execute("INSERT INTO admin_settings (key,value,updated_at) VALUES (%s,%s,%s) ON CONFLICT (key) DO NOTHING",(key,value,now))
   else:self.conn.execute("INSERT OR IGNORE INTO admin_settings (key,value,updated_at) VALUES (?,?,?)",(key,value,now))
  if not self._postgres:self.conn.commit()
 def get_settings(self):
  rows=self.conn.execute("SELECT key,value FROM admin_settings").fetchall(); result=dict(DEFAULT_SETTINGS); result.update({str(r["key"] if self._postgres else r[0]):str(r["value"] if self._postgres else r[1]) for r in rows}); return result
 def get_setting(self,key,default=None):return self.get_settings().get(key,default)
 def set_settings(self,values):
  now=NewsItem.now_iso()
  for key,value in values.items():
   if key not in DEFAULT_SETTINGS and not key.startswith("collector_last:"):continue
   value=str(value)
   if self._postgres:self.conn.execute("INSERT INTO admin_settings (key,value,updated_at) VALUES (%s,%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,updated_at=EXCLUDED.updated_at",(key,value,now))
   else:self.conn.execute("INSERT INTO admin_settings (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,now))
  if not self._postgres:self.conn.commit()
 def login_failures(self,attempt_key,since_iso):
  ph="%s" if self._postgres else "?"
  row=self.conn.execute(f"SELECT COUNT(*) AS count FROM admin_login_attempts WHERE attempt_key = {ph} AND attempted_at >= {ph}",(attempt_key,since_iso)).fetchone()
  return int(row["count"] if self._postgres else row[0])
 def record_login_failure(self,attempt_key,at_iso):
  ph="%s" if self._postgres else "?"
  self.conn.execute(f"INSERT INTO admin_login_attempts (attempt_key,attempted_at) VALUES ({ph},{ph})",(attempt_key,at_iso))
  cleanup_before=(datetime.fromisoformat(at_iso.replace("Z","+00:00"))-timedelta(hours=1)).isoformat().replace("+00:00","Z")
  self.conn.execute(f"DELETE FROM admin_login_attempts WHERE attempted_at < {ph}",(cleanup_before,))
  if not self._postgres:self.conn.commit()
 def clear_login_failures(self,attempt_key):
  ph="%s" if self._postgres else "?"
  self.conn.execute(f"DELETE FROM admin_login_attempts WHERE attempt_key = {ph}",(attempt_key,))
  if not self._postgres:self.conn.commit()
 def instagram_daily_count(self,start,end):
  ph="%s" if self._postgres else "?"; row=self.conn.execute(f"SELECT COUNT(*) AS count FROM news_items WHERE instagram_status='published' AND instagram_published_at >= {ph} AND instagram_published_at < {ph}",(start,end)).fetchone(); return int(row["count"] if self._postgres else row[0])
 def instagram_last_published_at(self):
  row=self.conn.execute("SELECT instagram_published_at FROM news_items WHERE instagram_status='published' AND instagram_published_at IS NOT NULL ORDER BY instagram_published_at DESC LIMIT 1").fetchone(); return (row["instagram_published_at"] if self._postgres else row[0]) if row else None
 def close(self):self.conn.close()
 def subscribe_newsletter(self,email,source="website",confirmed=True):
  email=str(email or "").strip().lower()
  now=NewsItem.now_iso()
  ph="%s" if self._postgres else "?"
  value=1 if confirmed else 0
  if self._postgres:self.conn.execute(f"INSERT INTO newsletter_subscribers (email,subscribed_at,source,confirmed) VALUES ({ph},{ph},{ph},{ph}) ON CONFLICT (email) DO UPDATE SET source=EXCLUDED.source,confirmed=EXCLUDED.confirmed",(email,now,source,value))
  else:self.conn.execute(f"INSERT INTO newsletter_subscribers (email,subscribed_at,source,confirmed) VALUES ({ph},{ph},{ph},{ph}) ON CONFLICT(email) DO UPDATE SET source=excluded.source,confirmed=excluded.confirmed",(email,now,source,value));self.conn.commit()
 def unsubscribe_newsletter(self,email):
  email=str(email or "").strip().lower()
  ph="%s" if self._postgres else "?"
  self.conn.execute(f"DELETE FROM newsletter_subscribers WHERE email = {ph}",(email,))
  if not self._postgres:self.conn.commit()
 def newsletter_count(self):
  row=self.conn.execute("SELECT COUNT(*) AS count FROM newsletter_subscribers").fetchone()
  return int(row["count"] if self._postgres else row[0])
 def increment_view(self,item_id:int,at_iso=None):
  at_iso=at_iso or NewsItem.now_iso()
  ph="%s" if self._postgres else "?"
  self.conn.execute(f"UPDATE news_items SET view_count=COALESCE(view_count,0)+1,last_viewed_at={ph} WHERE id = {ph} AND status='published'",(at_iso,item_id))
  if not self._postgres:self.conn.commit()
 def trending(self,limit=10):
  try:limit=max(1,min(int(limit),50))
  except (TypeError,ValueError):limit=10
  ph="%s" if self._postgres else "?"
  return self.conn.execute(f"SELECT * FROM news_items WHERE status='published' ORDER BY COALESCE(view_count,0) DESC, COALESCE(published_at_site,published_at) DESC LIMIT {ph}",(limit,)).fetchall()
 def insert(self,item:NewsItem)->bool:
  normalized_url=normalize_url(item.url); url_hash,title_hash=fingerprint(normalized_url,item.title); params=(item.source_name,item.source_type,item.title.strip(),item.url,normalized_url,item.published_at,item.summary,item.external_id,url_hash,title_hash,NewsItem.now_iso(),item.category or "general",item.image_url,1 if item.public_source else 0); sql="INSERT INTO news_items (source_name,source_type,title,url,normalized_url,published_at,summary,external_id,url_hash,title_hash,collected_at,category,image_url,public_source) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})"
  if self._postgres:return self.conn.execute(sql.format(p="%s")+" ON CONFLICT DO NOTHING",params).rowcount==1
  try:self.conn.execute(sql.format(p="?"),params); self.conn.commit(); return True
  except sqlite3.IntegrityError:return False
 def insert_many(self,items:Iterable[NewsItem]):
  added=skipped=0
  for item in items:
   if self.insert(item):added+=1
   else:skipped+=1
  return added,skipped
 def get_by_id(self,item_id:int,status=None):
  ph="%s" if self._postgres else "?"
  if status and status!="all":
   return self.conn.execute(f"SELECT * FROM news_items WHERE id = {ph} AND status = {ph} LIMIT 1",(int(item_id),status)).fetchone()
  return self.conn.execute(f"SELECT * FROM news_items WHERE id = {ph} LIMIT 1",(int(item_id),)).fetchone()

 def count(self):return int(self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()["count"] if self._postgres else self.conn.execute("SELECT COUNT(*) AS count FROM news_items").fetchone()[0])
 def count_status(self,status=None,review_status=None,instagram_status=None):
  clauses=[];params=[];ph="%s" if self._postgres else "?"
  if status and status!="all":clauses.append(f"status={ph}");params.append(status)
  if review_status and review_status!="all":clauses.append(f"fact_check_status={ph}");params.append(review_status)
  if instagram_status and instagram_status!="all":clauses.append(f"instagram_status={ph}");params.append(instagram_status)
  where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
  row=self.conn.execute(f"SELECT COUNT(*) AS count FROM news_items{where}",params).fetchone()
  return int(row["count"] if self._postgres else row[0])
 # Deliberately small listing projection: never transfer full articles, AI text,
 # authentication metadata or Instagram render fields for homepage card requests.
 PUBLIC_LIST_FIELDS = (
  "id", "title", "summary", "bot_summary", "source_name", "source_type",
  "url", "published_at", "published_at_site", "category", "status",
  "image_url", "image_source", "image_license", "public_source", "view_count",
 )
 def latest_public(self,limit=100,category=None,search=None):
  ph="%s" if self._postgres else "?"
  clauses=["status='published'"]; params=[]
  if category and category!="all":
   clauses.append(f"category={ph}"); params.append(category)
  if search:
   clauses.append(f"(LOWER(title) LIKE LOWER({ph}) OR LOWER(summary) LIKE LOWER({ph}))")
   params.extend([f"%{search}%",f"%{search}%"])
  max_rows=min(max(1,int(limit)),1000)
  fields=",".join(self.PUBLIC_LIST_FIELDS)
  return self.conn.execute(
   f"SELECT {fields} FROM news_items WHERE "+" AND ".join(clauses)+f" ORDER BY id DESC LIMIT {ph}",
   (*params,max_rows)
  ).fetchall()
 def latest(self,limit=20,category=None,status=None,search=None,review_status=None,instagram_status=None):
  clauses=[];params=[];ph="%s" if self._postgres else "?"
  for col,val in (("category",category),("status",status),("fact_check_status",review_status),("instagram_status",instagram_status)):
   if val and val!="all":clauses.append(f"{col} = {ph}");params.append(val)
  if search:clauses.append(f"(LOWER(title) LIKE LOWER({ph}) OR LOWER(summary) LIKE LOWER({ph}))");params.extend([f"%{search}%",f"%{search}%"])
  where=(" WHERE "+" AND ".join(clauses)) if clauses else ""; return self.conn.execute(f"SELECT * FROM news_items{where} ORDER BY id DESC LIMIT {ph}",(*params,limit)).fetchall()
 def update(self,item_id:int,**fields:Any):
  allowed={"title","summary","category","status","bot_summary","bot_article","ai_summary","ai_article","fact_check_status","fact_check_notes","image_url","approved_at","published_at_site","instagram_status","instagram_media_id","instagram_error","instagram_published_at","instagram_attempts","instagram_last_attempt_at","instagram_next_retry_at","instagram_scheduled_at","instagram_container_id","reel_cloudinary_public_id","reel_cloudinary_url","instagram_selected","instagram_queue_order","public_source","image_source","image_license","image_credit","image_source_url","image_search_query","image_selection_score","image_local_path","image_width","image_height","image_selected_at"}; fields={k:v for k,v in fields.items() if k in allowed}
  if not fields:return
  ph="%s" if self._postgres else "?";sets=[];params=[]
  for k,v in fields.items():sets.append(f"{k} = {ph}");params.append(v)
  params.append(item_id);self.conn.execute(f"UPDATE news_items SET {', '.join(sets)} WHERE id = {ph}",params)
  if not self._postgres:self.conn.commit()

 def log_activity(self,username,action,item_id=None,details=None):
  now=NewsItem.now_iso(); payload=str(details or "")[:4000];
  if self._postgres:self.conn.execute("INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES (%s,%s,%s,%s,%s)",(str(username),str(action),item_id,payload,now))
  else:self.conn.execute("INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES (?,?,?,?,?)",(str(username),str(action),item_id,payload,now)); self.conn.commit()
 def recent_activity(self,limit=50):
  try:limit=max(1,min(int(limit),200))
  except (TypeError,ValueError):
   limit=50
  ph="%s" if self._postgres else "?"
  return self.conn.execute(f"SELECT id,username,action,item_id,details,created_at FROM admin_activity ORDER BY id DESC LIMIT {ph}",(limit,)).fetchall()
 def next_instagram_queue_order(self):
  row=self.conn.execute("SELECT COALESCE(MAX(instagram_queue_order),0) AS value FROM news_items").fetchone(); return int(row["value"] if self._postgres else row[0])+1
