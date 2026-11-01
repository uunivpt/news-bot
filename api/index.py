# Production deployment marker: deterministic newsroom + public source attribution.
# Controlled production release: public quality, attribution and image-safety gates enabled.
from __future__ import annotations

import json, os, re, secrets, time, html, io, threading
from ipaddress import ip_address
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit
from flask import Flask, jsonify, request, session, send_from_directory, redirect, Response, render_template
from werkzeug.security import check_password_hash, generate_password_hash
from psycopg import Error as PostgresError
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase, DatabaseUnavailable, DatabaseBusy
from app.public_delivery import WindowLimiter, read_json_rows, remote_rows
from app.public_sessions import PublicSessionInterface
from app.briefing import DESKS as BRIEFING_DESKS, select_briefing, briefing_excerpt
from app.source_text import source_text as plain_source_text
from app.source_http import fetch_source, public_http_url
from app.admin_access import configured_users, verify_recovery_owner
from app.admin_workspace import LIST_FIELDS as ADMIN_LIST_FIELDS, EDITORIAL_FIELDS, editorial_revision, project_rows as admin_project_rows, coverage as admin_coverage
from app.category_routing import normalize_category
from app.seo_indexing import is_indexable, eligible_articles, news_sitemap_xml, google_news_sitemap_xml, standalone_sitemap_url_xml, STANDALONE_NEWS, SITE_ORIGIN as CANONICAL_ORIGIN
from app.models import NewsItem
from app import public_archive
from app.factcheck import run_cross_source_check
from app.newsroom import process_news, story_score, is_breaking, dedupe_story_rows, quality_headline, is_telegram_image
from app.phase_system import AGENTS, phase_analytics, cluster_stories, cluster_summary, train as train_agent
from app.reporting import operations_pdf
from app.advanced_ops import ensure_advanced_schema, live_dashboard, detailed_report, record_verification, audit_stage
from app.advanced_system import admin_snapshot, historical_analytics, event_timeline, ensure_schema as ensure_upgrade_schema
from app.newsletter import (
    OWNER as NEWSLETTER_OWNER, GENERIC_SIGNUP, mail_configured, valid_email,
    request_optin, confirmation_link, send_mail, confirm_optin, send_welcome,
    send_owner_alert, verified_story, lookup_unsubscribe, unsubscribe as unsubscribe_token,
    email_unsubscribe_link, ensure_tables as ensure_newsletter_tables, send_daily, iso,
)

app=Flask(__name__, static_folder="../public", static_url_path="", template_folder="../app/templates")
app.session_interface=PublicSessionInterface()
_secret=os.getenv("FLASK_SECRET_KEY") or os.getenv("ADMIN_TOKEN") or os.getenv("ADMIN_SETUP_KEY")
if not _secret:_secret=secrets.token_urlsafe(32)
app.secret_key=_secret
app.config["MAX_CONTENT_LENGTH"]=1*1024*1024
app.config.update(SESSION_COOKIE_NAME="__Host-politicshub_admin_session",SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE="Strict",SESSION_COOKIE_PATH="/",SESSION_COOKIE_REFRESH_EACH_REQUEST=False)
_LOGIN_WINDOW_SECONDS=300; _LOGIN_MAX_FAILURES=8; _SETUP_MAX_FAILURES=5; _login_failures={}

@app.before_request
def maybe_proxy_private_phone_admin():
 # Public reads still use the GitHub feed. Only the protected Admin API is
 # forwarded when the HTTPS tunnel and shared signing secret are configured.
 if os.getenv("VERCEL")!="1":
  return None
 from app.remote_admin_bridge import proxy_public_admin
 return proxy_public_admin()

_ADMIN_LOGIN_RATE=WindowLimiter(capacity=2048)


def recovery_session():
 return bool(session.get('admin_user') and session.get('admin_scope')=='recovery')


@app.before_request
def enforce_admin_session_scope():
 expiry=session.get('admin_expires_at')
 if expiry and time.time()>=expiry:session.clear()
 if request.method not in {'GET','HEAD','OPTIONS'} and (request.path.startswith('/api/admin/') or request.path.startswith('/api/news/')):
  origin=request.headers.get('Origin')
  expected_origins={request.host_url.rstrip('/')}
  # TLS terminates at Vercel before the Python runtime's internal HTTP hop.
  if os.getenv('VERCEL')=='1':
   # Vercel's internal request host can differ from the public browser origin.
   # Only the two canonical PoliticsHub HTTPS origins are trusted here.
   expected_origins.update({'https://politicshub.in','https://www.politicshub.in','https://'+request.host})
  # The Termux origin accepts this value ONLY after HMAC verification in
  # its private before_request guard. The phone still requires CSRF tokens.
  if os.getenv('POLITICSHUB_LOCAL_ADMIN')=='1' and os.getenv('POLITICSHUB_ADMIN_BRIDGE_SECRET'):
   expected_origins.add('http://127.0.0.1:8765')
  if origin and origin.rstrip('/') not in expected_origins:
   return jsonify({'error':'Cross-origin admin requests are not allowed'}),403
 if recovery_session() and request.path.startswith('/api/'):
  if request.method not in {'GET','HEAD','OPTIONS'} and request.path not in {'/api/admin/logout','/api/admin/login'}:
   return jsonify({'error':'Recovery access is read-only. Restore the database and sign in again to make changes.','code':'recovery_read_only'}),403


def _signed_in(username, role, scope='owner'):
 session.clear()
 session.update(admin_user=username,admin_role=role,admin_scope=scope,
  admin_expires_at=int(time.time())+(3600 if scope=='recovery' else 28800),
  csrf_token=secrets.token_urlsafe(32))
 return jsonify({'ok':True,'username':username,'role':role,'scope':scope,
  'read_only':scope=='recovery','csrf_token':session['csrf_token'],
  'expires_at':session['admin_expires_at']})


@app.before_request
def validate_json_object():
 if request.method in {"POST","PUT","PATCH","DELETE"} and request.is_json:
  body=request.get_json(silent=True)
  if not isinstance(body,dict):
   return jsonify({"error":"Request body must be a JSON object"}),400


@app.errorhandler(DatabaseUnavailable)
@app.errorhandler(PostgresError)
def database_request_unavailable(error):
 # Includes query cancellation and an unavailable admin database. Never return
 # driver messages, hostnames or SQL to a public browser.
 return jsonify({"error":"News database temporarily unavailable. Please retry shortly."}),503,{"Retry-After":"30"}


def _ensure_admin_users(database):
 database.conn.execute("CREATE TABLE IF NOT EXISTS admin_users (username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'owner',created_at TEXT NOT NULL)")
 configured=users()
 if configured:
  row=database.conn.execute('SELECT COUNT(*) AS count FROM admin_users').fetchone()
  if int(row['count'])==0:
   ph='%s' if database._postgres else '?'
   for username,password_hash in configured.items():
    if not re.fullmatch(r'[A-Za-z0-9._-]{3,40}',str(username)):continue
    if not isinstance(password_hash,str) or not password_hash.startswith(('scrypt:','pbkdf2:')) or password_hash.count('$')!=2 or not 60<=len(password_hash)<=1000:continue
    database.conn.execute(f'INSERT INTO admin_users (username,password_hash,role,created_at) VALUES ({ph},{ph},{ph},{ph}) ON CONFLICT(username) DO NOTHING',
     (username,password_hash,'owner',datetime.now(timezone.utc).isoformat()))
 if not database._postgres:database.conn.commit()

def _bootstrap_news_snapshot(database):
 try:
  if database.count() != 0:return 0
  path=Path(app.static_folder or "public") / "news-data.json"
  if not path.exists():return 0
  payload=json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(payload,list):return 0
  imported=0
  for item in payload[:500]:
   if not isinstance(item,dict) or not item.get("title") or not item.get("url"):continue
   news=NewsItem(
    source_name=str(item.get("source_name") or "PoliticsHub"),
    source_type=str(item.get("source_type") or "snapshot"),
    title=str(item.get("title")),
    url=str(item.get("url")),
    published_at=item.get("published_at"),
    summary=str(item.get("summary") or ""),
    external_id=None,
    category=str(item.get("category") or "general"),
    image_url=item.get("image_url"),
    public_source=bool(item.get("public_source")),
   )
   if not database.insert(news):continue
   ph="%s" if database._postgres else "?"
   row=database.conn.execute("SELECT id FROM news_items WHERE url = "+ph+" ORDER BY id DESC LIMIT 1",(news.url,)).fetchone()
   if not row:continue
   item_id=int(row["id"] if database._postgres else row[0])
   database.update(item_id,
    status="published",
    bot_summary=str(item.get("bot_summary") or item.get("summary") or ""),
    bot_article=str(item.get("bot_article") or ""),
    published_at_site=item.get("published_at_site") or item.get("published_at"),
    fact_check_status="pending",
   )
   imported+=1
  return imported
 except Exception as exc:
  print(f"News snapshot bootstrap skipped: {exc}")
  return 0


PUBLIC_BACKEND_ORIGIN=os.getenv("PUBLIC_BACKEND_ORIGIN","").rstrip("/")
_PUBLIC_API_TIMEOUT=8
_PUBLIC_RATE=WindowLimiter()

def _public_rate_key():
 # Vercel overwrites its own forwarding header. Outside that runtime, do not
 # trust arbitrary client-supplied proxy headers.
 if os.getenv("VERCEL")=="1":
  forwarded=request.headers.get("X-Vercel-Forwarded-For","").split(",",1)[0].strip()
  try:return str(ip_address(forwarded))
  except ValueError:pass
 return (request.remote_addr or "unknown")[:128]

def _public_rate_allowed(limit=120,window=60):
 key=(_public_rate_key(),request.endpoint,limit,window)
 return _PUBLIC_RATE.allow(key,limit,window)

def _proxy_public(path):
 if not PUBLIC_BACKEND_ORIGIN:return None
 try:
  import requests
  query=request.query_string.decode("utf-8")
  url=PUBLIC_BACKEND_ORIGIN+path+(("?" + query) if query else "")
  response=requests.get(url,timeout=_PUBLIC_API_TIMEOUT,headers={"Accept":"application/json","X-PoliticsHub-Proxy":"1"})
  return app.response_class(response.content,status=response.status_code,content_type=response.headers.get("Content-Type","application/json"))
 except Exception as exc:
  print(f"Public backend proxy failed: {exc}")
  return None

# Static assets live outside the Python function bundle on Vercel.
# During a database outage, read the latest production-branch snapshot without
# requiring a new Vercel deployment for every feed refresh.
_snapshot_remote_cache={"until":0.0,"payload":[]}
_snapshot_refresh_lock=threading.Lock()
PUBLIC_FEED_URL="https://raw.githubusercontent.com/uunivpt/news-bot/main/public/news-data.json"

# GitHub Actions publishes a link-only Hindi feed hourly, separately from Neon.
PUBLIC_HINDI_FEED_URL="https://raw.githubusercontent.com/uunivpt/news-bot/main/public/hindi-news.json"
_hindi_feed_cache={"until":0.0,"payload":[]}
_hindi_refresh_lock=threading.Lock()

def _hindi_rows():
 now=time.monotonic()
 if now < _hindi_feed_cache["until"]:
  return _validated_hindi_rows(_hindi_feed_cache['payload'])
 path=Path(app.static_folder or "public") / "hindi-news.json"
 local=read_json_rows(path)
 payload=_hindi_feed_cache["payload"] or local
 if os.getenv("VERCEL")=="1":
  payload=remote_rows(_hindi_feed_cache,_hindi_refresh_lock,local,
   (PUBLIC_HINDI_FEED_URL,),ttl=300,max_bytes=1_500_000,allow_empty=True)
 rows=_validated_hindi_rows(payload)
 if os.getenv("VERCEL")!="1":_hindi_feed_cache.update(until=now+300,payload=rows)
 return [dict(row) for row in rows]

def _validated_hindi_rows(payload):
 return [dict(row) for row in payload if isinstance(row,dict) and row.get('title') and
  str(row.get('category') or '').lower()=='hindi' and row.get('status','published')=='published' and _safe_source_url(row.get('url'))]


def _snapshot_rows(category="all", search=None):
 path=Path(app.static_folder or "public") / "news-data.json"
 payload=read_json_rows(path)
 if os.getenv("VERCEL")=="1":
  payload=remote_rows(_snapshot_remote_cache,_snapshot_refresh_lock,payload,
   (PUBLIC_FEED_URL,SITE_ORIGIN+"/news-data.json"),ttl=90,max_bytes=2_000_000)
 # Keep manually verified election reports independent of rotating news snapshots.
 # These time-stamped leads are NOT certified final election results.
 if not isinstance(payload,list):payload=[]
 curated_path=Path(app.static_folder or "public") / "maharashtra-mlc-2026-verified.json"
 try:
  curated=read_json_rows(curated_path)
  if isinstance(curated,list):
   present={str(x.get("id")) for x in payload if isinstance(x,dict)}
   payload=[x for x in curated if isinstance(x,dict) and x.get("title") and str(x.get("id")) not in present] + payload
 except (OSError,ValueError):
  pass
 rows=[dict(x) for x in payload if isinstance(x,dict) and x.get("title") and x.get("status","published")=="published"]
 for row in rows:
  row.setdefault("status","published")
  row["category"]=normalize_category(row.get("category"), row.get("title"), row.get("bot_summary") or row.get("summary") or "")
 if category and category!="all":rows=[x for x in rows if str(x.get("category") or "general").lower()==category]
 if search:
  q=str(search).strip().lower()
  rows=[x for x in rows if q in str(x.get("title") or "").lower() or q in str(x.get("summary") or x.get("bot_summary") or "").lower() or q in str(x.get("source_name") or x.get("source") or "").lower()]
 return rows

def _public_timestamp(row):
 for key in ("published_at_site","published_at_iso","published_at","created_at","collected_at"):
  raw=str(row.get(key) or "").strip()
  if not raw:continue
  normalized=re.sub(r"\s*[·•]\s*"," ",raw).strip()
  try:
   dt=datetime.fromisoformat(normalized.replace("Z","+00:00"))
   if not dt.tzinfo:dt=dt.replace(tzinfo=timezone.utc)
   return dt.timestamp()
  except ValueError:
   pass
  try:
   dt=parsedate_to_datetime(normalized)
   if dt.tzinfo is not None:return dt.timestamp()
  except (ValueError,TypeError,OverflowError):
   pass
  for fmt in ("%d %b %Y %H:%M","%d %b %Y"):
   try:
    return datetime.strptime(normalized,fmt).replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
   except ValueError:
    pass
 return 0.0


