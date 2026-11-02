"""Read notice metadata from configured official examination authorities only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .source_http import fetch_source, public_http_url
from .source_text import source_text

CONFIG=Path(__file__).resolve().parents[1]/'config/official-exam-sources.json'
KEYWORDS=re.compile(r'exam|examination|admit|answer.?key|result|application|registration|recruitment|candidates?|admission|syllabus|timetable|schedule|certificate|score|cut.?off|counsell|\bLOC\b|\bCET\b|परीक्षा|प्रवेश|अर्ज|उमेदवार|निकाल|वेळापत्रक|शिष्यवृत्ती|भरती',re.I)
EXCLUDE=re.compile(r'quotation|tender|procurement|water cooler|canteen|hotel|empanelment|निविदा',re.I)
DATE=re.compile(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b')

def sources():return json.loads(CONFIG.read_text())

def parse_notices(content,source,base_url=None):
    soup=BeautifulSoup(content,'html.parser');seen=set();items=[]
    for element in soup(['script','style','nav','header','footer']):element.decompose()
    for anchor in soup.select('a[href]'):
        url=urljoin(base_url or source['url'],anchor.get('href',''))
        if not url.lower().split('?',1)[0].endswith('.pdf') or not url.startswith('https://') or not public_http_url(url,source['allowed_hosts']) or url in seen:continue
        row=anchor.find_parent('tr')
        cells=row.find_all(['td','th'],recursive=False) if row else []
        texts=[source_text(x.get_text(' ',strip=True)) for x in cells]
        candidates=[text for text in texts if KEYWORDS.search(text) and not EXCLUDE.search(text)]
        title=max(candidates,key=len) if candidates else source_text(anchor.get_text(' ',strip=True))
        if len(title)<20 or len(title)>600 or not KEYWORDS.search(title) or EXCLUDE.search(title):continue
        date_text=next((text for text in texts if DATE.fullmatch(text)), '')
        match=DATE.search(date_text);published=None
        if match:
            try:published=datetime(int(match[3]),int(match[2]),int(match[1]),tzinfo=timezone.utc).isoformat()
            except ValueError:pass
        digest=hashlib.sha256(url.encode()).hexdigest()
        items.append({'id':8_000_000_000_000_000+int(digest[:12],16),'title':title,'url':url,
          'source_name':source['name'],'source_type':'official_exam','public_source':True,'status':'published',
          'category':'india','exam_region':source['region'],'exam_authority':source['id'],
          'published_at':published,'summary':f"Official examination notice listed by {source['name']}: {title}. Open the original official document to verify instructions, eligibility and any deadlines; dates are not inferred from collection time.",
          'bot_article':'','image_url':''})
        seen.add(url)
        if len(items)>=80:break
    return items

def fetch_notices(source):
    document=fetch_source(source['url'],timeout=20,max_bytes=4_000_000,allowed_hosts=source['allowed_hosts'])
    return parse_notices(document.content,source,document.url)
