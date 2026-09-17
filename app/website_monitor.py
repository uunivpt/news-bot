from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import NewsItem

logger = logging.getLogger(__name__)
HEADERS={"User-Agent":"NewsBot/3.0 (+public-news-monitor; contact=admin)","Accept":"text/html,application/xhtml+xml"}
URL_RE=re.compile(r"https?://[^\s<>\"']+",re.I)
DATE_RE=re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
BOILERPLATE_RE=re.compile(r"cookie|privacy policy|terms of use|subscribe|sign in|log in|advertisement|newsletter|follow us|share this|read more",re.I)

def _clean(value):return re.sub(r"\s+"," ",value or "").strip()
def _same_host(url,allowed_hosts):
 host=(urlparse(url).hostname or "").lower(); return host in allowed_hosts or any(host.endswith("."+item) for item in allowed_hosts)
def _allowed_path(url,prefixes):
 if not prefixes:return True
 path=urlparse(url).path or "/"; return any(path.startswith(prefix) for prefix in prefixes)
def _absolute(base,href):
 href=(href or "").strip()
 if not href or href.startswith(("#","javascript:","mailto:","tel:")):return None
 url=urljoin(base,href); parsed=urlparse(url)
 if parsed.scheme not in {"http","https"} or not parsed.netloc:return None
 return url.split("#",1)[0]
def _metadata(soup,*names):
 for name in names:
  node=soup.find("meta",attrs={"property":name}) or soup.find("meta",attrs={"name":name})
  if node and node.get("content"):return _clean(str(node["content"]))
 return None
def _parse_date(soup):
 node=soup.find("time")
 if node:
  value=node.get("datetime") or node.get_text(" ",strip=True)
  if value:return _clean(value)
 for attrs in ({"property":"article:published_time"},{"name":"date"},{"name":"pubdate"}):
  node=soup.find("meta",attrs=attrs)
  if node and node.get("content"):return _clean(str(node["content"]))
 return None
def _article_text(soup):
 for node in soup(["script","style","noscript","svg","nav","footer","form","aside"]):node.decompose()
 candidates=[]; selectors=("article","main",'[role="main"]',".article-body",".article-content",".story-body",".story-content",".entry-content",".press-release",".release-body")
 for selector in selectors:
  for node in soup.select(selector):
   lines=[]
   for child in node.find_all(["p","h2","h3","li"]):
    text=_clean(child.get_text(" ",strip=True))
    if len(text)>=35 and not BOILERPLATE_RE.search(text):lines.append(text)
   text="\n".join(lines)
   if len(text)>=180:candidates.append(text)
 if not candidates:
  lines=[]
  for node in soup.find_all(["p","h2","h3"]):
   text=_clean(node.get_text(" ",strip=True))
   if len(text)>=45 and not BOILERPLATE_RE.search(text):lines.append(text)
  candidates.append("\n".join(lines))
 return max(candidates,key=len,default="")[:24000].strip()
def _fetch(url,timeout=12):
 try:
  response=requests.get(url,headers=HEADERS,timeout=timeout,allow_redirects=True); response.raise_for_status()
  if "html" not in (response.headers.get("content-type") or "").lower():return None
  return response.url,BeautifulSoup(response.text[:4_000_000],"html.parser")
 except requests.RequestException as exc:logger.warning("Website fetch failed %s: %s",url,exc); return None
def collect_website(source):
 if not source.get("collection_allowed",True):return []
 seeds=source.get("sections") or [source.get("url")]; seeds=[s for s in seeds if isinstance(s,str) and s.startswith(("http://","https://"))]
 if not seeds:return []
 allowed_hosts={str(h).lower().strip() for h in source.get("allowed_hosts",[]) if h}
 if not allowed_hosts:allowed_hosts={(urlparse(seeds[0]).hostname or "").lower()}
 prefixes=[str(p) for p in source.get("article_path_prefixes",[]) if p]; max_links=min(max(int(source.get("max_links",40)),1),200); timeout=min(max(int(source.get("timeout_seconds",12)),3),30)
 candidates=[]; seen=set()
 for seed in seeds:
  fetched=_fetch(seed,timeout)
  if not fetched:continue
  final_url,soup=fetched
  for anchor in soup.find_all("a",href=True):
   url=_absolute(final_url,str(anchor.get("href")))
   if not url or url in seen or not _same_host(url,allowed_hosts) or not _allowed_path(url,prefixes):continue
   text=_clean(anchor.get_text(" ",strip=True))
   if len(text)<12:continue
   seen.add(url); candidates.append(url)
   if len(candidates)>=max_links:break
  if len(candidates)>=max_links:break
 items=[]
 for url in candidates:
  fetched=_fetch(url,timeout)
  if not fetched:continue
  final_url,soup=fetched; title=_metadata(soup,"og:title","twitter:title") or _clean(soup.title.get_text(" ",strip=True) if soup.title else "")
  if not title or len(title)<8:continue
  body=_article_text(soup); description=_metadata(soup,"og:description","twitter:description","description") or ""; material=body if len(body)>=180 else description
  if len(material)<80:continue
  image=_metadata(soup,"og:image","twitter:image"); image=urljoin(final_url,image) if image else None; published=_parse_date(soup); external_id=hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:40]
  items.append(NewsItem(source_name=source["name"],source_type="government" if source.get("source_class")=="government" else "website",title=title[:500],url=final_url,published_at=published,summary=material[:12000],external_id=external_id,category=source.get("category","general"),image_url=image,public_source=bool(source.get("public_source",False))))
 return items