def _rank_public(rows,threshold=0.82):
 items=[dict(r) for r in rows]
 for item in items:
  item["category"]=normalize_category(item.get("category"),item.get("title"),item.get("bot_summary") or item.get("summary") or "")
  item["news_score"]=story_score(item.get("title",""),item.get("bot_summary") or item.get("summary") or "",item.get("category") or "general",item.get("source_name") or "")
  item["is_breaking"]=is_breaking(item.get("title",""),item.get("bot_summary") or item.get("summary") or "",item["news_score"])
 items.sort(key=lambda item:(_public_timestamp(item),int(item.get("id") or 0)),reverse=True)
 return dedupe_story_rows(items,threshold=threshold)
def _public_rows_for_section(category="all",limit=200):
 if category=="hindi":return _rank_public(_hindi_rows())[:limit]
 try:
  database=db()
  try:
   rows=[dict(x) for x in database.latest_public(max(limit*3,limit),"all" if category in ("india","entertainment") else category)]
   rows=_rank_public(rows)
   return [x for x in rows if category=="all" or x.get("category")==category][:limit]
  finally:database.close()
 except RuntimeError:
  return _rank_public(_snapshot_rows(category))[:limit]

def _section_html(category="all"):
 rows=_public_rows_for_section(category,40)
 label="Latest news" if category=="all" else str(category).title()+" news"
 canonical=SITE_ORIGIN+"/" if category=="all" else SITE_ORIGIN+"/"+category+"/"
 cards=[]
 for row in rows:
  try:
   row=_publicize(row)
   title=html.escape(str(row.get("title") or "Untitled"))
   href=article_path(row)
   date=html.escape(str(row.get("published_at_site") or row.get("published_at") or ""))
   summary=html.escape(str(row.get("bot_summary") or row.get("summary") or "")[:320])
   source=html.escape(str(row.get("source_name") or "PoliticsHub"))
   image=str(row.get("image_url") or "").strip()
   media=""
   if image.startswith(("http://","https://","/")):
    media='<img src="'+html.escape(image,quote=True)+'" alt="" loading="lazy" decoding="async">'
   card_class="card im" if media else "card tx"
   cards.append('<a class="'+card_class+' rv" href="'+html.escape(href,quote=True)+'">'+media+'<span class="chip stk">'+html.escape(str(row.get("category") or category or "News"))+'</span><span class="go" aria-hidden="true">↗</span><h3>'+title+'</h3><p>'+summary+'</p><span class="m">'+source+" · "+date+"</span></a>")
  except Exception:
   pass
 first=rows[0] if rows else {}
 first_title=html.escape(str(first.get("title") or "Latest news"))
 first_summary=html.escape(str(first.get("bot_summary") or first.get("summary") or "")[:420])
 first_category=html.escape(str(first.get("category") or category or "News"))
 first_source=html.escape(str(first.get("source_name") or "PoliticsHub"))
 first_href=html.escape(article_path(first),quote=True) if first.get("id") else "#"
 first_image=str(first.get("image_url") or "").strip()
 first_media=""
 if first_image.startswith(("http://","https://","/")):
  first_media='<img src="'+html.escape(first_image,quote=True)+'" alt="" loading="eager" decoding="async">'
 jump=[]
 for cat in ("maharashtra","india","politics","world","hindi"):
  jump.append('<a href="/'+cat+'/">'+cat.title()+'<small>'+str(sum(1 for r in rows if str(r.get("category") or "").lower()==cat))+'</small></a>')
 just_in=[]
 for row in rows[1:4]:
  try:
   just_in.append('<a class="li" href="'+html.escape(article_path(row),quote=True)+'"><span>'+html.escape(str(row.get("title") or "Untitled"))+'</span><small>'+html.escape(str(row.get("published_at_site") or row.get("published_at") or ""))+'</small></a>')
  except Exception:
   pass
 body='<section class="bento">'
 body+='<div class="tile hl"><span class="burst" aria-hidden="true">✺</span><span class="lbl"><i class="dot"></i>What matters, clearly.</span><h1>'+first_title+'</h1><p>'+first_summary+'</p><a class="btn" href="'+first_href+'">Read latest story <span aria-hidden="true">↗</span></a></div>'
 if first_media:
  body+='<a class="tile cv im" href="'+first_href+'" aria-label="'+first_title+'">'+first_media+'<span class="chip stk">'+first_category+'</span><span class="cap">'+first_source+'</span></a>'
 body+='<div class="tile ct"><span class="lbl">Today on PoliticsHub.in</span><b class="num" data-n="'+str(len(rows))+'">'+str(len(rows))+'</b><span>stories in '+html.escape(label)+'</span></div>'
 body+='<div class="tile sc"><span class="lbl">Jump to a desk</span><div class="pills">'+"".join(jump)+'</div></div>'
 body+='<div class="tile lt"><span class="lbl">Just in</span>'+"".join(just_in)+'</div></section>'
 if category in ("india","all"):
  body+='<section aria-label="Verified report" style="margin:20px 0"><h2>Verified India report</h2><p><a href="/nana-patekar-tribute.html">Nana Patekar dies at 75 in Goa: report and sources</a></p></section>'
 body+='<div class="sh"><h2>Latest stories</h2><span class="lbl">'+str(len(rows))+' stories</span></div><div class="grid">'+"".join(cards)+'</div>'
 return '<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8"><meta name="color-scheme" content="dark light"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(label)+' — PoliticsHub.in</title><meta name="description" content="'+html.escape(label)+' from PoliticsHub.in."><link rel="canonical" href="'+canonical+'"><meta name="google-adsense-account" content="ca-pub-1752666987448533"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533" crossorigin="anonymous"></script><meta property="og:type" content="website"><meta property="og:title" content="'+html.escape(label)+' — PoliticsHub.in"><meta property="og:image" content="'+SITE_ORIGIN+'/api/og-home?v=20261022"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="'+html.escape(label)+' — PoliticsHub.in"><meta name="twitter:image" content="'+SITE_ORIGIN+'/api/og-home?v=20261022"><link rel="icon" href="/favicon.svg"><link rel="manifest" href="/manifest.webmanifest"><link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="stylesheet" href="/assets/editorial.css?v=phui19"><link rel="stylesheet" href="/assets/polish.css?v=phui30"><script src="/assets/ui.js?v=phui30" defer></script></head><body><div id="prog"></div><header id="hd"><div class="top"><button class="ib burger" id="bg" aria-label="Open menu">☰</button><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a><nav class="main" id="nav" aria-label="Sections"><span id="ind" aria-hidden="true"></span></nav><div class="acts"><button class="ib" id="sbtn" aria-label="Search">⌕</button><a class="ib" href="/about.html" aria-label="About">i</a></div></div><div class="tick" id="tick" hidden><span class="tag">LIVE <i class="dot"></i></span><div class="tk" id="tk"></div><button class="ib" id="pz" aria-label="Pause ticker" aria-pressed="false">Ⅱ</button></div></header><div id="bd"></div><aside id="dr" aria-hidden="true"><button class="ib" id="dx" aria-label="Close menu">×</button><nav id="dl"></nav><div class="ft">PoliticsHub.in<br><span>What matters, clearly.</span></div></aside><div id="cv"></div><section id="sp" aria-hidden="true"><div class="sb"><form id="sf"><input id="si" type="search" autocomplete="off" placeholder="Search the full archive" aria-label="Search the full archive"><button class="ib" id="sx" type="button" aria-label="Close search">×</button></form><p id="sc" class="lbl" style="margin:18px 6px"></p><div id="sres"></div></div></section><main class="wrap"><div id="app">'+body+'</div></main><footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><div class="ser">What matters,<br>clearly.</div></div><div><h4>EXPLORE</h4><p><a href="/">Home</a></p><p><a href="/about.html">About</a></p><p><a href="/archive/">All News Archive</a></p><p><a href="/nana-patekar-tribute.html">Nana Patekar report</a></p><p><a href="/search.html">Search</a></p></div><div><h4>INFORMATION</h4><p><a href="/privacy.html">Privacy</a></p><p><a href="/cookies.html">Cookies</a></p><p><a href="/terms.html">Terms</a></p><p><a href="/settings.html">Settings</a></p><p><a href="/contact.html">Contact</a></p><p><small>© <span id="yr"></span> PoliticsHub.in</small></p></div></div></footer><script src="/assets/site.js?v=phui30"></script><script src="/assets/editorial-home.js?v=phui30"></script></body></html>'


def _enhance_section_seo(document, category):
 """Provide structured data and useful metadata on server-rendered news pages."""
 if category == "all":
  document = document.replace("<title>Latest news — PoliticsHub.in</title>", "<title>India &amp; World News | PoliticsHub.in</title>", 1)
 section = category if category != "all" else "India and world"
 description = (
  "Explore the latest India and world news, politics, business and technology "
  "on PoliticsHub.in. Read source-linked reports and editorial updates."
  if category == "all" else
  f"Read the latest {section.title()} news and public affairs coverage on PoliticsHub.in, "
  "with source-linked reports, publication details and editorial transparency."
 )
 document = re.sub(
  r'<meta name="description" content="[^"]*">',
  '<meta name="description" content="' + html.escape(description, quote=True) + '">',
  document, count=1,
 )
 canonical = SITE_ORIGIN + ("/" if category == "all" else "/" + category + "/")
 publisher = {"@type": "Organization", "@id": SITE_ORIGIN + "/#publisher",
              "name": "PoliticsHub.in", "url": SITE_ORIGIN + "/",
              "logo": {"@type": "ImageObject", "url": SITE_ORIGIN + "/favicon.svg"}}
 website = {"@type": "WebSite", "name": "PoliticsHub.in",
            "url": SITE_ORIGIN + "/", "publisher": {"@id": publisher["@id"]}}
 page = {"@type": "CollectionPage", "name": ("Latest news" if category == "all" else section.title() + " news"),
         "url": canonical, "description": description, "isPartOf": {"@type": "WebSite", "url": SITE_ORIGIN + "/"}}
 schema = json.dumps({"@context": "https://schema.org", "@graph": [publisher, website, page]}, ensure_ascii=False).replace("<", "\\u003c")
 injection = ('<meta property="og:description" content="' + html.escape(description, quote=True) + '">'
              '<meta name="twitter:description" content="' + html.escape(description, quote=True) + '">'
              '<script type="application/ld+json">' + schema + '</script>')
 return document.replace("</head>", injection + "</head>", 1)

_db_retry_after=0.0

def db():
 global _db_retry_after
 # Vercel's news website consumes GitHub-published feed data. The only
 # editable PostgreSQL database is on Termux; never connect to Neon here,
 # even if legacy DATABASE_3URL environment secrets still exist.
 if os.getenv("VERCEL") == "1" or os.getenv("POLITICSHUB_GITHUB_FEED_ONLY") == "1":
  raise DatabaseUnavailable("Public website is GitHub-feed-only; editable data is local to Termux")
 if time.monotonic() < _db_retry_after:
  raise DatabaseUnavailable("Database temporarily unavailable")
 try:
  # Public HTTP requests fail over quickly; background collectors keep their
  # longer retry budget. Queries also have a server-side execution deadline.
  database=NewsDatabase(connect_attempts=1,connect_timeout=3,statement_timeout=5000,
   use_pool=True,initialize_schema=os.getenv("VERCEL")!="1")
 except DatabaseBusy:
  raise
 except DatabaseUnavailable:
  _db_retry_after=time.monotonic()+30
  raise
 # Public reads must never seed old snapshots into a production database.
 if request.path.startswith("/api/admin/"):
  try:_ensure_admin_users(database)
  except Exception:
   database.close()
   raise
 return database

def admin_ok():
 if recovery_session():return False
 if session.get("admin_user"):return True
 token=os.getenv("ADMIN_TOKEN",""); supplied=request.headers.get("X-Admin-Token",""); return bool(token and supplied and secrets.compare_digest(supplied,token))

def require_admin():
 if recovery_session():
  if request.path=='/api/admin/workspace':return None
  return jsonify({'error':'This section needs a live database owner session. Recovery access is read-only.','code':'recovery_read_only'}),403
 return None if admin_ok() else (jsonify({"error":"admin authentication required"}),401)
def require_csrf():
 if not session.get("admin_user"):return None
 token=request.headers.get("X-CSRF-Token",""); expected=session.get("csrf_token",""); return None if token and expected and secrets.compare_digest(token,expected) else (jsonify({"error":"invalid CSRF token"}),403)

def _strip_promo_nav(value):
 r=str(value or "")
 r=re.sub(r"\b(?:socials|donate|advertising)\b(?:\s*[|•·/,-]\s*\b(?:socials|donate|advertising)\b)*"," ",r,flags=re.I)
 return re.sub(r"\s{2,}"," ",r).strip(" |•·/-")

def _public_title(title,source_text=""):
 raw=re.sub(r"\s+"," ",str(title or "")).strip()
 raw=re.sub(r"^[^\w]+","",raw).strip()
 raw=re.sub(r"\s*[,;:]\s*[A-Za-z]{1,2}$","",raw).strip(" .,:;-")
 words=raw.split()
 # Repair the characteristic ingestion truncation where the first 1–3
 # lowercase letters of a headline survive but the rest of the first word is lost.
 first=words[0] if words else ""
 damaged=bool(first and len(first)<=3 and first.islower() and len(words)>=4)
 if damaged or len(words)>18 or "..." in raw or "…" in raw:
  candidate=quality_headline(raw,source_text)
  if candidate and not (len(candidate.split())<=3 and candidate==raw):
   raw=candidate
 if len(raw.split())>18:
  raw=" ".join(raw.split()[:18]).rstrip(" .,:;-")
 return raw or quality_headline(title,source_text)

