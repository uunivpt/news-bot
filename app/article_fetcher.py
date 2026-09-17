from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS={"User-Agent":"PoliticsHubNewsBot/2.0 (+public-news-collector)"}
URL_RE=re.compile(r"https?://[^\s<>()]+",re.I)
BOILERPLATE=re.compile(r"cookie|subscribe|sign in|log in|advertisement|newsletter|follow us|share this",re.I)


def find_urls(text):
 return [m.group(0).rstrip(".,);]}") for m in URL_RE.finditer(text or "")]


def _clean_text(value):
 return re.sub(r"\s+"," ",value or "").strip()


def extract_public_article(url,timeout=10):
 """Fetch readable public article material for the deterministic newsroom bot."""
 if not url.startswith(("http://","https://")):return None
 try:
  response=requests.get(url,headers=HEADERS,timeout=timeout,allow_redirects=True); response.raise_for_status()
  if "html" not in (response.headers.get("content-type") or "").lower():return None
  soup=BeautifulSoup(response.text[:4_000_000],"html.parser")
  for node in soup(["script","style","noscript","svg","nav","footer","form","aside"]):node.decompose()
  def meta(*names):
   for name in names:
    node=soup.find("meta",attrs={"property":name}) or soup.find("meta",attrs={"name":name})
    if node and node.get("content"):return _clean_text(str(node["content"]))
   return None
  title=meta("og:title","twitter:title") or _clean_text(soup.title.get_text(" ",strip=True) if soup.title else "")
  description=meta("og:description","twitter:description","description") or ""; image=meta("og:image","twitter:image")
  if image:image=urljoin(response.url,image)
  candidates=[]
  for selector in ("article","main",'[role="main"]','.article-body','.article-content','.story-body','.entry-content'):
   for node in soup.select(selector):
    text="\n".join(_clean_text(p.get_text(" ",strip=True)) for p in node.find_all(["p","h2","h3","li"]))
    text="\n".join(line for line in text.splitlines() if line and not BOILERPLATE.search(line))
    if len(text)>400:candidates.append(text)
  if not candidates:
   paragraphs=[]
   for p in soup.find_all(["p","h2","h3"]):
    text=_clean_text(p.get_text(" ",strip=True))
    if len(text)>=45 and not BOILERPLATE.search(text):paragraphs.append(text)
   candidates.append("\n".join(paragraphs))
  body=max(candidates,key=len)[:24_000].strip()
  if len(body)<250:return None
  return {"url":response.url,"title":title[:500],"description":description[:1500],"image_url":image,"text":body}
 except Exception:return None


def enrich_source_text(title,summary):
 """Prefer linked public article text; otherwise use the collected post text."""
 for url in find_urls(summary)[:2]:
  article=extract_public_article(url)
  if article:return article
 return {"url":None,"title":title,"description":summary or "","image_url":None,"text":summary or title}
