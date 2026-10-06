# Production deployment marker: deterministic newsroom + public source attribution.
# Controlled production release: public quality, attribution and image-safety gates enabled.
from __future__ import annotations

import json, os, re, secrets, time, html, io
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, session, send_from_directory, redirect, Response
from werkzeug.security import check_password_hash, generate_password_hash
from app.article_fetcher import enrich_source_text
from app.database import NewsDatabase
from app.models import NewsItem
from app.factcheck import run_cross_source_check
from app.newsroom import process_news, story_score, is_breaking, dedupe_story_rows, quality_headline, is_telegram_image
from app.worker import dispatch_worker
from app.phase_system import phase_analytics, cluster_stories, cluster_summary, train as train_agent
from app.reporting import operations_pdf
from app.advanced_ops import ensure_advanced_schema, live_dashboard, detailed_report, record_verification, audit_stage
from app.advanced_system import admin_snapshot, historical_analytics, event_timeline, ensure_schema as ensure_upgrade_schema

app=Flask(__name__, static_folder="../public", static_url_path="")
_secret=os.getenv("FLASK_SECRET_KEY") or os.getenv("ADMIN_TOKEN") or os.getenv("ADMIN_SETUP_KEY")
if not _secret:_secret=secrets.token_urlsafe(32)
app.secret_key=_secret
app.config["MAX_CONTENT_LENGTH"]=1*1024*1024
app.config.update(SESSION_COOKIE_NAME="__Host-politicshub_admin_session",SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE="Strict",SESSION_COOKIE_PATH="/",SESSION_COOKIE_REFRESH_EACH_REQUEST=False)
_LOGIN_WINDOW_SECONDS=300; _LOGIN_MAX_FAILURES=8; _SETUP_MAX_FAILURES=5; _login_failures={}


def _ensure_admin_users(database):
 database.conn.execute("CREATE TABLE IF NOT EXISTS admin_users (username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'owner',created_at TEXT NOT NULL)")
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


PUBLIC_BACKEND_ORIGIN=os.getenv("PUBLIC_BACKEND_ORIGIN","https://politicshub.onrender.com").rstrip("/")
_PUBLIC_API_TIMEOUT=8
_PUBLIC_RATE={}

def _public_rate_key():
 return (request.remote_addr or "unknown")[:128]

def _public_rate_allowed(limit=120,window=60):
 key=_public_rate_key(); now=time.time(); bucket=_PUBLIC_RATE.get(key)
 if not bucket or now-bucket[0]>=window:
  _PUBLIC_RATE[key]=[now,1]; return True
 if bucket[1]>=limit:return False
 bucket[1]+=1; return True

def _proxy_public(path):
 try:
  import requests
  query=request.query_string.decode("utf-8")
  url=PUBLIC_BACKEND_ORIGIN+path+(("?" + query) if query else "")
  response=requests.get(url,timeout=_PUBLIC_API_TIMEOUT,headers={"Accept":"application/json","X-PoliticsHub-Proxy":"1"})
  return app.response_class(response.content,status=response.status_code,content_type=response.headers.get("Content-Type","application/json"))
 except Exception as exc:
  print(f"Public backend proxy failed: {exc}")
  return None

def _rank_public(rows):
 items=[dict(r) for r in rows]
 for item in items:
  item["news_score"]=story_score(item.get("title",""),item.get("bot_summary") or item.get("summary") or "",item.get("category") or "general",item.get("source_name") or "")
  item["is_breaking"]=is_breaking(item.get("title",""),item.get("bot_summary") or item.get("summary") or "",item["news_score"])
 return dedupe_story_rows(items)
def _public_rows_for_section(category="all",limit=200):
 try:
  database=db()
  try:
   rows=[dict(x) for x in database.latest(max(limit*3,limit),category,"published")]
   return dedupe_story_rows(rows,threshold=0.78)[:limit]
  finally:database.close()
 except RuntimeError:
  try:
   import requests
   url=PUBLIC_BACKEND_ORIGIN+"/api/news?category="+requests.utils.quote(category)+"&limit="+str(limit)
   response=requests.get(url,timeout=_PUBLIC_API_TIMEOUT,headers={"Accept":"application/json","X-PoliticsHub-Proxy":"1"})
   return response.json() if response.ok and isinstance(response.json(),list) else []
  except Exception as exc: print(f"SSR section proxy failed: {exc}"); return []

def _section_html(category="all"):
 rows=_public_rows_for_section(category,40)
 label="Latest news" if category=="all" else str(category).title()+" news"
 canonical=SITE_ORIGIN+"/" if category=="all" else SITE_ORIGIN+"/"+category+"/"
 links=[]
 for row in rows:
  try:
   row=_publicize(row)
   title=html.escape(str(row.get("title") or "Untitled"))
   href=article_path(row)
   date=html.escape(str(row.get("published_at_site") or row.get("published_at") or ""))
   summary=html.escape(str(row.get("bot_summary") or row.get("summary") or "")[:220])
   links.append('<article><h2><a href="'+href+'">'+title+'</a></h2><p>'+summary+'</p><time>'+date+'</time></article>')
  except Exception: pass
 body="".join(links) or '<p class="msg">No stories are available in this section right now.</p>'
 return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(label)+' — PoliticsHub.in</title><meta name="description" content="'+html.escape(label)+' from PoliticsHub.in."><link rel="canonical" href="'+canonical+'"><meta property="og:type" content="website"><meta property="og:title" content="'+html.escape(label)+' — PoliticsHub.in"><meta property="og:image" content="'+SITE_ORIGIN+'/api/og-home"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="'+html.escape(label)+' — PoliticsHub.in"><meta name="twitter:image" content="'+SITE_ORIGIN+'/api/og-home"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533" crossorigin="anonymous"></script><link rel="icon" href="/favicon.svg"><link rel="manifest" href="/manifest.webmanifest"><link rel="stylesheet" href="/assets/site.css?v=phui8"></head><body><div id="prog"></div><header id="hd"><div class="top"><button class="ib burger" id="bg" aria-label="Open menu">☰</button><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a><nav class="main" id="nav" aria-label="Sections"><span id="ind" aria-hidden="true"></span></nav><div class="acts"><button class="ib" id="sbtn" aria-label="Search">⌕</button><a class="ib" href="/about.html" aria-label="About">i</a></div></div><div class="tick" id="tick" hidden><span class="tag">LIVE <i class="dot"></i></span><div class="tk" id="tk"></div><button class="ib" id="pz" aria-label="Pause ticker" aria-pressed="false">Ⅱ</button></div></header><div id="bd"></div><aside id="dr" aria-hidden="true"><button class="ib" id="dx" aria-label="Close menu">×</button><nav id="dl"></nav><div class="ft">PoliticsHub.in<br><span>What matters, clearly.</span></div></aside><div id="cv"></div><section id="sp" aria-hidden="true"><div class="sb"><form id="sf"><input id="si" type="search" autocomplete="off" placeholder="Search the full archive" aria-label="Search the full archive"><button class="ib" id="sx" type="button" aria-label="Close search">×</button></form><p id="sc" class="lbl" style="margin:18px 6px"></p><div id="sres"></div></div></section><main class="wrap"><div id="app"><div class="art"><div class="ah"><span class="lbl red">PoliticsHub.in</span><h1>'+html.escape(label)+'</h1><p class="dek">What matters, clearly.</p></div><section class="body">'+body+'</section></div></div></main><footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><div class="ser">What matters,<br>clearly.</div></div><div><h4>EXPLORE</h4><p><a href="/">Home</a></p><p><a href="/about.html">About</a></p><p><a href="/search.html">Search</a></p></div><div><h4>INFORMATION</h4><p><a href="/privacy.html">Privacy</a></p><p><a href="/cookies.html">Cookies</a></p><p><a href="/terms.html">Terms</a></p><p><a href="/settings.html">Settings</a></p><p><a href="/contact.html">Contact</a></p><p><small>© <span id="yr"></span> PoliticsHub.in</small></p></div></div></footer><script src="/assets/site.js?v=phui8"></script></body></html>'