def _publicize(row):
 r={k:v for k,v in dict(row).items() if not k.startswith(("instagram_","reel_cloudinary_"))}
 if not admin_ok():
  # Public readers may see the originating source and its public article URL.
  # Internal moderation, hashes and processing fields stay private.
  for key in ("normalized_url","external_id","url_hash","title_hash","collected_at","fact_check_status","fact_check_notes","approved_at","ai_summary","ai_article","published_at_site"):
   r.pop(key,None)
  raw=dict(row).get("published_at_site") or dict(row).get("published_at")
  if raw:
   try:
    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    r["published_at"]=dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M")
    r["published_at_iso"]=dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
   except ValueError:pass
  source_text=_strip_promo_nav(dict(row).get("bot_article") or dict(row).get("bot_summary") or dict(row).get("summary") or "")
  r["title"]=_public_title(r.get("title"),source_text)
  r["summary"]=plain_source_text(_strip_promo_nav(dict(row).get("bot_summary") or dict(row).get("summary") or ""))
  article_text=plain_source_text(_strip_promo_nav(source_text),paragraphs=True)
  article_text=re.sub(r"(?:\n|\s)*Why it matters:\s*$","",article_text,flags=re.I).strip()
  r["article"]=article_text
  r["url"]=_safe_source_url(r.get("url"))
  # Website images are source-only. Separately generated images
  # (Wikimedia/Openverse/etc.) must never appear on the website.
  r["image_url"]=_public_image_path(r)
  r.pop("editorial_context",None)
  if "editorial_value" in r: r["editorial_value"]=bool(r.get("editorial_value"))
  if "source_count" in r: r["source_count"]=int(r.get("source_count") or 0)
 r["category"]=normalize_category(r.get("category"), r.get("title"), r.get("summary") or r.get("bot_summary") or "")
 score=story_score(r.get("title",""),r.get("summary",""),r.get("category") or "general",r.get("source_name") or "")
 r["news_score"]=score; r["is_breaking"]=is_breaking(r.get("title",""),r.get("summary",""),score)
 return r


def _safe_source_url(value):
 try:
  parts=urlsplit(str(value or "").strip())
  return str(value).strip() if parts.scheme in {"http","https"} and parts.hostname and not parts.username and not parts.password else ""
 except ValueError:return ""


def _is_source_supplied_image(row):
 if not isinstance(row,dict):return False
 url=str(row.get("image_url") or "").strip()
 if not url.startswith(("http://","https://")):return False
 source=str(row.get("image_source") or "").strip().lower()
 license_key=str(row.get("image_license") or "").strip().lower().split(" ",1)[0]
 # Never publish a feed/publisher image merely because it arrived with a story.
 # The public website is source-image-only AND requires an explicit low-risk
 # public-domain/CC0-style licence. Unknown-source images remain hidden.
 return source=="article-source" and license_key in {"cc0","pdm"}


def _public_image_path(row):
 if isinstance(row,dict) and row.get("source_type")=="x" and row.get("status")=="published":
  try:return "/api/x-card/"+str(int(row.get("id")))
  except (TypeError,ValueError):return ""
 if not _is_source_supplied_image(row):return ""
 item_id=row.get("id") if isinstance(row,dict) else None
 try:return "/api/image/"+str(int(item_id))
 except (TypeError,ValueError):return ""


def _safe_public_image_origin(url):
 return public_http_url(url)


@app.get("/api/x-card/<int:item_id>")
def x_post_quote_card(item_id):
 database=db()
 try:
  row=database.get_by_id(item_id,"published")
  if not row or row["source_type"]!="x":return Response(status=404)
  from app.x_quote_poster import render_x_quote_card
  image=render_x_quote_card(dict(row))
  return Response(image,mimetype="image/jpeg",headers={"Cache-Control":"public, max-age=3600"})
 finally:database.close()


@app.get("/api/image/<int:item_id>")
def public_story_image(item_id):
 database=db()
 try:
  row=database.get_by_id(int(item_id),"published")
  row=dict(row) if row else None
 finally:
  database.close()
 if not row or not _is_source_supplied_image(row):
  return Response(status=404)
 source_url=str(row.get("image_url") or "").strip()
 if not _safe_public_image_origin(source_url):
  return Response(status=404)
 try:
  from urllib.parse import urlsplit
  parts=urlsplit(source_url)
  headers={
   "User-Agent":"Mozilla/5.0 (compatible; PoliticsHubImageProxy/1.0; +https://politicshub.in)",
   "Accept":"image/avif,image/webp,image/png,image/jpeg,image/gif",
   "Referer":parts.scheme+"://"+parts.netloc+"/",
  }
  upstream=fetch_source(source_url,headers=headers,timeout=12,max_bytes=8*1024*1024)
  content_type=upstream.content_type.split(";",1)[0].strip()
  if content_type not in {"image/avif","image/webp","image/png","image/jpeg","image/gif"}:
   raise ValueError("Source image must use a supported raster format")
  response=Response(upstream.content,mimetype=content_type)
  response.headers["Cache-Control"]="public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800"
  response.headers["X-Content-Type-Options"]="nosniff"
  return response
 except Exception as exc:
  print(f"Public source image unavailable for item {item_id}: {type(exc).__name__}")
  return Response(status=404)


SITE_ORIGIN=CANONICAL_ORIGIN
EDITORIAL_DESK="PoliticsHub Editorial Desk"
EDITORIAL_EMAIL="politicshub.in@gmail.com"
CATEGORY_SLUGS={"general":"india","india":"india","world":"world","politics":"politics","business":"business","technology":"technology","sports":"sports","entertainment":"entertainment","science":"science","health":"health","hindi":"hindi"}

def _slugify(value):
 from app.seo_indexing import slugify
 return slugify(value)

def article_path(row):
 category=normalize_category(row.get("category"),row.get("title"),row.get("bot_summary") or row.get("summary") or "")
 category=CATEGORY_SLUGS.get(category,"india")
 return f"/{category}/{int(row['id'])}-{_slugify(row.get('title'))}"

_archive_discovery_cache=(None,())
_archive_discovery_until=0.0

def _archive_rows(database=None, search=None,discovery=False):
 global _archive_discovery_cache,_archive_discovery_until
 if discovery:
  records=public_archive._load()
  if _archive_discovery_cache[0] is not records or time.monotonic()>=_archive_discovery_until:
   normalized=[_discovery_row(row) for row in records]
   eligible=eligible_articles(normalized)
   for row in eligible:row['_discovery_ready']=True
   _archive_discovery_cache=(records,tuple(eligible))
   _archive_discovery_until=time.monotonic()+300
  rows=[dict(row) for row in _archive_discovery_cache[1]]
 else:rows=public_archive.rows(search)
 if database is not None:
  overrides=[dict(row) for row in database.archive_overrides(rows)]
  ids={str(row["id"]) for row in overrides}
  urls={row["url"] for row in overrides}
  rows=[row for row in rows if str(row["id"]) not in ids and row["url"] not in urls]
 return rows

def _archive_row(item_id,database=None):
 row=public_archive.by_id(item_id)
 if row is None:return None
 if database is not None:
  # Honor current publication status, including a changed ID after migration.
  overrides=[dict(record) for record in database.archive_overrides([row])]
  for record in overrides:
   if str(record["id"])==str(item_id) or record["url"]==row["url"]:
    return database.get_by_id(record["id"],"published") if record["status"]=="published" else None
 return row

def _public_row_by_id(item_id):
 # Stable, content-addressed IDs for the Hindi RSS desk live outside Neon.
 for item in _hindi_rows():
  if str(item.get("id"))==str(item_id):return _publicize(item)
 try:
  database=db()
  try:
   row=database.get_by_id(int(item_id),"all")
   if row:return _publicize(row) if row["status"]=="published" else None
   row=_archive_row(item_id,database)
   return _publicize(row) if row else None
  finally: database.close()
 except RuntimeError:
  pass
 for item in _snapshot_rows("all"):
  if str(item.get("id"))==str(item_id):return _publicize(item)
 archived=_archive_row(item_id)
 if archived:return _publicize(archived)
 proxied=_proxy_public("/api/news/"+str(int(item_id)))
 return proxied.get_json(silent=True) if proxied is not None and proxied.status_code<400 else None

