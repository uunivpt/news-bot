"""Unicode keyword search shared by live and archived news."""
import re
import unicodedata

STOP={'a','an','the','of','for','to','in','on','and','or','is','are','was','with','news','latest'}
FIELDS=('title','summary','bot_summary','bot_article','article','source_name','category')

def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split())

def terms(query):
    return list(dict.fromkeys(t for t in re.split(r'[\s,.;:!?/\\()\[\]{}"\'|%_*—–-]+',normalized(query)) if len(t)>=2 and t not in STOP))[:10]

def contains(term,text):
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(term),text)) if term.isascii() else term in text

def relevance(row,query):
    from .news_numbers import news_number
    q=normalized(query)
    if q.isdigit():return 10000 if q in {str(row.get('id')),news_number(row)} else 0
    tokens=terms(q)
    if not tokens:return 0
    title=normalized(row.get('title'));lead=normalized(row.get('bot_summary') or row.get('summary'))
    body=normalized(row.get('bot_article') or row.get('article'))
    source=normalized(str(row.get('source_name') or '')+' '+str(row.get('category') or ''))
    matched=sum(contains(t,title) or contains(t,lead) or contains(t,body) or contains(t,source) for t in tokens)
    if not matched:return 0
    return (100 if q in title else 0)+(50 if matched==len(tokens) else 0)+sum(12*contains(t,title)+4*contains(t,lead)+1*contains(t,body)+2*contains(t,source) for t in tokens)

def matching(rows,query):
    return [row for row in rows if relevance(row,query)>0]