def db():
 database=NewsDatabase(); _ensure_admin_users(database); _bootstrap_news_snapshot(database); return database

def admin_ok():
 if session.get("admin_user"):return True
 token=os.getenv("ADMIN_TOKEN",""); supplied=request.headers.get("X-Admin-Token",""); return bool(token and supplied and secrets.compare_digest(supplied,token))

def require_admin():return None if admin_ok() else (jsonify({"error":"admin authentication required"}),401)
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
 r=dict(row)
 if not admin_ok():
  # Public readers may see the originating source and its public article URL.
  # Internal moderation, Instagram state, hashes and processing fields stay private.
  for key in ("normalized_url","external_id","url_hash","title_hash","collected_at","fact_check_status","fact_check_notes","approved_at","instagram_status","instagram_media_id","instagram_error","instagram_published_at","instagram_attempts","instagram_last_attempt_at","instagram_next_retry_at","instagram_scheduled_at","instagram_queue_order","instagram_container_id","reel_cloudinary_public_id","instagram_selected","ai_summary","ai_article","published_at_site"):
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
  r["summary"]=_strip_promo_nav(dict(row).get("bot_summary") or dict(row).get("summary") or "")
  article_text=_strip_promo_nav(source_text)
  article_text=re.sub(r"(?:\n|\s)*Why it matters:\s*$","",article_text,flags=re.I).strip()
  r["article"]=article_text
  # Keep verified source images public; the frontend already handles missing images safely.
  r.pop("editorial_context",None)
  if "editorial_value" in r: r["editorial_value"]=bool(r.get("editorial_value"))
  if "source_count" in r: r["source_count"]=int(r.get("source_count") or 0)
 score=story_score(r.get("title",""),r.get("summary",""),r.get("category") or "general",r.get("source_name") or "")
 r["news_score"]=score; r["is_breaking"]=is_breaking(r.get("title",""),r.get("summary",""),score)
 return r


SITE_ORIGIN="https://www.politicshub.in"
EDITORIAL_DESK="PoliticsHub Editorial Desk"
EDITORIAL_EMAIL="politicshub.in@gmail.com"
CATEGORY_SLUGS={"general":"india","india":"india","world":"world","politics":"politics","business":"business","technology":"technology","sports":"sports","entertainment":"entertainment","science":"science","health":"health","hindi":"hindi"}

def _slugify(value):
 value=re.sub(r"[^a-z0-9]+","-",str(value or "").lower()).strip("-")
 return value[:110] or "story"

def article_path(row):
 category=str(row.get("category") or "general").lower()
 category=CATEGORY_SLUGS.get(category,"india")
 return f"/{category}/{int(row['id'])}-{_slugify(row.get('title'))}"

def _public_row_by_id(item_id):
 try:
  database=db()
  try:
   row=database.get_by_id(int(item_id),"published")
   if row:return _publicize(row)
  finally: database.close()
 except RuntimeError:
  try:
   import requests
   response=requests.get(PUBLIC_BACKEND_ORIGIN+"/api/news/"+str(int(item_id)),timeout=_PUBLIC_API_TIMEOUT,headers={"Accept":"application/json","X-PoliticsHub-Proxy":"1"})
   if response.ok:
    return response.json()
  except Exception as exc: print(f"SSR article proxy failed: {exc}")
 return None

def _article_html(row):
 row=dict(row); title=str(row.get("title") or "PoliticsHub.in"); category=str(row.get("category") or "India")
 canonical=SITE_ORIGIN+article_path(row)
 published=row.get("published_at_iso") or row.get("published_at_site") or row.get("published_at")
 modified=row.get("published_at_iso") or row.get("published_at_site") or row.get("published_at")
 summary=str(row.get("summary") or row.get("bot_summary") or "")[:300]
 body=str(row.get("article") or row.get("bot_article") or row.get("body") or summary)
 source=str(row.get("source_name") or "PoliticsHub.in")
 image=SITE_ORIGIN+"/api/og/"+str(row.get("id"))
 pub_iso=str(published or datetime.now(timezone.utc).isoformat())
 if pub_iso and not re.search(r"[+-]\d\d:\d\d|Z$",pub_iso): pub_iso=pub_iso+"Z"
 data={
  "@context":"https://schema.org","@type":"NewsArticle","headline":title,
  "description":summary,"image":[image],"datePublished":pub_iso,"dateModified":str(modified or pub_iso),
  "author":[{"@type":"Organization","name":EDITORIAL_DESK,"url":SITE_ORIGIN+"/author/politicshub-news-desk"}],
  "publisher":{"@type":"Organization","name":"PoliticsHub.in","url":SITE_ORIGIN},
  "mainEntityOfPage":{"@type":"WebPage","@id":canonical},"isAccessibleForFree":True
 }
 paras="".join(f"<p>{html.escape(p.strip())}</p>" for p in re.split(r"\n+",body) if p.strip())
 return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — PoliticsHub.in</title>