def _article_html(row):
 row=dict(row)
 indexable=is_indexable(row)
 robots_meta = "" if indexable else '<meta name="robots" content="noindex,follow">'
 # Don't serve advertising scripts on pages containing only RSS headline excerpts.
 article_ad_code = ('<meta name="google-adsense-account" content="ca-pub-1752666987448533"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533" crossorigin="anonymous"></script>' if indexable else '')
 title=str(row.get("title") or "PoliticsHub.in"); category=str(row.get("category") or "India")
 canonical=SITE_ORIGIN+article_path(row)
 published=row.get("published_at_iso") or row.get("published_at_site") or row.get("published_at")
 modified=row.get("published_at_iso") or row.get("published_at_site") or row.get("published_at")
 summary=plain_source_text(row.get("summary") or row.get("bot_summary"))
 body=plain_source_text(row.get("article") or row.get("bot_article") or row.get("body") or summary,paragraphs=True)
 source=str(row.get("source_name") or "PoliticsHub.in")
 source_url=_safe_source_url(row.get("url"))
 image=SITE_ORIGIN+"/api/og/"+str(row.get("id"))+"?v=20261031-deva"
 pub_iso=str(published or datetime.now(timezone.utc).isoformat())
 if pub_iso and not re.search(r"[+-]\d\d:\d\d|Z$",pub_iso): pub_iso=pub_iso+"Z"
 data={
  "@context":"https://schema.org","@type":"NewsArticle","headline":title,
  "description":summary,"image":[image],"datePublished":pub_iso,"dateModified":str(modified or pub_iso),
  "author":[{"@type":"Organization","name":EDITORIAL_DESK,"url":SITE_ORIGIN+"/author/politicshub-news-desk"}],
  "publisher":{"@type":"Organization","name":"PoliticsHub.in","url":SITE_ORIGIN,"logo":{"@type":"ImageObject","url":SITE_ORIGIN+"/favicon.svg"}},
  "mainEntityOfPage":{"@type":"WebPage","@id":canonical},"isAccessibleForFree":True
 }
 json_ld=json.dumps(data,ensure_ascii=False).replace("<", "\\u003c")
 paras="".join(f"<p>{html.escape(p.strip())}</p>" for p in re.split(r"\n+",body) if p.strip())
 return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — PoliticsHub.in</title>
{robots_meta}
<meta name="description" content="{html.escape(summary[:160])}">
<meta name="robots" content="max-image-preview:large">
<link rel="canonical" href="{html.escape(canonical)}">
{article_ad_code}<meta property="og:type" content="article"><meta property="og:site_name" content="PoliticsHub.in">
<meta property="og:title" content="{html.escape(title)}"><meta property="og:description" content="{html.escape(summary[:200])}">
<meta property="og:url" content="{html.escape(canonical)}"><meta property="og:image" content="{html.escape(image)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{html.escape(title)}"><meta name="twitter:description" content="{html.escape(summary[:200])}"><meta name="twitter:image" content="{html.escape(image)}">
<meta property="article:section" content="{html.escape(category)}"><meta property="article:published_time" content="{html.escape(pub_iso)}">
<link rel="icon" href="/favicon.svg"><link rel="manifest" href="/manifest.webmanifest"><link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="stylesheet" href="/assets/share.css?v=phshare2">
<script type="application/ld+json">{json_ld}</script>
<link rel="stylesheet" href="/assets/polish.css?v=phui30"><script src="/assets/ui.js?v=phui30" defer></script><script src="/assets/share.js?v=phshare2" defer></script></head><body>
<header id="hd"><div class="top"><button class="ib burger" id="bg" aria-label="Open menu">☰</button><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a><div class="acts"><a class="ib" href="/" aria-label="Home">⌂</a><a class="ib" href="/about.html" aria-label="About">i</a></div></div></header>
<main class="wrap"><article class="art" data-k="{html.escape(category.lower())}">
<div class="ah"><span class="chip">{html.escape(category)}</span><h1>{html.escape(title)}</h1><p class="dek">{html.escape(summary)}</p>
<div class="by"><span>By <a href="/author/politicshub-news-desk">{EDITORIAL_DESK}</a></span><time datetime="{html.escape(pub_iso,quote=True)}">{html.escape(str(published or ""))}</time><span>{html.escape(source)}</span></div></div>
{"<div class='ahero'><img src='"+html.escape(str(_public_image_path(row)),quote=True)+"' alt='"+html.escape(title,quote=True)+"' loading='eager'></div>" if _public_image_path(row) else ""}
<div class="body">{paras}</div>
{"<div class='src'><strong>Publisher excerpt:</strong> This page is a source-linked summary, not an independently reported PoliticsHub article. The original source link below contains the complete report.</div>" if not indexable else ""}
<div class="src"><strong>Source transparency:</strong> This is a source-linked brief prepared from the originating report. When multiple independent sources are available, PoliticsHub compares their reported details; otherwise no independent reporting claim is made.</div>
<div class="src">Source: {html.escape(source)}. {"<a href='"+html.escape(source_url,quote=True)+"' rel='nofollow noopener noreferrer' target='_blank'>Read the original report</a>" if source_url else ""}</div>
<button type="button" class="article-share" data-share-title="{html.escape(title,quote=True)}" data-share-url="{html.escape(canonical,quote=True)}" aria-haspopup="dialog"><span>↗</span><b>Share this story</b></button>
</article></main>
<footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><p class="ser">Source-linked news. Clearly.</p></div><div><h4>Navigate</h4><ul><li><a href="/">Home</a></li><li><a href="/archive/">News Archive</a></li><li><a href="/about.html">About</a></li><li><a href="/editorial-policy.html">Editorial Policy</a></li><li><a href="/corrections.html">Corrections</a></li><li><a href="/contact.html">Contact</a></li><li><a href="/disclaimer.html">Disclaimer</a></li><li><a href="/privacy.html">Privacy</a></li><li><a href="/cookies.html">Cookies</a></li><li><a href="/terms.html">Terms</a></li><li><a href="/newsletter.html">Newsletter</a></li><li><a href="/settings.html">Settings</a></li><li><a href="/debug.html">System Status</a></li></ul></div><div><h4>Contact</h4><ul><li><a href="mailto:politicshub.in@gmail.com">politicshub.in@gmail.com</a></li></ul></div></div></footer>
<script src="/assets/story-page.js?v=phview1"></script>
</body></html>"""

def _og_image(item_id):
  row = _public_row_by_id(item_id)
  if not row:
    return None
  from app.social_preview import render_story
  return render_story(row.get("title") or "Latest PoliticsHub report", row.get("category") or "News")

def _editorial_page(title,lead,kind="page"):
 links=["Home","About","Editorial Policy","Corrections","Contact","Disclaimer","Privacy","Cookies","Terms","Newsletter","Settings","System Status"]
 hrefs={"Home":"/","About":"/about.html","Editorial Policy":"/editorial-policy.html","Corrections":"/corrections.html","Contact":"/contact.html","Disclaimer":"/disclaimer.html","Privacy":"/privacy.html","Cookies":"/cookies.html","Terms":"/terms.html","Newsletter":"/newsletter.html","Settings":"/settings.html","System Status":"/debug.html"}
 nav="<ul>"+"".join("<li><a href=\""+hrefs[x]+"\">"+html.escape(x)+"</a></li>" for x in links)+"</ul>"
 body="<p>PoliticsHub.in is a source-linked digital newsroom focused on politics, public affairs, India and the world.</p>" if kind=="author" else ""
 page='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+' — PoliticsHub.in</title><meta name="description" content="'+html.escape(lead[:160])+'"><link rel="canonical" href="'+SITE_ORIGIN+request.path+'"><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="stylesheet" href="/assets/polish.css?v=phui30"><script src="/assets/ui.js?v=phui30" defer></script></head><body><header id="hd"><div class="top"><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a></div></header><main class="wrap"><article class="art"><div class="ah"><span class="lbl red">PoliticsHub.in</span><h1>'+html.escape(title)+'</h1><p class="dek">'+html.escape(lead)+'</p></div><div class="body">'+body+'</div></article></main><footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><p class="ser">What matters, clearly.</p></div><div><h4>Navigate</h4>'+nav+'</div></div></footer></body></html>'
 return Response(page,mimetype="text/html")
def rows_json(rows,compact=False):
 out=[]
 for row in rows:
  if not (admin_ok() or row.get("status")=="published"):continue
  item=_publicize(row)
  if compact and admin_ok():
   item={k:item.get(k) for k in ("id","title","source_name","category","status","fact_check_status","bot_summary","news_score","is_breaking","view_count")}
  out.append(item)
 return out
def users():
 return configured_users()
def _client_key():return _public_rate_key()
def _auth_key(username):return "login:user:"+str(username).strip().lower()[:128]
def _ip_key():return "login:ip:"+_client_key()
def _setup_key():return "setup:global"
def _auth_allowed(database,attempt_key,maximum):
 now=datetime.now(timezone.utc); since=(now-timedelta(seconds=_LOGIN_WINDOW_SECONDS)).isoformat(); return database.login_failures(attempt_key,since)<maximum
def _auth_failed(database,attempt_key):database.record_login_failure(attempt_key,datetime.now(timezone.utc).isoformat())
def _auth_clear(database,attempt_key):database.clear_login_failures(attempt_key)
def _india_day_bounds():
 tz=ZoneInfo("Asia/Kolkata"); today=datetime.now(tz).date(); start=datetime.combine(today,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc); return start.isoformat(),(start+timedelta(days=1)).isoformat()

def log_admin(database,action,item_id=None,details=None):
 try:database.log_activity(session.get("admin_user") or "token",action,item_id,details)
 except Exception:pass

@app.get("/admin/", strict_slashes=False)
def admin_page():
 return send_from_directory(app.static_folder,"admin/index.html")

@app.after_request
def security_headers(response):
 response.headers["X-Content-Type-Options"]="nosniff"
 response.headers["X-Frame-Options"]="DENY"
 response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
 response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=(), payment=(), usb=()"
 response.headers["Strict-Transport-Security"]="max-age=63072000; includeSubDomains; preload"
 response.headers["Content-Security-Policy"]="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' https://pagead2.googlesyndication.com https://www.google.com https://www.googletagmanager.com https://www.googleadservices.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https:; media-src 'self' https:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://www.google.com https://www.googleadservices.com https://www.google-analytics.com https://region1.google-analytics.com https://www.googletagmanager.com; frame-src 'self' https://googleads.g.doubleclick.net https://tpc.googlesyndication.com; worker-src 'self'; upgrade-insecure-requests"
 response.headers["Cross-Origin-Opener-Policy"]="same-origin"
 response.headers["Cross-Origin-Resource-Policy"]="same-origin"
 response.headers["X-Permitted-Cross-Domain-Policies"]="none"
 if os.getenv("POLITICSHUB_LOCAL_ADMIN")=="1":
  # Loopback-only HTTP: avoid redirecting local JavaScript to HTTPS.
  response.headers.pop("Strict-Transport-Security",None)
  response.headers["Content-Security-Policy"]=response.headers["Content-Security-Policy"].replace("; upgrade-insecure-requests","")
 if request.path.startswith("/api/admin") or (request.path.startswith("/api/") and admin_ok()):
  response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
 elif request.path=="/api/health" or response.status_code>=400:
  response.headers["Cache-Control"]="no-store"
 elif request.method=="GET" and request.path.startswith("/api/") and "Cache-Control" not in response.headers:
  response.headers["Cache-Control"]="public, max-age=10, s-maxage=10, stale-while-revalidate=20"
 if response.status_code==429:
  response.headers["Retry-After"]="60"
 # Never let a logged-in browser populate a shared public HTML cache either.
 if session.get('admin_user') or admin_ok():
  response.headers["Cache-Control"]="private, no-store"
  response.headers["Vercel-CDN-Cache-Control"]="no-store"
  response.vary.add("Cookie")
 if request.method in ("GET","HEAD") and response.status_code==200 and response.cache_control.public and not response.is_streamed:
  response.add_etag()
  response.make_conditional(request)
 return response

@app.post("/api/admin/setup")
def setup_owner():
 if session.get("admin_user"):return jsonify({"error":"owner setup is disabled after sign-in"}),403
 key=os.getenv("ADMIN_SETUP_KEY","").strip() or os.getenv("ADMIN_TOKEN","").strip(); body=request.get_json(silent=True) or request.form.to_dict() or {}
 if not key:return jsonify({"error":"owner setup is disabled; configure ADMIN_SETUP_KEY or ADMIN_TOKEN first"}),503
 database=db()
 try:
  if not _auth_allowed(database,_setup_key(),_SETUP_MAX_FAILURES):return jsonify({"error":"too many setup attempts; try again later"}),429
  if not secrets.compare_digest(str(body.get("setup_key","")),key):
   _auth_failed(database,_setup_key()); return jsonify({"error":"invalid setup key"}),403
  username=str(body.get("username","")).strip(); password=str(body.get("password",""))
  if len(username)<3 or len(username)>40 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in username):return jsonify({"error":"invalid username"}),400
  if len(password)<12:return jsonify({"error":"password must be at least 12 characters"}),400
  count=int(database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()["count"] if database._postgres else database.conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()[0])
  if count:return jsonify({"error":"owner already exists; setup is permanently closed"}),409
  now=datetime.now(timezone.utc).isoformat(); ph="%s" if database._postgres else "?"; database.conn.execute(f"INSERT INTO admin_users (username,password_hash,role,created_at) VALUES ({ph},{ph},{ph},{ph})",(username,generate_password_hash(password),"owner",now))
  if not database._postgres:database.conn.commit()
  _auth_clear(database,_setup_key()); session.clear(); session["admin_user"]=username; session["admin_role"]="owner"; session["csrf_token"]=secrets.token_urlsafe(32); return jsonify({"ok":True,"username":username,"role":"owner","csrf_token":session["csrf_token"]})
 finally:database.close()

@app.post("/api/admin/login")
def login():
 body=request.get_json(silent=True) or request.form.to_dict() or {}
 username=str(body.get("username","")).strip()
 password=str(body.get("password",""))
 if not re.fullmatch(r'[A-Za-z0-9._-]{3,40}',username) or not 1<=len(password)<=256:
  return jsonify({'error':'invalid username or password'}),401
 # This guard works even when the persistent login-attempt table is unavailable.
 if not _ADMIN_LOGIN_RATE.allow(('ip',_client_key()),20,300) or not _ADMIN_LOGIN_RATE.allow(('user',username),12,300):
  return jsonify({'error':'too many login attempts; try again later'}),429
 try:database=db()
 except (DatabaseUnavailable,PostgresError):
  if verify_recovery_owner(username,password):return _signed_in(username,'recovery','recovery')
  return jsonify({'error':'invalid username or password'}),401
 attempt_key=_auth_key(username)
 ip_attempt_key=_ip_key()
 try:
  if not _auth_allowed(database,attempt_key,_LOGIN_MAX_FAILURES) or not _auth_allowed(database,ip_attempt_key,20):
   return jsonify({"error":"too many login attempts; try again later"}),429
  ph="%s" if database._postgres else "?"
  row=database.conn.execute("SELECT username,password_hash,role FROM admin_users WHERE username = "+ph,(username,)).fetchone()
  valid=bool(row and check_password_hash(row["password_hash"] if database._postgres else row[1],password))
  role=(row["role"] if database._postgres else row[2]) if row else None
  if not valid:
   _auth_failed(database,attempt_key)
   _auth_failed(database,ip_attempt_key)
   return jsonify({"error":"invalid username or password"}),401
  _auth_clear(database,attempt_key)
  _auth_clear(database,ip_attempt_key)
  return _signed_in(username,role or 'owner')
 except (DatabaseUnavailable,PostgresError):
  if verify_recovery_owner(username,password):return _signed_in(username,'recovery','recovery')
  return jsonify({'error':'invalid username or password'}),401
 finally:
  database.close()

# Render owns the root/www canonical redirect for the custom domain.
# Keep application routing host-neutral so assets and pages never enter a
# second redirect chain.

@app.get("/robots.txt")
def robots():
 return send_from_directory(app.static_folder, "robots.txt", mimetype="text/plain")

@app.get("/api/og-home")
def og_home():
  from app.social_preview import render_home
  return Response(render_home(),mimetype="image/png",
                  headers={"Cache-Control":"public, max-age=86400, s-maxage=86400",
                           "X-Content-Type-Options":"nosniff"})

@app.get("/api/og/<int:item_id>")
def og_image(item_id):
 payload=_og_image(item_id)
 if not payload:return jsonify({"error":"not found"}),404
 return Response(payload,mimetype="image/png",headers={"Cache-Control":"public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800"})

@app.get("/api/newsletter")
def newsletter_status():
 delivery=mail_configured(); storage=False; database=None
 if delivery:
  try:
   database=db(); database.conn.execute('SELECT 1'); storage=True
  except (RuntimeError,PostgresError):pass
  finally:
   if database is not None:database.close()
 available=delivery and storage
 message='' if available else ('Subscriptions are temporarily unavailable. Please try again later.' if delivery else 'Email delivery is being activated. Please check back soon.')
 response=jsonify({"ok":True,"available":available,"delivery_configured":delivery,"storage_available":storage,
  "message":message,"double_opt_in":True,"daily_brief":True})
 response.headers['Cache-Control']='public, max-age=15, s-maxage=60, stale-while-revalidate=30'
 return response

def _newsletter_page(title, lead, form="", notice=""):
 """Unsubscribe and confirmation links never activate on a GET from a mail scanner."""
 body = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
 '<meta name="robots" content="noindex,nofollow"><title>'+html.escape(title)+' — PoliticsHub.in</title>'
 '<link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="stylesheet" href="/assets/polish.css?v=phui30"><script src="/assets/ui.js?v=phui30" defer></script></head><body><main class="wrap" style="max-width:690px;padding:70px 24px">'
 '<a href="/" class="lbl">PoliticsHub.in</a><article class="art"><div class="ah"><span class="lbl red">PoliticsHub Brief</span>'
 '<h1>'+html.escape(title)+'</h1><p class="dek">'+html.escape(lead)+'</p></div><div class="body">'+form+
 '<p style="margin-top:25px"><a href="/newsletter.html">Newsletter</a> · <a href="/privacy.html">Privacy Policy</a></p></div></article></main></body></html>')
 return Response(body, mimetype="text/html",headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer","X-Robots-Tag":"noindex, nofollow"})

def _newsletter_current_story():
 try:return verified_story(_public_rows_for_section("all",80))
 except Exception:return None

@app.post("/api/newsletter")
def newsletter_subscribe():
 if not _public_rate_allowed(8,3600):return jsonify({"error":"Too many attempts. Please try again later."}),429
 if not mail_configured():return jsonify({"error":"Newsletter delivery is being configured. Please try again later."}),503
 body=request.get_json(silent=True) or request.form.to_dict() or {}
 email=str(body.get("email") or "").strip().lower()
 if not valid_email(email):return jsonify({"error":"Enter a valid email address."}),400
 if str(body.get("consent","")).lower() not in {"1","true","on","yes"}:
  return jsonify({"error":"Please agree to newsletter email delivery and the Privacy Policy."}),400
 if str(body.get("adult","")).lower() not in {"1","true","on","yes"}:
  return jsonify({"error":"Newsletter signup is available only to adults aged 18 and older."}),400
 try:
  database=db()
  try:
   token=request_optin(database,email)
   if token:
    try:
     send_mail(email,"Confirm your PoliticsHub Brief subscription","Confirm your email address",[
      "You requested the free PoliticsHub Brief newsletter.",
      "Click the button to confirm your subscription. We will send one sourced news briefing a day. This link expires in 48 hours.",
      "If you did not request this email, you can ignore it. You will not receive any news emails."
     ],action=("Confirm subscription",confirmation_link(token)))
    except Exception:
     # Avoid falsely claiming success or blocking retry for 30 minutes after SMTP failure.
     ph="%s" if database._postgres else "?"
     database.conn.execute(f"UPDATE newsletter_optins SET requested_at={ph} WHERE email={ph} AND status='pending'",((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),email))
     if not database._postgres:database.conn.commit()
     return jsonify({"error":"We couldn't send your confirmation email. Please try again later."}),503
  finally:database.close()
  return jsonify({"ok":True,"message":GENERIC_SIGNUP}),202
 except RuntimeError:
  return jsonify({"error":"Newsletter database is temporarily unavailable. No subscription was recorded."}),503

@app.route("/newsletter/confirm",methods=["GET","POST"])
def newsletter_confirm():
 token=str(request.values.get("token") or "")
 if request.method=="GET":
  if not token or len(token)>256:
   return _newsletter_page("Invalid confirmation link","Request a new confirmation email on the newsletter page."),400
  form='<form method="post" action="/newsletter/confirm"><input type="hidden" name="token" value="'+html.escape(token,quote=True)+'"><button class="btn" type="submit">Confirm my subscription</button></form>'
  return _newsletter_page("Confirm subscription","Confirm that you want a daily source-linked news briefing from PoliticsHub.in.",form)
 try:
  database=db()
  try:
   reader=confirm_optin(database,token)
   if not reader:return _newsletter_page("Link invalid or expired","Please subscribe again to request a new confirmation link."),400
   story=_newsletter_current_story()
   for sender in (lambda:send_welcome(database,reader,story,app.secret_key),
                  lambda:send_owner_alert(database,reader)):
    try:sender()
    except Exception as exc:app.logger.warning("Newsletter follow-up delivery delayed (%s)",type(exc).__name__)
   return _newsletter_page("You're subscribed!","Thank you for joining PoliticsHub Brief. Your welcome email and daily news briefings will follow.")
  finally:database.close()
 except RuntimeError:
  return _newsletter_page("Please try again later","The subscription service is temporarily unavailable."),503

@app.route("/newsletter/unsubscribe",methods=["GET","POST"])
def newsletter_unsubscribe_page():
 token=str(request.values.get("token") or "")
 if request.method=="GET":
  form='<form method="post" action="/newsletter/unsubscribe"><input type="hidden" name="token" value="'+html.escape(token[:1000],quote=True)+'"><button class="btn" type="submit">Unsubscribe from emails</button></form>'
  return _newsletter_page("Unsubscribe","Stop receiving PoliticsHub Brief emails immediately, without logging in.",form)
 try:
  database=db()
  try:unsubscribe_token(database,token,app.secret_key)
  finally:database.close()
 except RuntimeError:return _newsletter_page("Please try again later","We could not process this right now."),503
 return _newsletter_page("Unsubscribed","This subscription has been stopped. No further PoliticsHub Brief emails will be sent.")

@app.post("/api/newsletter/one-click")
def newsletter_one_click():
 # Mailbox providers send this explicit POST. GET requests never unsubscribe.
 if request.form.get("List-Unsubscribe")!="One-Click":
  return jsonify({"error":"Invalid unsubscribe request"}),400
 try:
  database=db()
  try:unsubscribe_token(database,str(request.args.get("token") or ""),app.secret_key)
  finally:database.close()
 except RuntimeError:return jsonify({"error":"Temporary error"}),503
 return Response(status=204)

@app.delete("/api/newsletter")
def newsletter_unsubscribe_by_email():
 """No third party may remove an account by merely knowing its email address."""
 if not _public_rate_allowed(8,3600):return jsonify({"error":"Too many requests."}),429
 email=str((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
 if not valid_email(email):return jsonify({"error":"Enter a valid email address."}),400
 if not mail_configured():return jsonify({"error":"Email service temporarily unavailable"}),503
 try:
  database=db()
  try:
   ensure_newsletter_tables(database)
   ph="%s" if database._postgres else "?"
   row=database.conn.execute(f"SELECT * FROM newsletter_optins WHERE email={ph} AND status='active'",(email,)).fetchone()
   if row:
    row=dict(row)
    last=row.get("last_manage_mail_at")
    can_send=True
    if last:
     try:can_send=datetime.now(timezone.utc)-datetime.fromisoformat(last.replace("Z","+00:00"))>timedelta(minutes=30)
     except ValueError:pass
    if can_send:
     send_mail(email,"Manage your PoliticsHub Brief subscription","Unsubscribe confirmation link",[
      "We received a request to stop PoliticsHub Brief emails for this address.",
      "Use the secure button to confirm. If you didn't request this, simply ignore this message."
     ],action=("Unsubscribe",email_unsubscribe_link(row["subscriber_id"],app.secret_key)))
     database.conn.execute(f"UPDATE newsletter_optins SET last_manage_mail_at={ph} WHERE email={ph}",(iso(),email))
     if not database._postgres:database.conn.commit()
  finally:database.close()
  return jsonify({"ok":True,"message":"If this email is subscribed, we've sent a secure unsubscribe link."})
 except Exception:return jsonify({"error":"Could not send the link right now. Please try again later."}),503

@app.get("/api/newsletter/daily")
def newsletter_daily():
 expected=os.getenv("CRON_SECRET","")
 supplied=request.headers.get("Authorization","")
 if not expected or not secrets.compare_digest(supplied,"Bearer "+expected):
  return jsonify({"error":"Unauthorized"}),401
 if not mail_configured():return jsonify({"error":"Gmail delivery is not configured"}),503
 story=_newsletter_current_story()
 if not story:return jsonify({"ok":True,"sent":0,"reason":"No recent source-linked story"}),200
 try:
  database=db()
  try:
   # Retry delayed welcome and owner mail before sending new daily briefs.
   ensure_newsletter_tables(database)
   pending=database.conn.execute("""SELECT * FROM newsletter_optins WHERE status='active'
     AND (welcome_sent_at IS NULL OR owner_sent_at IS NULL) ORDER BY confirmed_at LIMIT 5""").fetchall()
   for row in pending:
    record=dict(row)
    if not record.get("welcome_sent_at"):
     try:send_welcome(database,record,story,app.secret_key)
     except Exception:pass
    if not record.get("owner_sent_at"):
     try:send_owner_alert(database,record)
     except Exception:pass
   sent=send_daily(database,story,app.secret_key)
   return jsonify({"ok":True,"sent":sent,"story":story["title"]}),200
  finally:database.close()
 except RuntimeError:return jsonify({"error":"Newsletter database unavailable"}),503

@app.get("/api/briefing")
@app.get("/briefing/", strict_slashes=False)
def quick_briefing():
 desk=str(request.args.get("desk","all"))
 period=str(request.args.get("period","day"))
 if desk not in dict(BRIEFING_DESKS) or period not in {"day","week"}:
  return redirect("/briefing/",code=302)
 selected=select_briefing(_public_rows_for_section(desk,200),timestamp=_public_timestamp,
                         desk=desk,days=7 if period=="week" else 1)
 stories=[]
 for row in selected:
  published=datetime.fromtimestamp(_public_timestamp(row),timezone.utc)
  item=_publicize(row)
  summary=briefing_excerpt(item.get("summary"))
  stories.append({"title":item["title"],"category":item["category"],"href":article_path(item),
   "summary":summary,"source":item.get("source_name") or urlsplit(item["url"]).hostname,
   "url":item["url"],"iso":published.isoformat(),
   "date":published.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M")})
 return Response(render_template("briefing.html",stories=stories,desks=BRIEFING_DESKS,
  desk=desk,desk_label=dict(BRIEFING_DESKS)[desk],period=period),mimetype="text/html",
  headers={"Cache-Control":"public,max-age=60,s-maxage=180"})


@app.get("/api/seo-section/<category>")
@app.get("/<category>/", strict_slashes=False)
def seo_section(category):
 category=category.lower().strip()
 if category in {"business","technology","sports","entertainment","science","health"}:
  return redirect("/", code=301)
 if category=="maharashtra":
  return send_from_directory(app.static_folder,"maharashtra/index.html")
 if category not in set(CATEGORY_SLUGS.values()):
  if request.path.startswith("/api/"):return jsonify({"error":"not found"}),404
  return send_from_directory(app.static_folder,category)
 return Response(_enhance_section_seo(_section_html(category), category),mimetype="text/html",headers={"Cache-Control":"public,max-age=60,s-maxage=180"})

@app.get("/search.html")
def search_page():return redirect("/#/search",code=302)

@app.get("/status")
def public_status_page():return redirect("/#/settings/status",code=302)

@app.get("/author/politicshub-news-desk")
def author_page(): return _editorial_page("PoliticsHub News Desk","The PoliticsHub Editorial Desk publishes and edits newsroom stories, source links and public corrections.","author")

@app.get("/api/seo-article/<category>/<int:item_id>-<slug>")
@app.get("/<category>/<int:item_id>-<slug>")
def seo_article(category,item_id,slug):
 category=category.lower()
 if category not in set(CATEGORY_SLUGS.values()):
  return jsonify({"error":"not found"}),404
 row=_public_row_by_id(item_id)
 if not row:
  # During a database outage, historical items absent from the bounded
  # snapshot are temporarily inaccessible, not permanently deleted.
  try:
   database=db()
   database.close()
  except RuntimeError:
   message=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>Story currently unavailable — PoliticsHub.in</title><body style="font:16px/1.6 system-ui;max-width:680px;margin:8vh auto;padding:24px">'
    '<a href="/">PoliticsHub.in</a><h1>This story is temporarily unavailable</h1>'
    '<p>Our archive is temporarily unable to retrieve this article. It has not been deleted. '
    'Try again later, or browse the latest India, World and Politics news.</p>'
    '<a href="/">Back to latest news</a></body></html>')
   return Response(message,status=503,mimetype="text/html",headers={"Retry-After":"300","Cache-Control":"no-store"})
  return jsonify({"error":"not found"}),404
 canonical_path=article_path(row); requested=f"/{category}/{item_id}-{slug}"
 if requested.rstrip("/")!=canonical_path.rstrip("/"):return redirect(SITE_ORIGIN+canonical_path,code=301)
 return Response(_article_html(row),mimetype="text/html",headers={"Cache-Control":"public,max-age=60,s-maxage=180"})

@app.post("/api/admin/logout")
def logout():
 err=require_csrf()
 if err:return err
 session.clear(); return jsonify({"ok":True})

@app.get("/api/admin/me")
def me():return jsonify({"authenticated":bool(session.get("admin_user")),"username":session.get("admin_user"),"role":session.get("admin_role"),"scope":session.get('admin_scope','owner'),"read_only":recovery_session(),"expires_at":session.get('admin_expires_at'),"csrf_token":session.get("csrf_token") if session.get("admin_user") else None})


@app.get('/api/admin/workspace')
def admin_workspace():
 err=require_admin()
 if err:return err
 if not _public_rate_allowed(30,60):return jsonify({'error':'Workspace refresh limit reached. Please wait.'}),429
 started=time.monotonic(); database=None; connected=False; stats={}; settings={}; activity=[]
 try:
  database=db(); connected=True
  if not recovery_session():
   # Transfer a bounded projection, never 200 complete articles per refresh.
   fields=','.join(ADMIN_LIST_FIELDS)
   raw=database.conn.execute(f"SELECT {fields},LENGTH(COALESCE(bot_article,'')) AS article_length FROM news_items ORDER BY id DESC LIMIT 200").fetchall()
   counts=database.conn.execute("SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN status='published' THEN 1 ELSE 0 END),0) AS published,COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) AS pending,COALESCE(SUM(CASE WHEN fact_check_status='needs_review' THEN 1 ELSE 0 END),0) AS review_needed FROM news_items").fetchone()
   stats={key:int(counts[key]) for key in ('total','published','pending','review_needed')}
   settings=database.get_settings()
   activity=[dict(row) for row in database.recent_activity(8)]
   rows=admin_project_rows(raw)
 except (DatabaseUnavailable,PostgresError):
  connected=False
 finally:
  if database:database.close()
 snapshot=not connected or recovery_session()
 if snapshot:
  rows=admin_project_rows(sorted(_snapshot_rows(),key=_public_timestamp,reverse=True)[:200],snapshot=True)
  stats={'total':None,'published':len(rows),'pending':None,'review_needed':None}
 now=datetime.now(timezone.utc)
 latest=max((r['timestamp'] for r in rows if r['timestamp'] is not None),default=None)
 writable=connected and not recovery_session()
 return jsonify({'version':2,'generated_at':now.isoformat(),'mode':'snapshot' if snapshot else 'live',
   'data_origin':'termux_github' if os.getenv("VERCEL")=="1" or os.getenv("POLITICSHUB_GITHUB_FEED_ONLY")=="1" else 'local_database',
  'access':{'username':session.get('admin_user') or 'API token','scope':'recovery' if recovery_session() else 'owner','read_only':not writable,'expires_at':session.get('admin_expires_at')},
  'capabilities':{'publish':writable,'settings':writable,'telemetry':writable,'export':True},
  'health':{'database':'connected' if connected else 'unavailable','snapshot_available':bool(rows) if snapshot else None,
   'latest_published_at':datetime.fromtimestamp(latest,timezone.utc).isoformat() if latest else None,
   'latest_age_seconds':max(0,int(now.timestamp()-latest)) if latest else None,
   'response_ms':round((time.monotonic()-started)*1000),'reauthenticate':connected and recovery_session()},
  'stats':stats,'settings':settings,'activity':activity,'stories':rows,'coverage':admin_coverage(rows),
  'limits':{'stories':200,'coverage_scope':'loaded stories','refresh_seconds':60},
  'notice':('Termux is the primary news database. This website reads the published GitHub feed; editorial changes happen on the phone.' if os.getenv("VERCEL")=="1" else
   'Database restored. Sign out and sign in again for owner access.' if connected and recovery_session() else
   'Database unavailable. Showing the latest public snapshot; editorial changes are paused.' if snapshot else '')})


@app.get('/api/admin/stories')
def admin_story_queue():
 err=require_admin()
 if err:return err
 if not _public_rate_allowed(60,60):return jsonify({'error':'Please wait before refreshing the queue.'}),429
 try:
  page=max(1,min(int(request.args.get('page','1')),1000))
 except ValueError:return jsonify({'error':'Invalid page'}),400
 filters={key:str(request.args.get(key,'all')).strip()[:120] for key in ('category','source','status','review')}
 if filters['status'] not in {'all','pending','published','rejected'}:return jsonify({'error':'Invalid publication status'}),400
 query=str(request.args.get('search','')).strip()[:120]
 database=db()
 try:
  ph='%s' if database._postgres else '?'; clauses=[]; params=[]
  for key,column in (('category','category'),('source','source_name'),('status','status'),('review','fact_check_status')):
   if filters[key]!='all':clauses.append(f'{column}={ph}');params.append(filters[key])
  if query:
   clauses.append(f'(LOWER(title) LIKE LOWER({ph}) OR LOWER(COALESCE(summary,bot_summary,\'\')) LIKE LOWER({ph}) OR LOWER(source_name) LIKE LOWER({ph}))')
   params.extend([f'%{query}%']*3)
  quality="(COALESCE(NULLIF(bot_summary,''),summary,'')='' OR COALESCE(image_url,'')='' OR COALESCE(url,'')='' OR COALESCE(bot_article,'')='' OR fact_check_status='needs_review')"
  if request.args.get('quality')=='1':clauses.append(quality)
  where=' WHERE '+' AND '.join(clauses) if clauses else ''
  sorts={'newest':'id DESC','oldest':'id ASC','views':'COALESCE(view_count,0) DESC,id DESC','quality':f'CASE WHEN {quality} THEN 1 ELSE 0 END DESC,id DESC'}
  order=sorts.get(request.args.get('sort','newest'),'id DESC')
  count=database.conn.execute('SELECT COUNT(*) AS total FROM news_items'+where,tuple(params)).fetchone()['total']
  fields=','.join(ADMIN_LIST_FIELDS)
  raw=database.conn.execute(f"SELECT {fields},LENGTH(COALESCE(bot_article,'')) AS article_length FROM news_items{where} ORDER BY {order} LIMIT {ph} OFFSET {ph}",(*params,25,(page-1)*25)).fetchall()
  return jsonify({'stories':admin_project_rows(raw),'total':int(count),'page':page,'page_size':25,'mode':'live'})
 finally:database.close()

@app.get("/api/health")
def health():
 if os.getenv("VERCEL") == "1" or os.getenv("POLITICSHUB_GITHUB_FEED_ONLY") == "1":
  rows=_snapshot_rows("all")
  newest=max((_public_timestamp(r) for r in rows),default=0)
  result={"ok":bool(rows),"mode":"github_feed" if rows else "unavailable",
   "storage":"termux","delivery":"github","stories":len(rows),
   "latest_published_at":datetime.fromtimestamp(newest,timezone.utc).isoformat() if newest else None}
  return jsonify(result),(200 if rows else 503)
 try:
  database=db()
  try:
   row=database.newest_public()
   newest=_public_timestamp(dict(row)) if row else None
  finally:database.close()
  return jsonify({"ok":True,"mode":"live","latest_published_at":datetime.fromtimestamp(newest,timezone.utc).isoformat() if newest else None})
 except RuntimeError:
  rows=_snapshot_rows()
  newest=max((_public_timestamp(r) for r in rows),default=0)
  return jsonify({"ok":False,"mode":"snapshot" if rows else "unavailable","latest_published_at":datetime.fromtimestamp(newest,timezone.utc).isoformat() if newest else None}),503


@app.get("/api/maharashtra")
def maharashtra_public_feed():
 from api.maharashtra_feed import get_feed
 try:
  data=get_feed(request.args.get('lang','mr'))
  response=jsonify(data)
  # The published RSS headlines are refreshed at most once per 20 minutes.
  ttl=60 if data.get('status') in {'stale','unavailable'} else 1200
  response.headers["Cache-Control"]=f"public, max-age=0, s-maxage={ttl}, stale-while-revalidate=60"
  return response
 except Exception:
  return jsonify({"items":[],"sources":{},"status":"unavailable","refresh_minutes":20}),503

@app.get("/api/hindi-feed")
def public_hindi_feed():
 rows=_rank_public(_hindi_rows())[:120]
 response=jsonify(rows)
 response.headers["Cache-Control"]="public, max-age=60, s-maxage=300"
 return response

@app.get("/api/news")
@app.get("/api/admin/news")
def news():
 if request.path.startswith('/api/admin/'):
  err=require_admin()
  if err:return err
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 category=request.args.get("category","all").lower().strip(); status=request.args.get("status","published"); review=request.args.get("review_status","all"); search=request.args.get("search"); compact=request.args.get("compact","0")=="1"
 if category!="all" and category not in {"general","india","world","politics","business","technology","sports","entertainment","science","health","hindi"}:return jsonify({"error":"invalid category"}),400
 if search is not None: search=str(search).strip()[:120]
 try:limit=min(max(int(request.args.get("limit","200")),1),200)
 except ValueError:limit=100
 if not admin_ok():status,review="published","all"
 try:database=db()
 except Exception:
  # When the database is unavailable, publish only a valid saved snapshot.
  rows=_snapshot_rows(category,search)
  if not rows:return jsonify({"error":"news backend unavailable"}),503
  rows=_rank_public(rows,threshold=0.78)
  payload=rows_json(rows[:limit],compact=compact)
  if not admin_ok():
   for item in payload:
    for key in ("article","bot_article","bot_summary"):item.pop(key,None)
  response=jsonify(payload)
  response.headers["X-News-Mode"]="snapshot"
  response.headers["Cache-Control"]="public, max-age=15, s-maxage=60, stale-while-revalidate=120"
  return response
 try:
  public_listing=not admin_ok()
  if public_listing:
   # Listing cards never need the full editorial article/AI fields.
   records=database.latest_public(max(limit*3,limit),"all" if category in ("india","entertainment") else category,search)
  else:
   records=database.latest(max(limit*6,limit),"all" if category in ("india","entertainment") else category,status,search,review)
  rows=_rank_public(records,threshold=0.78)
  if category!="all":rows=[x for x in rows if x.get("category")==category]
  # A healthy database is authoritative; never resurrect removed stories.
  payload=rows_json(rows[:limit],compact=compact)
  if public_listing:
   for item in payload:
    for key in ('article','bot_article','bot_summary'):item.pop(key,None)
  response=jsonify(payload)
  # Public news is refreshed by a 30-minute collection cadence. CDN caching
  # avoids waking a free-tier Postgres compute on every visitor refresh.
  # Admin API responses remain uncacheable through the after_request policy.
  if not admin_ok() and status=="published" and not search:
   response.headers["Cache-Control"]="public, max-age=30, s-maxage=600, stale-while-revalidate=300"
  return response
 finally:database.close()

@app.get("/api/search")
def public_search():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 q=str(request.args.get("q","")).strip()[:120]
 if len(q)<2:return jsonify([])
 try:
  limit=min(max(int(request.args.get("limit","30")),1),50)
  offset=max(int(request.args.get("offset","0")),0)
 except ValueError:return jsonify({"error":"Invalid search pagination"}),400
 category=str(request.args.get("category","all")).lower()
 if category not in {"all","india","world","politics","hindi","maharashtra"}:
  return jsonify({"error":"Invalid search category"}),400
 if offset>100000:return jsonify({"error":"Search offset is too large"}),400
 source=str(request.args.get("source","")).strip()[:120].casefold()
 period=str(request.args.get("period","all"))
 if period not in {"all","day","week","month"}:return jsonify({"error":"Invalid search period"}),400
 cutoff=time.time()-{"day":1,"week":7,"month":30}[period]*86400 if period!="all" else 0
 database=None
 try:
  database=db()
  rows=[dict(row) for row in database.search_public(q)]+_archive_rows(database,q)
 except RuntimeError:
  rows=_snapshot_rows("all",q)+_archive_rows(search=q)
 finally:
  if database is not None:database.close()
 # Deduplicate identities, not similar headlines across different news dates.
 unique=[]; ids=set(); urls=set()
 for row in rows:
  if str(row["id"]) in ids or row.get("url") in urls:continue
  ids.add(str(row["id"])); urls.add(row.get("url"))
  row["category"]=normalize_category(row.get("category"),row.get("title"),row.get("bot_summary") or row.get("summary"))
  if category!="all" and row["category"]!=category:continue
  if source and str(row.get("source_name") or row.get("source") or "").casefold()!=source:continue
  if cutoff and _public_timestamp(row)<cutoff:continue
  unique.append(row)
 unique.sort(key=lambda row:(public_archive.timestamp(row),int(row["id"])),reverse=True)
 payload=rows_json(unique[offset:offset+limit])
 if not admin_ok():
  for item in payload:
   for key in ("article","bot_article","bot_summary"):item.pop(key,None)
 response=jsonify(payload)
 response.headers["X-Search-Total"]=str(len(unique))
 response.headers["Cache-Control"]="public, max-age=0, s-maxage=30, stale-while-revalidate=30"
 return response

@app.get("/api/trending")
def trending():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 try:limit=min(max(int(request.args.get("limit","10")),1),30)
 except ValueError:limit=10
 try:database=db()
 except RuntimeError:
  # Counts and breaking alerts cannot be reconstructed faithfully from an
  # archived snapshot; return an explicit empty fallback, not stale live claims.
  if not _snapshot_rows():return jsonify({"error":"news backend unavailable"}),503
  response=jsonify([])
  response.headers["X-News-Mode"]="snapshot"
  response.headers["Cache-Control"]="no-store"
  return response
 try:return jsonify(rows_json([dict(row) for row in database.trending(limit)]))
 finally:database.close()

@app.get("/api/breaking")
def breaking():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 try:database=db()
 except RuntimeError:
  # Counts and breaking alerts cannot be reconstructed faithfully from an
  # archived snapshot; return an explicit empty fallback, not stale live claims.
  if not _snapshot_rows():return jsonify({"error":"news backend unavailable"}),503
  response=jsonify([])
  response.headers["X-News-Mode"]="snapshot"
  response.headers["Cache-Control"]="no-store"
  return response
 try:
  rows=_rank_public(database.latest_public(100,"all"))
  return jsonify(rows_json([r for r in rows if r.get("is_breaking")][:12]))
 finally:database.close()

@app.post("/api/news/<int:item_id>/view")
def article_view(item_id):
 if not _public_rate_allowed(60,60):return jsonify({"error":"rate limit exceeded"}),429
 try:database=db()
 except RuntimeError:return jsonify({"ok":False,"tracked":False}),200
 try:
  if not database.increment_view(item_id):return jsonify({"error":"not found"}),404
  return jsonify({"ok":True,"tracked":True})
 finally:database.close()

@app.get("/api/news/<int:item_id>")
def article(item_id):
 try:database=db()
 except RuntimeError:
  snapshot=next((x for x in _snapshot_rows("all") if str(x.get("id"))==str(item_id)),None)
  if snapshot:return jsonify(_publicize(snapshot))
  archived=_archive_row(item_id)
  if archived:return jsonify(_publicize(archived))
  proxied=_proxy_public("/api/news/"+str(item_id))
  return proxied or (jsonify({"error":"news backend unavailable"}),503)
 try:
  row=database.get_by_id(item_id,"all")
  if row and (row["status"]=="published" or admin_ok()):return jsonify(_publicize(row))
  if row is None:
   archived=_archive_row(item_id,database)
   if archived:return jsonify(_publicize(archived))
  return jsonify({"error":"not found"}),404
 finally:database.close()

@app.get("/api/stats")
def stats():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings()
  return jsonify({"total":database.count(),"pending":database.count_status("pending"),"review_needed":database.count_status("published","needs_review"),"published":database.count_status("published"),"website_enabled":settings.get("website_enabled","true")=="true"})
 finally:database.close()


@app.get("/api/admin/dashboard")
def admin_dashboard():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings()
  return jsonify({"settings":settings,"stats":{"total":database.count(),"pending":database.count_status("pending"),"review_needed":database.count_status("published","needs_review"),"published":database.count_status("published"),"website_enabled":settings.get("website_enabled","true")=="true"},"activity":rows_json(database.recent_activity(20))})
 finally:database.close()

@app.get("/api/admin/health")
def admin_health():
 err=require_admin()
 if err:return err
 database=db()
 try:return jsonify({"ok":True,"database":"connected","website_enabled":database.get_settings().get("website_enabled","true")=="true","news_count":database.count()})
 finally:database.close()

@app.get("/api/admin/activity")
def admin_activity():
 err=require_admin()
 if err:return err
 database=db()
 try:return jsonify([dict(r) for r in database.recent_activity(request.args.get("limit",50))])
 finally:database.close()


@app.get("/api/admin/live")
def admin_live():
 err=require_admin()
 if err:return err
 database=db()
 try:
  ensure_advanced_schema(database)
  return jsonify(live_dashboard(database))
 finally: database.close()

@app.get("/api/admin/upgrade")
def admin_upgrade():
 err=require_admin()
 if err:return err
 database=db()
 try:
  ensure_upgrade_schema(database)
  snapshot=admin_snapshot(database)
  event_id=str(request.args.get("event_id","")).strip()
  if event_id:
   snapshot["event_timeline"]=event_timeline(database,event_id)
  else:
   snapshot["event_timeline"]=[]
  return jsonify(snapshot)
 finally: database.close()

@app.get("/api/admin/history")
def admin_history():
 err=require_admin()
 if err:return err
 try: days=max(1,min(int(request.args.get("days","30")),365))
 except ValueError: days=30
 database=db()
 try:
  ensure_upgrade_schema(database)
  return jsonify(historical_analytics(database,days))
 finally: database.close()

@app.get("/api/admin/report")
def admin_detailed_report():
 err=require_admin()
 if err:return err
 try: days=max(1,min(int(request.args.get("days","7")),90))
 except ValueError: days=7
 database=db()
 try:
  payload=detailed_report(database,days)
  payload["generated_at"]=datetime.now(timezone.utc).isoformat()
  return jsonify(payload)
 finally: database.close()

@app.post("/api/admin/verification/<int:item_id>")
def admin_verify(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}
 database=db()
 try:
  classification=record_verification(database,item_id,int(body.get("source_count",0)),body.get("source_names") or [],body.get("conflicts") or [])
  audit_stage(database,item_id,"VERIFICATION","completed",{"classification":classification})
  return jsonify({"ok":True,"classification":classification})
 finally: database.close()

@app.get("/api/admin/operations")
def admin_operations():
 err=require_admin()
 if err:return err
 database=db()
 try:
  # A dashboard refresh is a read, not a completed reporting-agent task.
  # Collection workers own clustering and the actual task telemetry.
  ops=phase_analytics(database,7)
  recent_errors=[dict(r) for r in database.conn.execute("SELECT agent_id,operation,error,started_at FROM ph_agent_runs WHERE status='failed' ORDER BY id DESC LIMIT 20").fetchall() if r["agent_id"] in AGENTS]
  clusters=cluster_summary(database)
  total=database.count()
  coverage=database.published_coverage()
  published=coverage["published"]
  with_article=coverage["with_article"]
  images=coverage["with_image"]
  ops["content_quality"]={"published":published,"with_article":with_article,"article_coverage_percent":round(with_article/published*100,1) if published else None,"with_image":images,"image_coverage_percent":round(images/published*100,1) if published else None,"cluster_count":len(clusters)}
  ops["recent_errors"]=recent_errors
  return jsonify(ops)
 finally:database.close()

@app.get("/api/admin/operations.pdf")
def admin_operations_pdf():
 err=require_admin()
 if err:return err
 database=db()
 try:
  pdf=operations_pdf(database,7)
  from flask import Response
  return Response(pdf,mimetype="application/pdf",headers={"Content-Disposition":"attachment; filename=politicshub-operations-report.pdf","Cache-Control":"no-store"})
 finally:database.close()

@app.post("/api/admin/training")
def admin_training():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}
 agent_id=str(body.get("agent_id","")).strip()
 notes=str(body.get("notes","")).strip()
 if not agent_id or agent_id not in __import__("app.phase_system",fromlist=["AGENTS"]).AGENTS:return jsonify({"error":"unknown agent"}),400
 database=db()
 try:
  with __import__("app.phase_system",fromlist=["run"]).run(database,"hr","record_training",metadata={"agent_id":agent_id}):
   train_agent(database,agent_id,str(body.get("event_type") or "knowledge_update"),notes)
  log_admin(database,"agent.training",None,agent_id)
  return jsonify({"ok":True,"agent_id":agent_id})
 finally:database.close()

@app.get("/api/admin/settings")
def admin_settings():
 err=require_admin()
 if err:return err
 database=db()
 try:return jsonify(database.get_settings())
 finally:database.close()

@app.post("/api/admin/settings")
def save_settings():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True)
 if not isinstance(body,dict) or set(body)-{"website_enabled"}:return jsonify({"error":"Unsupported settings"}),400
 values={}
 if "website_enabled" in body:
  if not isinstance(body["website_enabled"],bool):return jsonify({"error":"website_enabled must be a boolean"}),400
  values["website_enabled"]="true" if body["website_enabled"] else "false"
 database=db()
 try:
  database.set_settings(values)
  log_admin(database,"settings.update",None,",".join(values))
  return jsonify({"ok":True,"settings":database.get_settings()})
 finally:database.close()

def change(item_id,status=None,**extra):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  fields=dict(extra);
  existing=database.get_by_id(item_id)
  if not existing:return jsonify({'error':'story not found'}),404
  if status=="published":
   if existing and existing["source_type"]=="x" and existing["fact_check_status"]!="reviewed":
    return jsonify({"error":"X post needs source and context review before publishing"}),409
   if os.getenv("POLITICSHUB_LOCAL_ADMIN")=="1":
    # Explicit verification is required before making a phone story public.
    row=dict(existing)
    if row.get("status")=="published":return jsonify({"error":"Story is already published"}),409
    if not row.get("approved_at") or str(row.get("fact_check_status") or "").lower() not in {"reviewed","verified","passed","approved"}:
     return jsonify({"error":"Verify and approve this story before publishing"}),409
    if not bool(row.get("public_source")) or len((row.get("bot_article") or "").strip())<600:
     return jsonify({"error":"Public source and a complete article are required"}),409
    from scripts.mobile_editorial_approve import parse_published,MAX_AGE
    original=parse_published(row.get("published_at") or row.get("published_at_site"))
    now=datetime.now(timezone.utc)
    if original is None or now-original>MAX_AGE or original>now+timedelta(minutes=30):
     return jsonify({"error":"Old/future-dated news cannot be published as breaking news"}),409
    fields["published_at_site"]=str(row.get("published_at") or row.get("published_at_site"))
  if status is not None:fields["status"]=status
  database.update(item_id,**fields); log_admin(database,"news.update",item_id,",".join(fields.keys())); return jsonify({"ok":True,**fields})
 finally:database.close()

@app.post("/api/news/<int:item_id>/approve")
def approve(item_id):
 if os.getenv("POLITICSHUB_LOCAL_ADMIN")!="1":
  return change(item_id,fact_check_status="reviewed",approved_at=datetime.now(timezone.utc).isoformat())
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 data=request.get_json(silent=True) or {}
 if data.get("confirm")!="APPROVE "+str(item_id) or data.get("confirmed_facts") is not True or data.get("confirmed_originality") is not True:
  return jsonify({"error":"Exact story confirmation and independent verification required"}),400
 from scripts.mobile_editorial_approve import check_evidence,review_eligibility
 links=data.get("evidence_urls")
 notes=str(data.get("notes") or "").strip()
 if not isinstance(links,list) or len(links)>6 or any(not isinstance(link,str) for link in links) or not 40<=len(notes)<=4000:
  return jsonify({"error":"Provide independent evidence URLs and substantive editorial notes"}),400
 database=db()
 try:
  with database.conn.transaction():
   row=database.conn.execute("SELECT * FROM news_items WHERE id=%s FOR UPDATE",(item_id,)).fetchone()
   if not row:return jsonify({"error":"Story not found"}),404
   current=dict(row)
   issues=review_eligibility(current)
   _,errors=check_evidence(current,links)
   if issues or errors:return jsonify({"error":"Approval blocked: "+"; ".join(issues+errors)}),409
   stamp=datetime.now(timezone.utc).isoformat()
   result=database.conn.execute(
    "UPDATE news_items SET fact_check_status=%s,fact_check_notes=%s,approved_at=%s WHERE id=%s AND status=%s AND approved_at IS NULL",
    ("reviewed","Human verified at "+stamp+". Evidence: "+"; ".join(links)+". Notes: "+notes,stamp,item_id,"pending"))
   if result.rowcount!=1:return jsonify({"error":"Approval conflict; reopen story"}),409
   database.conn.execute(
    "INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES (%s,%s,%s,%s,%s)",
    (session.get("admin_user"),"news.approve",item_id,"Verified source/context/originality on phone",stamp))
  return jsonify({"ok":True,"id":item_id,"status":"pending","fact_check_status":"reviewed"})
 finally:database.close()
@app.post("/api/news/<int:item_id>/reject")
def reject(item_id):return change(item_id,status="rejected")
@app.post("/api/news/<int:item_id>/publish")
def publish(item_id):return change(item_id,status="published",published_at_site=datetime.now(timezone.utc).isoformat())

@app.post("/api/admin/news/create")
def create_manual_story():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True)
 if not isinstance(body,dict):return jsonify({"error":"JSON body required"}),400
 title=str(body.get("title") or "").strip()
 summary=str(body.get("summary") or "").strip()
 article=str(body.get("article") or "").strip()
 category=str(body.get("category") or "india").lower().strip()
 original=str(body.get("source_url") or "").strip()
 source=str(body.get("source_name") or "PoliticsHub Editorial").strip()
 image=str(body.get("image_url") or "").strip()
 image_license=str(body.get("image_license") or "").strip().lower()
 image_credit=str(body.get("image_credit") or "").strip()
 if not 20<=len(title)<=250 or not 60<=len(summary)<=1800 or not 600<=len(article)<=50000:
  return jsonify({"error":"Headline 20-250 chars, summary 60-1800 chars and article 600-50000 chars required"}),400
 if category not in {"india","world","politics","maharashtra","hindi","general"}:
  return jsonify({"error":"Select a supported news desk"}),400
 from urllib.parse import urlsplit
 src=urlsplit(original)
 if src.scheme!="https" or not src.hostname or src.username or len(original)>2000:
  return jsonify({"error":"A valid HTTPS reporting/source URL is required"}),400
 if image:
  parsed=urlsplit(image)
  if parsed.scheme!="https" or not parsed.hostname or parsed.username or len(image)>2000:
   return jsonify({"error":"Image must be an HTTPS URL"}),400
  if image_license not in {"cc0","pdm","rights-owned","licensed"}:
   return jsonify({"error":"Specify image rights before using an image"}),400
  if not image_credit:return jsonify({"error":"Image credit is required"}),400
 if len(source)>160:return jsonify({"error":"Source name too long"}),400
 import uuid
 from app.normalize import normalize_url,fingerprint
 now=datetime.now(timezone.utc).isoformat()
 reference=normalize_url(original)
 unique=str(uuid.uuid4())
 normalized=reference+"#manual-"+unique
 url_hash,title_hash=fingerprint(normalized,title)
 database=db()
 try:
  ph="%s" if database._postgres else "?"
  keys=("source_name","source_type","title","url","normalized_url",
        "published_at","summary","external_id","url_hash","title_hash",
        "collected_at","category","image_url","public_source","bot_summary",
        "bot_article","image_source","image_license","image_credit","image_source_url",
        "fact_check_status","status")
  params=(source,"manual",title,original,normalized,now,summary,
          "manual-"+unique,url_hash,title_hash,now,category,image,1,summary,
          article,"article-source" if image else "",image_license,image_credit,
          image if image else "","pending","pending")
  with database.conn.transaction() if database._postgres else __import__("contextlib").nullcontext():
   if database._postgres:
    result=database.conn.execute(
     "INSERT INTO news_items ("+",".join(keys)+") VALUES ("
     +",".join([ph]*len(keys))+") RETURNING id",params)
    item_id=result.fetchone()[0]
   else:
    result=database.conn.execute(
     "INSERT INTO news_items ("+",".join(keys)+") VALUES ("
     +",".join([ph]*len(keys))+")",params)
    item_id=result.lastrowid
   database.conn.execute(
    "INSERT INTO admin_activity (username,action,item_id,details,created_at) VALUES ("
    +",".join([ph]*5)+")",
    (session.get("admin_user"),"news.manual.create",item_id,"Manual editorial draft created, verification pending",now))
   if not database._postgres:database.conn.commit()
  return jsonify({"ok":True,"id":item_id,"status":"pending","message":"Draft saved. Verify and approve before publishing."}),201
 finally:database.close()


@app.post("/api/news/<int:item_id>/edit")
def edit_news(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; fields={k:str(body[k] or "").strip() for k in ("title","summary","category","image_url","bot_summary","bot_article") if k in body}
 if not fields:return jsonify({"error":"no editable fields supplied"}),400
 if "title" in fields and not fields["title"]:return jsonify({"error":"title cannot be empty"}),400
 if 'title' in fields and len(fields['title'])>500:return jsonify({'error':'Headline must be at most 500 characters'}),400
 if any(len(fields.get(key,''))>6000 for key in ('summary','bot_summary')):return jsonify({'error':'Summary must be at most 6000 characters'}),400
 if 'category' in fields and fields['category'] not in {'general','india','world','politics','business','technology','sports','entertainment','science','health','hindi','maharashtra'}:
  return jsonify({'error':'Invalid editorial desk'}),400
 database=db()
 try:
  existing=database.get_by_id(item_id)
  if not existing:return jsonify({'error':'story not found'}),404
  revision=request.headers.get('If-Match','').strip('"')
  if revision:
   current=dict(existing)
   if revision!=editorial_revision(current):return jsonify({'error':'This story changed in another session. Reopen the inspector before saving.'}),409
   ph='%s' if database._postgres else '?'
   assignments=','.join(f'{key}={ph}' for key in fields)
   conditions=' AND '.join(f"COALESCE({key},'')={ph}" for key in EDITORIAL_FIELDS)
   updated=database.conn.execute(f'UPDATE news_items SET {assignments} WHERE id={ph} AND {conditions}',(*fields.values(),item_id,*(str(current.get(key) or '') for key in EDITORIAL_FIELDS))).rowcount
   if not database._postgres:database.conn.commit()
   if not updated:return jsonify({'error':'This story changed during your edit. Reopen the inspector before saving.'}),409
  else:database.update(item_id,**fields)
  log_admin(database,"news.edit",item_id,",".join(fields.keys())); return jsonify({"ok":True,"fields":fields})
 finally:database.close()


@app.get('/api/admin/story/<int:item_id>/article')
def admin_private_article(item_id):
 # Public /api/news/<id> intentionally hides pending editorial manuscripts.
 # The same-origin signed bridge exposes the full text only to a logged-in
 # owner/editor. It is never cached by Vercel or included in the public feed.
 err=require_admin()
 if err:return err
 database=db()
 try:
  row=database.get_by_id(item_id)
  if not row:return jsonify({'error':'story not found'}),404
  row=dict(row)  # Also supports sqlite3.Row during isolated browser tests.
  text=str(row.get('bot_article') or row.get('article') or row.get('summary') or '')
  response=jsonify({'id':item_id,'article':text,'status':row.get('status')})
  response.headers['Cache-Control']='private, no-store'
  return response
 finally:database.close()


@app.get('/api/admin/story/<int:item_id>')
def admin_editorial_draft(item_id):
 err=require_admin()
 if err:return err
 database=db()
 try:
  row=database.get_by_id(item_id)
  if not row:return jsonify({'error':'story not found'}),404
  row=dict(row)
  return jsonify({'id':item_id,'title':row.get('title') or '',
   'summary':row.get('bot_summary') or row.get('summary') or '',
   'category':row.get('category') or 'general','revision':editorial_revision(row)})
 finally:database.close()

def _editorial_source_packets(database, row, limit=4):
 """Collect distinct source material for factual cross-source curation."""
 target_hash=str(row.get("title_hash") or "").strip()
 target_title=str(row.get("title") or "").strip()
 target_source=str(row.get("source_name") or "").strip()
 candidates=[]
 for item in database.latest(1000,status="all"):
  item=dict(item)
  if int(item.get("id") or 0)==int(row.get("id") or 0): continue
  source_name=str(item.get("source_name") or "").strip()
  if not source_name or source_name==target_source: continue
  same_hash=bool(target_hash and str(item.get("title_hash") or "").strip()==target_hash)
  a=set(re.findall(r"[a-z0-9]+",target_title.lower()))
  b=set(re.findall(r"[a-z0-9]+",str(item.get("title") or "").lower()))
  similarity=len(a&b)/max(1,len(a|b))
  if same_hash or similarity>=0.62:
   candidates.append(item)
  if len(candidates)>=12: break

 packets=[]
 seen=set()
 # Primary source first.
 primary=enrich_source_text(target_title,str(row.get("summary") or ""),str(row.get("url") or ""))
 if primary.get("text"):
  packets.append({"source_name":target_source or "Primary source","url":primary.get("url") or row.get("url") or "","text":primary.get("text")})
  seen.add(target_source or "Primary source")

 for item in candidates:
  name=str(item.get("source_name") or "").strip()
  if not name or name in seen: continue
  fetched=enrich_source_text(str(item.get("title") or ""),str(item.get("summary") or ""),str(item.get("url") or ""))
  text_value=fetched.get("text") or ""
  if len(text_value)<80: continue
  packets.append({"source_name":name,"url":fetched.get("url") or item.get("url") or "","text":text_value})
  seen.add(name)
  if len(packets)>=limit: break
 return packets


@app.post("/api/news/<int:item_id>/process")
def process_item(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  row=(dict(database.get_by_id(item_id,"all")) if database.get_by_id(item_id,"all") else None)
  if not row:return jsonify({"error":"not found"}),404
  source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or ""); material=source.get("text") or row.get("summary") or row.get("title") or ""; packets=_editorial_source_packets(database,row); result=process_news(row["title"],material,row.get("category") or "general",source_materials=packets)
  if not result:return jsonify({"error":"bot could not produce complete content from available material"}),422
  fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"],"editorial_context":result.get("editorial_context") or "", "editorial_value":1 if result.get("editorial_value") else 0, "source_count":int(result.get("source_count") or 0)}
  # Never persist Telegram CDN images as site assets. A branded OG image is generated server-side.
  if source.get("image_url") and not is_telegram_image(source.get("image_url")) and not row.get("image_url"):fields["image_url"]=source["image_url"]
  elif row.get("image_url") and is_telegram_image(row.get("image_url")):fields["image_url"]=None
  database.update(item_id,**fields); log_admin(database,"news.process",item_id,"deterministic_bot"); return jsonify({"ok":True,"mode":"deterministic_bot","headline":result["headline"],"summary":result["summary"],"article":result["article"]})
 finally:database.close()

@app.post("/api/news/<int:item_id>/ai")
def legacy_process(item_id):return process_item(item_id)


@app.post("/api/fact-check")
def fact_check():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  checked=run_cross_source_check(database); log_admin(database,"fact_check.run",None,str(checked)); return jsonify({"ok":True,"checked":checked})
 finally:database.close()


def _xml_escape(value):
 return html.escape(str(value or ""),quote=True)


def _sitemap_static_xml():
 urls=["/","/about.html","/contact.html","/editorial-policy.html","/corrections.html","/privacy.html","/cookies.html","/terms.html","/disclaimer.html","/newsletter.html","/data-rights.html","/licenses.html"]
 body="".join("<url><loc>"+_xml_escape(SITE_ORIGIN+p)+"</loc></url>" for p in urls)
 return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"+body+"</urlset>"


def _published_sitemap_rows():
 try:
  database=db()
  try:
   rows=database.conn.execute(
    "SELECT id,title,category,published_at_site,published_at,bot_article,"
    "bot_summary,summary,source_type,public_source,url,status "
    "FROM news_items WHERE status='published' AND public_source<>0 "
    "AND LOWER(COALESCE(source_type,''))<>'telegram' "
    "AND LENGTH(COALESCE(NULLIF(bot_summary,''),summary,''))>=80 "
    "AND LENGTH(COALESCE(NULLIF(bot_article,''),NULLIF(bot_summary,''),summary,''))>=300 "
    "ORDER BY COALESCE(NULLIF(published_at_site,''),published_at) DESC,id DESC"
   ).fetchall()
   return [dict(r) for r in rows]+_archive_rows(database,discovery=True)
  finally:
   database.close()
 except RuntimeError:
  return _snapshot_rows("all")+_archive_rows(discovery=True)


def _discovery_row(row):
 # Sitemap/archive listings need canonical titles and indexability, not image
 # work, score computation, local-time formatting or a duplicate article body.
 item=dict(row)
 if item.get('_discovery_ready'):return item
 source_text=item.get('bot_article') or item.get('bot_summary') or item.get('summary') or ''
 item['title']=_public_title(item.get('title'),_strip_promo_nav(source_text))
 item['summary']=_strip_promo_nav(item.get('bot_summary') or item.get('summary') or '')
 item['bot_summary']=item['summary']
 item['article']=_strip_promo_nav(source_text)
 item['category']=normalize_category(item.get('category'),item['title'],item['summary'])
 return item


@app.get("/api/seo-archive")
@app.get("/archive/")
def seo_archive():
 # Only genuinely index-eligible, available stories receive discovery links.
 raw=request.args.get("page","1")
 if not raw.isdigit() or len(raw)>5 or int(raw)<1:
  return Response("Not found",status=404)
 page=int(raw)
 try:
  stories=eligible_articles([_discovery_row(r) for r in _published_sitemap_rows()])
 except RuntimeError:
  return Response("Archive temporarily unavailable",status=503,headers={"Retry-After":"300"})
 # Avoid HTTP 503 for a public archive during a database outage.
 per_page=100
 start=(page-1)*per_page
 if start>=len(stories) and not (page==1 and not stories):return Response("Not found",status=404)
 shown=stories[start:start+per_page]
 canonical=SITE_ORIGIN+"/archive/"+("?page="+str(page) if page>1 else "")
 items=[]
 for item in shown:
  title=html.escape(str(item.get("title") or "Latest report"))
  href=html.escape(article_path(item),quote=True)
  source=html.escape(str(item.get("source_name") or "PoliticsHub.in"))
  category=html.escape(str(item.get("category") or "news").title())
  date=html.escape(str(item.get("published_at_iso") or item.get("published_at") or ""))
  summary=html.escape(str(item.get("bot_summary") or item.get("summary") or "")[:220])
  items.append('<li><article><a href="'+href+'"><h2>'+title+'</h2></a><p>'+category+' · '+source+' · '+date+'</p><p>'+summary+'</p></article></li>')
 pager=""
 if page==1:
  for story in STANDALONE_NEWS:
   items.insert(0,'<li><article><a href="'+html.escape(story["path"],quote=True)+'"><h2>'+html.escape(story["title"])+'</h2></a><p>India · PoliticsHub News Desk · '+html.escape(story["published_at"])+'</p><p>Dated report, with sources linked on the article page.</p></article></li>')
 if page>1:
  prev="/archive/" if page==2 else "/archive/?page="+str(page-1)
  pager+='<a href="'+prev+'">← Newer stories</a> '
 if start+per_page<len(stories):
  pager+='<a href="/archive/?page='+str(page+1)+'">Older stories →</a>'
 if not stories and page==1:
  items.append('<li><p>No additional long-form reports are currently available. Read our <a href="/guides/election-results.html">election verification guide</a> or visit <a href="/maharashtra/">Maharashtra coverage</a>.</p></li>')
 page_html='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>News Archive'+(" · Page "+str(page) if page>1 else "")+' — PoliticsHub.in</title><meta name="description" content="Browse the source-linked, published news reports from PoliticsHub.in."><link rel="canonical" href="'+html.escape(canonical,quote=True)+'"><link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/assets/polish.css?v=phui30"><script src="/assets/ui.js?v=phui30" defer></script></head><body><header id="hd"><div class="top"><a class="logo" href="/"><img src="/favicon.svg" alt="PoliticsHub.in"></a><nav><a href="/">Home</a> · <a href="/india/">India</a> · <a href="/politics/">Politics</a> · <a href="/world/">World</a></nav></div></header><main class="wrap" style="max-width:1000px;padding:38px 22px"><h1>News Archive</h1><p>Browse individual published reports. Every headline opens its dedicated article page.</p><ol style="list-style:none;padding:0">'+''.join(items)+'</ol><nav aria-label="Archive pages">'+pager+'</nav></main><footer><div class="wrap"><p>PoliticsHub.in · <a href="/">Home</a> · <a href="/editorial-policy.html">Editorial policy</a> · <a href="/contact.html">Contact</a></p></div></footer></body></html>'
 if not stories:
  page_html=page_html.replace("<head>","<head><meta name='robots' content='noindex,follow'>",1)
 return Response(page_html,mimetype="text/html",headers={"Cache-Control":"public,max-age=60,s-maxage=180"})

@app.get("/sitemap.xml")
def sitemap_index():
 from app.seo_indexing import sitemap_index_xml
 return Response(sitemap_index_xml(),mimetype="application/xml",headers={"Cache-Control":"public,max-age=300"})

@app.get("/static-sitemap.xml")
def static_sitemap():
 from app.seo_indexing import static_sitemap_xml
 return Response(static_sitemap_xml(),mimetype="application/xml",headers={"Cache-Control":"public,max-age=3600"})

@app.get("/api/seo-news-sitemap")
@app.get("/news-sitemap.xml")
def news_sitemap_first():
 return _news_sitemap_page(1)

@app.get("/api/seo-google-news")
@app.get("/google-news.xml")
def google_news_sitemap_page():
 rows=_published_sitemap_rows()
 selected=[_discovery_row(r) for r in rows]
 body=google_news_sitemap_xml(selected)
 return Response(body,mimetype="application/xml",headers={"Cache-Control":"public,max-age=300,s-maxage=300"})

@app.get("/news-sitemap-<int:page>.xml")
def news_sitemap_page(page):
 return _news_sitemap_page(page)

def _news_sitemap_page(page):
 if page<1:return Response("Not found",status=404)
 rows=_published_sitemap_rows()
 if not rows:
  return Response("Sitemap temporarily unavailable",status=503,headers={"Retry-After":"300"})
 # Build sitemap URLs from the same public headline representation served
 # on article pages. Long/cleaned headlines otherwise yield divergent slugs.
 selected=eligible_articles([_discovery_row(r) for r in rows])
 chunk=40000
 if (page-1)*chunk >= len(selected) and page!=1:
  return Response("Not found",status=404)
 xml=news_sitemap_xml(selected[(page-1)*chunk:page*chunk])
 if page==1:
  xml=xml.replace("</urlset>",standalone_sitemap_url_xml()+"</urlset>")
 return Response(xml,mimetype="application/xml",headers={"Cache-Control":"public,max-age=300,s-maxage=300"})

@app.get("/")
@app.get("/api/seo-home")
def seo_home():
 category=request.args.get("category","").lower().strip()
 if category:
  category=CATEGORY_SLUGS.get(category,category)
  if category in set(CATEGORY_SLUGS.values()): return redirect("/"+category+"/",code=301)
 return Response(_enhance_section_seo(_section_html("all"), "all"),mimetype="text/html",headers={"Cache-Control":"public,max-age=60,s-maxage=180"})

@app.get("/article.html")
def legacy_article():
 raw=request.args.get("id","").strip()
 if not raw.isdigit(): return redirect("/",code=301)
 row=_public_row_by_id(int(raw))
 if not row:return redirect("/",code=301)
 return redirect(SITE_ORIGIN+article_path(row),code=301)

@app.get("/home.html")
def legacy_home():
 return redirect("/",code=301)

# Explicit static routes for files that must never be normalized with a
# trailing slash by a proxy or catch-all route.
@app.get("/favicon.svg", strict_slashes=False)
def favicon():
 return send_from_directory(app.static_folder,"favicon.svg",max_age=86400)

@app.get("/manifest.webmanifest", strict_slashes=False)
def manifest():
 return send_from_directory(app.static_folder,"manifest.webmanifest",max_age=300)

@app.get("/service-worker.js", strict_slashes=False)
def service_worker():
 return send_from_directory(app.static_folder,"service-worker.js",max_age=0)

@app.get("/brand.svg", strict_slashes=False)
def brand():
 return send_from_directory(app.static_folder,"brand.svg",max_age=86400)

# Render web-service compatibility: serve remaining static assets/pages.

@app.post("/api/ai/translate")
def ai_translate():
    err=require_admin()
    if err:return err
    err=require_csrf()
    if err:return err
    body=request.get_json(silent=True) or {}
    text_value=str(body.get("text") or "").strip()
    language=str(body.get("target_language") or "").strip()
    if not text_value or language.lower() not in {"english","hindi","marathi"}:
        return jsonify({"error":"text and target_language (English/Hindi/Marathi) are required"}),400
    try:
        from app.phi4 import translate
        return jsonify({"ok":True,"provider":"microsoft_phi4","translation":translate(text_value,language)})
    except Exception as exc:
        return jsonify({"error":str(exc)[:500]}),503


@app.post("/api/ai/neutrality")
def ai_neutrality():
    err=require_admin()
    if err:return err
    err=require_csrf()
    if err:return err
    body=request.get_json(silent=True) or {}
    title=str(body.get("title") or "").strip()
    article=str(body.get("article") or "").strip()
    if not title or not article:return jsonify({"error":"title and article are required"}),400
    try:
        from app.phi4 import neutrality_check
        result=neutrality_check(title,article)
        return jsonify({"ok":True,"provider":"microsoft_phi4","result":result})
    except Exception as exc:
        return jsonify({"error":str(exc)[:500]}),503


@app.post("/api/ai/reel-script")
def ai_reel_script():
    err=require_admin()
    if err:return err
    err=require_csrf()
    if err:return err
    body=request.get_json(silent=True) or {}
    title=str(body.get("title") or "").strip()
    article=str(body.get("article") or "").strip()
    if not title or not article:return jsonify({"error":"title and article are required"}),400
    try:
        from app.phi4 import reel_script
        return jsonify({"ok":True,"provider":"microsoft_phi4","script":reel_script(title,article)})
    except Exception as exc:
        return jsonify({"error":str(exc)[:500]}),503


@app.post("/api/ai/assistant")
def ai_assistant():
    err=require_admin()
    if err:return err
    err=require_csrf()
    if err:return err
    body=request.get_json(silent=True) or {}
    instruction=str(body.get("instruction") or "").strip()
    context=str(body.get("context") or "").strip()
    if not instruction:return jsonify({"error":"instruction is required"}),400
    try:
        from app.phi4 import newsroom_assistant
        return jsonify({"ok":True,"provider":"microsoft_phi4","answer":newsroom_assistant(instruction,context)})
    except Exception as exc:
        return jsonify({"error":str(exc)[:500]}),503


@app.route("/<path:path>")
def _render_public(path):
 if path.startswith("api/"): return jsonify({"error":"not found"}),404
 if path in {"politics","india","world","business","technology","sports","entertainment","hindi"}: return redirect("/#/"+("c/"+path))
 return send_from_directory(app.static_folder,path)