<meta name="description" content="{html.escape(summary[:160])}">
<link rel="canonical" href="{html.escape(canonical)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="PoliticsHub.in">
<meta property="og:title" content="{html.escape(title)}"><meta property="og:description" content="{html.escape(summary[:200])}">
<meta property="og:url" content="{html.escape(canonical)}"><meta property="og:image" content="{html.escape(image)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{html.escape(title)}"><meta name="twitter:description" content="{html.escape(summary[:200])}"><meta name="twitter:image" content="{html.escape(image)}">
<meta property="article:section" content="{html.escape(category)}"><meta property="article:published_time" content="{html.escape(pub_iso)}">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533" crossorigin="anonymous"></script><link rel="icon" href="/favicon.svg"><link rel="manifest" href="/manifest.webmanifest"><link rel="stylesheet" href="/assets/site.css?v=phui8">
<script type="application/ld+json">{json.dumps(data,ensure_ascii=False)}</script>
</head><body>
<header id="hd"><div class="top"><button class="ib burger" id="bg" aria-label="Open menu">☰</button><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a><div class="acts"><a class="ib" href="/" aria-label="Home">⌂</a><a class="ib" href="/about.html" aria-label="About">i</a></div></div></header>
<main class="wrap"><article class="art" data-k="{html.escape(category.lower())}">
<div class="ah"><span class="chip">{html.escape(category)}</span><h1>{html.escape(title)}</h1><p class="dek">{html.escape(summary)}</p>
<div class="by"><span>By <a href="/author/politicshub-news-desk">{EDITORIAL_DESK}</a></span><span>{html.escape(str(published or ""))}</span><span>{html.escape(source)}</span></div></div>
{"<div class='ahero'><img src='"+html.escape(str(row.get("image_url") or image))+"' alt='"+html.escape(title)+"' loading='eager'></div>" if row.get("image_url") else ""}
<div class="body">{paras}</div>
<div class="src"><strong>Source transparency:</strong> This is a source-linked brief prepared from the originating report. When multiple independent sources are available, PoliticsHub compares their reported details; otherwise no independent reporting claim is made.</div>
<div class="src">Source: {html.escape(source)}. {"<a href='"+html.escape(str(row.get("url")))+"' rel='nofollow noopener' target='_blank'>Read the original report</a>" if row.get("url") else ""}</div>
<div class="article-share"><span>SHARE</span><a href="https://wa.me/?text={html.escape(title)}%20{html.escape(canonical)}">WhatsApp</a><a href="https://t.me/share/url?url={html.escape(canonical)}&text={html.escape(title)}">Telegram</a><a href="https://www.facebook.com/sharer/sharer.php?u={html.escape(canonical)}">Facebook</a><a href="https://twitter.com/intent/tweet?text={html.escape(title)}&url={html.escape(canonical)}">X</a></div>
</article></main>
<footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><p class="ser">Source-linked news. Clearly.</p></div><div><h4>Navigate</h4><ul><li><a href="/">Home</a></li><li><a href="/about.html">About</a></li><li><a href="/editorial-policy.html">Editorial Policy</a></li><li><a href="/corrections.html">Corrections</a></li><li><a href="/contact.html">Contact</a></li><li><a href="/disclaimer.html">Disclaimer</a></li><li><a href="/privacy.html">Privacy</a></li><li><a href="/cookies.html">Cookies</a></li><li><a href="/terms.html">Terms</a></li><li><a href="/newsletter.html">Newsletter</a></li><li><a href="/settings.html">Settings</a></li><li><a href="/debug.html">System Status</a></li></ul></div><div><h4>Contact</h4><ul><li><a href="mailto:politicshub.in@gmail.com">politicshub.in@gmail.com</a></li></ul></div></div></footer>
<script src="/assets/site.js?v=phui8"></script>
</body></html>"""

def _og_image(item_id):
 row=_public_row_by_id(item_id)
 if not row:return None
 from PIL import Image, ImageDraw, ImageFont
 image=Image.new("RGB",(1200,630),(245,245,242)); draw=ImageDraw.Draw(image)
 try: font_big=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",54); font_small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",24)
 except Exception: font_big=ImageFont.load_default(); font_small=ImageFont.load_default()
 draw.rectangle((0,0,1200,18),fill=(200,16,46)); draw.text((70,65),"PoliticsHub.in",font=font_small,fill=(60,60,60))
 title=str(row.get("title") or "PoliticsHub.in")
 words=title.split(); lines=[]; line=""
 for word in words:
  test=(line+" "+word).strip()
  if draw.textlength(test,font=font_big)>1050 and line: lines.append(line);line=word
  else:line=test
 if line:lines.append(line)
 y=170
 for line in lines[:5]:
  draw.text((70,y),line,font=font_big,fill=(15,15,18)); y+=64
 draw.text((70,560),f"{str(row.get('category') or 'News')} · {EDITORIAL_DESK}",font=font_small,fill=(105,105,105))
 out=io.BytesIO();image.save(out,format="PNG",optimize=True);return out.getvalue()

def _editorial_page(title,lead,kind="page"):
 links=["Home","About","Editorial Policy","Corrections","Contact","Disclaimer","Privacy","Cookies","Terms","Newsletter","Settings","System Status"]
 hrefs={"Home":"/","About":"/about.html","Editorial Policy":"/editorial-policy.html","Corrections":"/corrections.html","Contact":"/contact.html","Disclaimer":"/disclaimer.html","Privacy":"/privacy.html","Cookies":"/cookies.html","Terms":"/terms.html","Newsletter":"/newsletter.html","Settings":"/settings.html","System Status":"/debug.html"}
 nav="<ul>"+"".join("<li><a href=\""+hrefs[x]+"\">"+html.escape(x)+"</a></li>" for x in links)+"</ul>"
 body="<p>PoliticsHub.in is a source-linked digital newsroom focused on politics, public affairs, India and the world.</p>" if kind=="author" else ""
 page='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+' — PoliticsHub.in</title><meta name="description" content="'+html.escape(lead[:160])+'"><link rel="canonical" href="'+SITE_ORIGIN+request.path+'"><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/assets/site.css?v=phui8"></head><body><header id="hd"><div class="top"><a class="logo" href="/"><img id="lg" src="/favicon.svg" alt="PoliticsHub.in"></a></div></header><main class="wrap"><article class="art"><div class="ah"><span class="lbl red">PoliticsHub.in</span><h1>'+html.escape(title)+'</h1><p class="dek">'+html.escape(lead)+'</p></div><div class="body">'+body+'</div></article></main><footer><div class="wrap"><div><img src="/favicon.svg" alt="PoliticsHub.in"><p class="ser">What matters, clearly.</p></div><div><h4>Navigate</h4>'+nav+'</div></div></footer></body></html>'
 return Response(page,mimetype="text/html")
def rows_json(rows,compact=False):
 out=[]
 for row in rows:
  if not (admin_ok() or row.get("status")=="published"):continue
  item=_publicize(row)
  if compact and admin_ok():
   item={k:item.get(k) for k in ("id","title","source_name","category","status","instagram_status","instagram_attempts","instagram_error","instagram_selected","instagram_scheduled_at","instagram_queue_order","fact_check_status","bot_summary","news_score","is_breaking","view_count")}
  out.append(item)
 return out
def users():
 try:return json.loads(os.getenv("ADMIN_USERS_JSON","{}"))
 except Exception:return {}
def _client_key():return (request.remote_addr or "unknown").strip()[:128]
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

@app.after_request
def security_headers(response):
 response.headers["X-Content-Type-Options"]="nosniff"
 response.headers["X-Frame-Options"]="DENY"
 response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
 response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=(), payment=(), usb=()"
 response.headers["Strict-Transport-Security"]="max-age=63072000; includeSubDomains; preload"
 response.headers["Content-Security-Policy"]="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' https://pagead2.googlesyndication.com https://www.google.com https://www.googletagmanager.com https://www.googleadservices.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https:; media-src 'self' https:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://www.google.com https://www.googleadservices.com; frame-src 'self' https://googleads.g.doubleclick.net https://tpc.googlesyndication.com; worker-src 'self'; upgrade-insecure-requests"
 response.headers["Cross-Origin-Opener-Policy"]="same-origin"
 response.headers["Cross-Origin-Resource-Policy"]="same-origin"
 response.headers["X-Permitted-Cross-Domain-Policies"]="none"
 if request.path.startswith("/api/admin") or (request.path.startswith("/api/") and admin_ok()):
  response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
 elif request.method=="GET" and request.path.startswith("/api/"):
  response.headers["Cache-Control"]="public, max-age=30, s-maxage=30, stale-while-revalidate=60"
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
 database=db()
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
  session.clear()
  session["admin_user"]=username
  session["admin_role"]=role or "owner"
  session["csrf_token"]=secrets.token_urlsafe(32)
  return jsonify({"ok":True,"username":username,"role":role or "owner","csrf_token":session["csrf_token"]})
 finally:
  database.close()

@app.before_request
def canonical_host():
 host=(request.host or "").split(":")[0].lower()
 if host=="politicshub.in": return redirect("https://www.politicshub.in"+request.full_path,code=301)

@app.get("/robots.txt")
def robots():
 return app.response_class("User-agent: *\nAllow: /\nAllow: /api/\nAllow: /api/news\nAllow: /ads.txt\nDisallow: /admin/\nDisallow: /admin.html\nDisallow: /admin.js\nDisallow: /newsroom-console-8x4m7k2q.html\nSitemap: https://www.politicshub.in/sitemap.xml\nSitemap: https://www.politicshub.in/news-sitemap.xml\n",mimetype="text/plain")

@app.get("/api/og-home")
def og_home():
 from PIL import Image, ImageDraw, ImageFont
 image=Image.new("RGB",(1200,630),(245,245,242));draw=ImageDraw.Draw(image)
 try: font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",72); small=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",28)
 except Exception: font=ImageFont.load_default();small=ImageFont.load_default()
 draw.rectangle((0,0,1200,18),fill=(200,16,46));draw.text((70,70),"PoliticsHub.in",font=small,fill=(70,70,70));draw.text((70,190),"What matters, clearly.",font=font,fill=(15,15,18));draw.text((70,520),"Source-linked news · Politics · India · World",font=small,fill=(105,105,105))
 out=io.BytesIO();image.save(out,format="PNG",optimize=True);return Response(out.getvalue(),mimetype="image/png",headers={"Cache-Control":"public, max-age=86400, s-maxage=86400"})

@app.get("/api/og/<int:item_id>")
def og_image(item_id):
 payload=_og_image(item_id)
 if not payload:return jsonify({"error":"not found"}),404
 return Response(payload,mimetype="image/png",headers={"Cache-Control":"public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800"})

@app.get("/api/newsletter")
def newsletter_status(): return jsonify({"ok":True,"available":True})

@app.post("/api/newsletter")
def newsletter_subscribe():
 if not _public_rate_allowed(20,3600):return jsonify({"error":"too many requests"}),429
 body=request.get_json(silent=True) or request.form.to_dict() or {}; email=str(body.get("email","")).strip().lower()
 if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",email):return jsonify({"error":"Enter a valid email address"}),400
 try:
  database=db()
  try: database.subscribe_newsletter(email); return jsonify({"ok":True,"message":"You are on the PoliticsHub newsletter list."})
  finally: database.close()
 except RuntimeError:
  try:
   import requests
   response=requests.post(PUBLIC_BACKEND_ORIGIN+"/api/newsletter",json={"email":email},timeout=_PUBLIC_API_TIMEOUT,headers={"Accept":"application/json","X-PoliticsHub-Proxy":"1"})
   return app.response_class(response.content,status=response.status_code,content_type=response.headers.get("Content-Type","application/json"))
  except Exception: return jsonify({"error":"newsletter service unavailable"}),503

@app.get("/<category>/")
def seo_section(category):
 category=category.lower().strip()
 if category not in set(CATEGORY_SLUGS.values()): return jsonify({"error":"not found"}),404
 return Response(_section_html(category if category!="india" or category in CATEGORY_SLUGS else "all"),mimetype="text/html")

@app.get("/author/politicshub-news-desk")
def author_page(): return _editorial_page("PoliticsHub News Desk","The PoliticsHub Editorial Desk publishes and edits newsroom stories, source links and public corrections.","author")

@app.get("/<category>/<int:item_id>-<slug>")
def seo_article(category,item_id,slug):
 row=_public_row_by_id(item_id)
 if not row:return jsonify({"error":"not found"}),404
 canonical_path=article_path(row); requested=f"/{category}/{item_id}-{slug}"
 if requested.rstrip("/")!=canonical_path.rstrip("/"):return redirect(SITE_ORIGIN+canonical_path,code=301)
 try:
  database=db()
  try: database.increment_view(item_id,datetime.now(timezone.utc).isoformat())
  finally: database.close()
 except Exception as exc: print(f"view counter skipped: {exc}")
 return Response(_article_html(row),mimetype="text/html")

@app.post("/api/admin/logout")
def logout():
 err=require_csrf()
 if err:return err
 session.clear(); return jsonify({"ok":True})

@app.get("/api/admin/me")
def me():return jsonify({"authenticated":bool(session.get("admin_user")),"username":session.get("admin_user"),"role":session.get("admin_role"),"csrf_token":session.get("csrf_token") if session.get("admin_user") else None})

@app.get("/api/health")
def health():
 database=db()
 try:return jsonify({"ok":True})
 finally:database.close()

@app.get("/api/news")
def news():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 category=request.args.get("category","all").lower().strip(); status=request.args.get("status","published"); review=request.args.get("review_status","all"); ig=request.args.get("instagram_status","all"); search=request.args.get("search"); compact=request.args.get("compact","0")=="1"
 if category!="all" and category not in {"general","india","world","politics","business","technology","sports","entertainment","science","health","hindi"}:return jsonify({"error":"invalid category"}),400
 if search is not None: search=str(search).strip()[:120]
 try:limit=min(max(int(request.args.get("limit","200")),1),200)
 except ValueError:limit=100
 if not admin_ok():status,review,ig="published","all","all"
 try:database=db()
 except Exception as exc:
  print(f"News DB unavailable; serving snapshot: {exc}")
  try:
   path=Path(app.static_folder or "public") / "news-data.json"
   payload=json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
   rows=[dict(x) for x in payload if isinstance(x,dict)]
   if category!="all": rows=[x for x in rows if str(x.get("category") or "general").lower()==category]
   if search:
    q=search.lower()
    rows=[x for x in rows if q in str(x.get("title") or "").lower() or q in str(x.get("summary") or x.get("bot_summary") or "").lower()]
   rows=_rank_public(rows)
   rows=dedupe_story_rows(rows,threshold=0.78)
   return jsonify(rows_json(rows[:limit],compact=compact))
  except Exception as snapshot_exc:
   print(f"News snapshot fallback failed: {snapshot_exc}")
   return jsonify({"error":"news backend unavailable"}),503
 try:
  rows=_rank_public(database.latest(max(limit*6,limit),category,status,search,review,ig))
  rows=dedupe_story_rows(rows,threshold=0.78)
  return jsonify(rows_json(rows[:limit],compact=compact))
 finally:database.close()

@app.get("/api/search")
def public_search():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 q=str(request.args.get("q","")).strip()[:120]
 if len(q)<2:return jsonify([])
 try:limit=min(max(int(request.args.get("limit","30")),1),50)
 except ValueError:limit=30
 try:database=db()
 except RuntimeError:
  proxied=_proxy_public("/api/news")
  return proxied or (jsonify({"error":"news backend unavailable"}),503)
 try:
  rows=_rank_public(database.latest(min(limit*8,400),"all","published",q))
  rows=dedupe_story_rows(rows,threshold=0.78)
  return jsonify(rows_json(rows[:limit]))
 finally:database.close()

@app.get("/api/trending")
def trending():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 try:limit=min(max(int(request.args.get("limit","10")),1),30)
 except ValueError:limit=10
 try:database=db()
 except RuntimeError:
  proxied=_proxy_public("/api/news")
  return proxied or (jsonify({"error":"news backend unavailable"}),503)
 try:return jsonify(rows_json(_rank_public(database.trending(limit*2))[:limit]))
 finally:database.close()

@app.get("/api/breaking")
def breaking():
 if not _public_rate_allowed():return jsonify({"error":"rate limit exceeded"}),429
 try:database=db()
 except RuntimeError:
  proxied=_proxy_public("/api/news")
  return proxied or (jsonify({"error":"news backend unavailable"}),503)
 try:
  rows=_rank_public(database.latest(100,"all","published"))
  return jsonify(rows_json([r for r in rows if r.get("is_breaking")][:12]))
 finally:database.close()

@app.post("/api/news/<int:item_id>/view")
def article_view(item_id):
 if not _public_rate_allowed(60,60):return jsonify({"error":"rate limit exceeded"}),429
 try:database=db()
 except RuntimeError:return jsonify({"ok":False,"tracked":False}),200
 try:
  row=database.get_by_id(item_id,"published")
  if not row:return jsonify({"error":"not found"}),404
  database.increment_view(item_id); return jsonify({"ok":True,"tracked":True})
 finally:database.close()

@app.get("/api/news/<int:item_id>")
def article(item_id):
 try:database=db()
 except RuntimeError:
  proxied=_proxy_public("/api/news/"+str(item_id))
  return proxied or (jsonify({"error":"news backend unavailable"}),503)
 try:
  row=database.get_by_id(item_id,"all")
  if not row or (row["status"]!="published" and not admin_ok()):return jsonify({"error":"not found"}),404
  return jsonify(_publicize(row))
 finally:database.close()

@app.get("/api/stats")
def stats():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds(); return jsonify({"total":database.count(),"pending":database.count_status("pending"),"review_needed":database.count_status("published","needs_review"),"published":database.count_status("published"),"instagram_failed":database.count_status("published",None,"failed"),"instagram_today":database.instagram_daily_count(a,b),"instagram_limit":int(settings.get("instagram_daily_limit","5")),"instagram_interval_minutes":int(settings.get("instagram_interval_minutes","0")),"instagram_enabled":settings.get("instagram_enabled","true")=="true","instagram_paused":settings.get("instagram_paused","false")=="true","instagram_priority_id":settings.get("instagram_priority_id",""),"website_enabled":settings.get("website_enabled","true")=="true"})
 finally:database.close()


@app.get("/api/admin/dashboard")
def admin_dashboard():
 err=require_admin()
 if err:return err
 database=db()
 try:
  settings=database.get_settings(); a,b=_india_day_bounds();
  payload={"settings":settings,"stats":{"total":database.count(),"pending":database.count_status("pending"),"review_needed":database.count_status("published","needs_review"),"published":database.count_status("published"),"instagram_failed":database.count_status("published",None,"failed"),"instagram_today":database.instagram_daily_count(a,b),"instagram_limit":int(settings.get("instagram_daily_limit","5")),"instagram_interval_minutes":int(settings.get("instagram_interval_minutes","0")),"instagram_enabled":settings.get("instagram_enabled","true")=="true","instagram_paused":settings.get("instagram_paused","false")=="true","instagram_priority_id":settings.get("instagram_priority_id",""),"website_enabled":settings.get("website_enabled","true")=="true"}, "activity":rows_json(database.recent_activity(20))}
  payload["settings"]["instagram_today"]=str(payload["stats"]["instagram_today"]); payload["settings"]["instagram_last_published_at"]=database.instagram_last_published_at() or ""
  return jsonify(payload)
 finally:database.close()

@app.get("/api/admin/health")
def admin_health():
 err=require_admin()
 if err:return err
 database=db()
 try:
  s=database.get_settings(); worker_ready=bool(os.getenv("WORKFLOW_TOKEN", "").strip() or os.getenv("GITHUB_WORKFLOW_TOKEN", "").strip()); instagram_marker=os.getenv("INSTAGRAM_WORKER_CONFIGURED", "").strip().lower()=="true"; return jsonify({"ok":True,"database":"connected","instagram":{"configured":bool(worker_ready or instagram_marker or os.getenv("META_ACCESS_TOKEN", "").strip()),"credentials_source":"github_actions" if worker_ready and not os.getenv("META_ACCESS_TOKEN", "").strip() else ("vercel" if os.getenv("META_ACCESS_TOKEN", "").strip() else "marker"),"enabled":s.get("instagram_enabled","true")=="true","paused":s.get("instagram_paused","false")=="true"},"worker_dispatch_configured":worker_ready,"website_enabled":s.get("website_enabled","true")=="true","news_count":database.count()})
 finally:database.close()

@app.get("/api/admin/activity")
def admin_activity():
 err=require_admin()
 if err:return err
 database=db()
 try:return jsonify([dict(r) for r in database.recent_activity(request.args.get("limit",50))])
 finally:database.close()

@app.get("/api/admin/instagram/analytics")
def instagram_analytics():
 err=require_admin()
 if err:return err
 database=db()
 try:
  now=datetime.now(timezone.utc); start=now-timedelta(days=7); rows=[dict(r) for r in database.latest(500,"all","published")]; published=[r for r in rows if r.get("instagram_status")=="published"]
  daily={};
  for row in published:
   raw=row.get("instagram_published_at")
   if raw:
    try:day=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat(); daily[day]=daily.get(day,0)+1
    except ValueError:pass
  recent=[{"id":r["id"],"title":r["title"],"published_at":r.get("instagram_published_at"),"media_id":r.get("instagram_media_id")} for r in published[:20]]
  return jsonify({"last_7_days":{k:v for k,v in daily.items() if k>=start.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()},"total_published":len(published),"failed":len([r for r in rows if r.get("instagram_status")=="failed"]),"processing":len([r for r in rows if r.get("instagram_status")=="processing"]),"queued":len([r for r in rows if r.get("instagram_status")=="pending" and int(r.get("instagram_selected") or 0)==1]),"recent":recent})
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
  cluster_stories(database,250)
  with __import__("app.phase_system",fromlist=["run"]).run(database,"reporting","generate_operations_report"):
   ops=phase_analytics(database,7)
  recent_errors=[dict(r) for r in database.conn.execute("SELECT agent_id,operation,error,started_at FROM ph_agent_runs WHERE status='failed' ORDER BY id DESC LIMIT 20").fetchall()]
  # Instagram failures are stored on news_items as well as agent telemetry. Surface them
  # in the Command Center so a failed Reel never looks like a silent queue stall.
  instagram_errors=[dict(r) for r in database.conn.execute("SELECT id,title,instagram_error,instagram_status,instagram_attempts,instagram_last_attempt_at FROM news_items WHERE instagram_error IS NOT NULL AND instagram_error <> '' ORDER BY id DESC LIMIT 20").fetchall()]
  for item in instagram_errors:
   recent_errors.append({
    "agent_id":"instagram",
    "operation":"publish_reel",
    "error":f"#{item.get('id')} {item.get('title')}: {item.get('instagram_error')}",
    "started_at":item.get("instagram_last_attempt_at") or ""
   })
  recent_errors=recent_errors[-20:]
  clusters=cluster_summary(database)
  total=database.count()
  published=len(database.latest(1000,"all","published"))
  published_rows=[dict(r) for r in database.latest(1000,"all","published")]
  with_article=len([r for r in published_rows if r.get("bot_article")])
  images=len([r for r in published_rows if r.get("image_url")])
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
 try:
  settings=database.get_settings(); a,b=_india_day_bounds(); settings["instagram_today"]=str(database.instagram_daily_count(a,b)); settings["instagram_last_published_at"]=database.instagram_last_published_at() or ""; return jsonify(settings)
 finally:database.close()

@app.post("/api/admin/settings")
def save_settings():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; values={}
 for key in ("instagram_enabled","website_enabled","instagram_paused"):
  if key in body:values[key]="true" if bool(body[key]) else "false"
 for key,maximum in (("instagram_daily_limit",100),("instagram_interval_minutes",1440)):
  if key in body:
   try:value=int(body[key])
   except (TypeError,ValueError):return jsonify({"error":f"{key} must be a number"}),400
   if value<0 or value>maximum:return jsonify({"error":f"{key} is out of range"}),400
   values[key]=str(value)
 if "instagram_selection_mode" in body:
  mode=str(body["instagram_selection_mode"]).lower()
  if mode not in {"auto","manual"}:return jsonify({"error":"selection mode must be auto or manual"}),400
  values["instagram_selection_mode"]=mode
 database=db()
 try:database.set_settings(values); settings_now=database.get_settings(); log_admin(database,"settings.update",None,",".join(values.keys()))
 finally:database.close()
 dispatch=dispatch_worker() if any(k.startswith("instagram_") for k in values) else None; payload={"ok":True,"settings":settings_now}
 if dispatch is not None:payload.update({"worker_dispatched":dispatch.get("ok",False),"worker_dispatch":dispatch})
 return jsonify(payload)

def change(item_id,status=None,**extra):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  fields=dict(extra); 
  if status is not None:fields["status"]=status
  database.update(item_id,**fields); log_admin(database,"news.update",item_id,",".join(fields.keys())); return jsonify({"ok":True,**fields})
 finally:database.close()

@app.post("/api/news/<int:item_id>/approve")
def approve(item_id):return change(item_id,fact_check_status="reviewed",approved_at=datetime.now(timezone.utc).isoformat())
@app.post("/api/news/<int:item_id>/reject")
def reject(item_id):return change(item_id,status="rejected",instagram_selected=0)
@app.post("/api/news/<int:item_id>/publish")
def publish(item_id):return change(item_id,status="published",published_at_site=datetime.now(timezone.utc).isoformat())

@app.post("/api/news/<int:item_id>/edit")
def edit_news(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; fields={k:str(body[k] or "").strip() for k in ("title","summary","category","image_url","bot_summary","bot_article") if k in body}
 if not fields:return jsonify({"error":"no editable fields supplied"}),400
 if "title" in fields and not fields["title"]:return jsonify({"error":"title cannot be empty"}),400
 database=db()
 try:database.update(item_id,**fields); log_admin(database,"news.edit",item_id,",".join(fields.keys())); return jsonify({"ok":True,"fields":fields})
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

@app.post("/api/news/<int:item_id>/instagram/queue")
def instagram_queue(item_id):
 result=change(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_queue_order=0,instagram_scheduled_at=None)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)
@app.post("/api/news/<int:item_id>/instagram/unqueue")
def instagram_unqueue(item_id):return change(item_id,instagram_selected=0)
@app.post("/api/news/<int:item_id>/instagram/retry")
def instagram_retry(item_id):
 result=change(item_id,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_selected=1)
 if isinstance(result,tuple):return result
 dispatch=dispatch_worker(); payload=result.get_json() or {}; payload["worker_dispatched"]=dispatch.get("ok",False); payload["worker_dispatch"]=dispatch; return jsonify(payload)

@app.post("/api/admin/instagram/bulk")
def instagram_bulk():
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; ids=[]; action=str(body.get("action","")).lower()
 for value in body.get("ids",[]):
  try: ids.append(int(value))
  except (TypeError,ValueError): pass
 ids=list(dict.fromkeys(ids))[:100]
 if action not in {"queue","unqueue","retry","cancel_schedule"}:return jsonify({"error":"unsupported bulk action"}),400
 database=db(); changed=0
 try:
  for item_id in ids:
   row=(dict(database.get_by_id(item_id,"all")) if database.get_by_id(item_id,"all") else None)
   if not row:continue
   if action=="queue":
    order=database.next_instagram_queue_order(); database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_scheduled_at=None,instagram_queue_order=order)
   elif action=="unqueue":database.update(item_id,instagram_selected=0)
   elif action=="retry":database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
   elif action=="cancel_schedule":database.update(item_id,instagram_scheduled_at=None)
   changed+=1
  log_admin(database,"instagram.bulk",None,f"{action}:{changed}")
 finally:database.close()
 dispatch=dispatch_worker() if action in {"queue","retry"} else {"ok":False,"configured":False}
 return jsonify({"ok":True,"changed":changed,"worker_dispatched":dispatch.get("ok",False)})

@app.post("/api/news/<int:item_id>/instagram/publish-now")
def instagram_publish_now(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  row=(dict(database.get_by_id(item_id,"published")) if database.get_by_id(item_id,"published") else None)
  if not row:return jsonify({"error":"published story not found"}),404
  if not row.get("bot_article") or not row.get("bot_summary"):
   source=enrich_source_text(row.get("title") or "",row.get("summary") or "",row.get("url") or ""); material=source.get("text") or row.get("summary") or row.get("title") or ""; packets=_editorial_source_packets(database,row); result=process_news(row.get("title") or "",material,row.get("category") or "general",source_materials=packets)
   if not result:return jsonify({"error":"story could not be processed by the newsroom bot"}),422
   fields={"title":result["headline"],"summary":result["summary"],"bot_summary":result["summary"],"bot_article":result["article"],"editorial_context":result.get("editorial_context") or "", "editorial_value":1 if result.get("editorial_value") else 0, "source_count":int(result.get("source_count") or 0)}
   if source.get("image_url") and not row.get("image_url"):fields["image_url"]=source["image_url"]
   database.update(item_id,**fields); row.update(fields); log_admin(database,"news.process",item_id,"auto before Instagram")
  if row.get("instagram_status")=="published":return jsonify({"error":"already published to Instagram"}),409
  database.set_settings({"instagram_priority_id":str(item_id),"instagram_paused":"false"}); database.update(item_id,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None,instagram_scheduled_at=None); log_admin(database,"instagram.priority",item_id,"post_now")
 finally:database.close()
 dispatch=dispatch_worker(); return jsonify({"ok":True,"priority_id":item_id,"queue_paused":True,"worker_dispatched":dispatch.get("ok",False),"worker_dispatch":dispatch})

@app.post("/api/news/<int:item_id>/instagram/schedule")
def instagram_schedule(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; raw=str(body.get("scheduled_at","")).strip()
 if raw:
  try:due=datetime.fromisoformat(raw.replace("Z","+00:00")); due=due if due.tzinfo else due.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
  except ValueError:return jsonify({"error":"invalid scheduled_at; use ISO date/time"}),400
  if due.astimezone(timezone.utc)<=datetime.now(timezone.utc):return jsonify({"error":"scheduled time must be in the future"}),400
  value=due.astimezone(timezone.utc).isoformat()
 else:value=None
 database=db()
 try:
  database.update(item_id,instagram_scheduled_at=value,instagram_selected=1,instagram_status="pending",instagram_error=None,instagram_next_retry_at=None)
  log_admin(database,"instagram.schedule",item_id,value or "cleared")
  return jsonify({"ok":True,"scheduled_at":value})
 finally:database.close()

@app.post("/api/news/<int:item_id>/instagram/order")
def instagram_order(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 body=request.get_json(silent=True) or {}; direction=str(body.get("direction","")).lower()
 if direction not in {"up","down"}:return jsonify({"error":"direction must be up or down"}),400
 database=db()
 try:
  rows=[dict(r) for r in database.latest(200,"all","published",None,"all","pending") if int(r.get("instagram_selected") or 0)==1]
  rows.sort(key=lambda r:(int(r.get("instagram_queue_order") or 0) if int(r.get("instagram_queue_order") or 0)>0 else 10**9,-int(r["id"])))
  index=next((i for i,r in enumerate(rows) if int(r["id"])==item_id),-1)
  target=index-1 if direction=="up" else index+1
  if index<0 or target<0 or target>=len(rows):return jsonify({"ok":True,"moved":False})
  a,b=rows[index],rows[target]; ao=int(a.get("instagram_queue_order") or 0); bo=int(b.get("instagram_queue_order") or 0)
  if ao<=0:ao=database.next_instagram_queue_order()
  if bo<=0:bo=max(1,ao-1)
  database.update(int(a["id"]),instagram_queue_order=bo); database.update(int(b["id"]),instagram_queue_order=ao); log_admin(database,"instagram.reorder",item_id,direction); return jsonify({"ok":True,"moved":True})
 finally:database.close()

@app.post("/api/news/<int:item_id>/instagram/cancel-priority")
def instagram_cancel_priority(item_id):
 err=require_admin()
 if err:return err
 err=require_csrf()
 if err:return err
 database=db()
 try:
  if str(database.get_settings().get("instagram_priority_id",""))!=str(item_id):return jsonify({"error":"this story is not the active priority"}),409
  database.set_settings({"instagram_priority_id":"","instagram_paused":"false"}); log_admin(database,"instagram.priority.cancel",item_id); return jsonify({"ok":True})
 finally:database.close()

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
 urls=["/","/about.html","/contact.html","/editorial-policy.html","/corrections.html","/privacy.html","/cookies.html","/terms.html","/disclaimer.html","/newsletter.html"]
 body="".join("<url><loc>"+_xml_escape(SITE_ORIGIN+p)+"</loc></url>" for p in urls)
 return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"+body+"</urlset>"


def _published_sitemap_rows():
 database=db()
 try:
  rows=database.conn.execute("SELECT id,title,category,published_at_site,published_at FROM news_items WHERE status='published' ORDER BY COALESCE(published_at_site,published_at) DESC,id DESC").fetchall()
  return [dict(r) for r in rows]
 finally:
  database.close()


@app.get("/sitemap.xml")
def sitemap_index():
 try:
  rows=_published_sitemap_rows()
  chunk=45000
  pages=max(1,(len(rows)+chunk-1)//chunk)
  body='<sitemap><loc>'+_xml_escape(SITE_ORIGIN+'/static-sitemap.xml')+'</loc></sitemap>'
  body+=''.join('<sitemap><loc>'+_xml_escape(SITE_ORIGIN+('/news-sitemap.xml' if i==1 else '/news-sitemap-'+str(i)+'.xml'))+'</loc></sitemap>' for i in range(1,pages+1))
  xml='<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+body+'</sitemapindex>'
  return Response(xml,mimetype="application/xml",headers={"Cache-Control":"public,max-age=300"})
 except Exception as exc:
  print(f"Sitemap index failed: {exc}")
  return Response('<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>'+_xml_escape(SITE_ORIGIN+'/static-sitemap.xml')+'</loc></sitemap><sitemap><loc>'+_xml_escape(SITE_ORIGIN+'/news-sitemap.xml')+'</loc></sitemap></sitemapindex>',mimetype="application/xml",headers={"Cache-Control":"public,max-age=300"})


@app.get("/static-sitemap.xml")
def static_sitemap():
 return Response(_sitemap_static_xml(),mimetype="application/xml",headers={"Cache-Control":"public,max-age=3600"})


@app.get("/news-sitemap.xml")
def news_sitemap_first():
 return _news_sitemap_page(1)


@app.get("/news-sitemap-<int:page>.xml")
def news_sitemap_page(page):
 return _news_sitemap_page(page)


def _news_sitemap_page(page):
 if page<1:return Response("Not found",status=404)
 try:
  rows=_published_sitemap_rows(); chunk=45000; start=(page-1)*chunk
  if start>=len(rows):return Response("Not found",status=404)
  selected=rows[start:start+chunk]; items=[]
  for row in selected:
   url=article_path(row)
   stamp=row.get("published_at_site") or row.get("published_at")
   item='<url><loc>'+_xml_escape(SITE_ORIGIN+url)+'</loc>'
   if stamp:item+='<lastmod>'+_xml_escape(str(stamp))+'</lastmod>'
   item+='</url>'; items.append(item)
  xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(items)+'</urlset>'
  return Response(xml,mimetype="application/xml",headers={"Cache-Control":"public,max-age=300"})
 except Exception as exc:
  print(f"News sitemap failed: {exc}")
  return Response("Sitemap unavailable",status=503)


@app.get("/")
def seo_home():
 category=request.args.get("category","").lower().strip()
 if category:
  category=CATEGORY_SLUGS.get(category,category)
  if category in set(CATEGORY_SLUGS.values()): return redirect("/"+category+"/",code=301)
 return Response(_section_html("all"),mimetype="text/html")

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
 if path in {"politics","india","world","business","technology","sports","entertainment","hindi"}: return Response(_section_html(path),mimetype="text/html")
 return send_from_directory(app.static_folder,path)
