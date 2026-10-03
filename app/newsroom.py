from __future__ import annotations
import re
from collections import Counter

URL_RE=re.compile(r"https?://\S+",re.I)
SPACE_RE=re.compile(r"\s+")
BAD_LINE_RE=re.compile(r"^(?:source|via|follow|subscribe|read more|click here|advertisement|ad)\b",re.I)
HANDLE_RE=re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}")
TRAILING_FRAGMENT_RE=re.compile(r"\b(?:a|an|and|as|at|by|for|from|in|including|into|of|on|or|such|than|that|the|their|this|to|under|via|was|were|with|without)\.?$",re.I)

# Deterministic newsroom training rules.
# The bot does NOT invent facts and does NOT call an LLM. It learns the shape
# of a good news summary from these editorial rules:
# 1) preserve who/what/where/when and concrete numbers;
# 2) prefer the lead + material new facts + consequence/next step;
# 3) never repeat the headline as a sentence;
# 4) never join unrelated sentences or manufacture transitions;
# 5) keep source order after selecting the best facts;
# 6) remove boilerplate, handles, URLs and incomplete fragments;
# 7) prefer factual reporting verbs over opinion/marketing language.
STOPWORDS={
    "the","and","for","that","with","this","from","have","has","were","was",
    "are","their","they","said","into","after","before","about","will","been",
    "also","than","then","over","under","more","some","such","its","but","not",
    "who","what","when","where","which","while","would","could","should"
}
FACT_VERBS=re.compile(
    r"\b(?:announced|approved|confirmed|reported|ordered|signed|launched|"
    r"introduced|agreed|rejected|accepted|opened|closed|began|ended|"
    r"started|stopped|won|lost|filed|charged|arrested|issued|released|"
    r"raised|cut|increased|decreased|fell|rose|set|will|plans?|expected|"
    r"effective|scheduled|resigned|appointed|elected|found|identified)\b",re.I
)
CONSEQUENCE_WORDS=re.compile(
    r"\b(?:effective|from|starting|next|result|following|after|because|"
    r"allow|require|mean|means|expected|scheduled|deadline|impact|affect)\b",re.I
)
DATE_OR_NUMBER_RE=re.compile(
    r"\b(?:\d+(?:\.\d+)?%?|\$\d[\d,.]*|₹\s?\d[\d,.]*|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*|"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"
    r"\d{4})\b",re.I
)

def clean_text(text: str|None)->str:
    value=text or ""
    value=URL_RE.sub("",value)
    value=HANDLE_RE.sub("",value)
    value=value.replace("\u200b"," ").replace("\xa0"," ")
    lines=[]
    for raw in re.split(r"\n+",value):
        line=SPACE_RE.sub(" ",raw).strip(" \t|•·")
        if line and not BAD_LINE_RE.search(line):
            lines.append(line)
    return "\n".join(lines)

def sentences(text:str)->list[str]:
    value=SPACE_RE.sub(" ",clean_text(text).replace("\n"," ")).strip()
    if not value:return []
    # Split only at clear sentence boundaries. Do not try to "repair" grammar
    # by concatenating fragments.
    parts=re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'‘“])",value)
    result=[]
    for index,part in enumerate(parts):
        item=part.strip(" \t-–—")
        if len(item)<30 or BAD_LINE_RE.search(item):
            continue
        if index==len(parts)-1 and not re.search(r"[.!?][\"'’”)]*$",item):
            continue
        if TRAILING_FRAGMENT_RE.search(item):
            continue
        result.append(item.rstrip(".!?")+".")
    return result

def _words(value):
    return re.findall(r"[A-Za-z][A-Za-z'-]{2,}",value.lower())

def _content_words(value):
    return [w for w in _words(value) if w not in STOPWORDS]

def _score(sentence,index,total,title_words):
    words=_content_words(sentence)
    if not words:return -100.0
    unique=set(words)
    score=0.0

    # The lead is usually the highest-value fact, but later concrete details
    # can outrank it when the lead merely repeats the headline.
    score += max(0.0,2.4-index*0.32)

    overlap=len(unique & title_words)/max(1,len(title_words))
    score += min(3.0,overlap*4.0)

    if DATE_OR_NUMBER_RE.search(sentence): score += 1.8
    if FACT_VERBS.search(sentence): score += 1.4
    if CONSEQUENCE_WORDS.search(sentence): score += 1.1

    # Named entities are useful, but avoid counting sentence-initial words.
    caps=re.findall(r"\b[A-Z][A-Za-z'-]{2,}\b",sentence)
    score += min(1.2,len(set(caps))*0.18)

    # Prefer readable factual sentences over tiny fragments or huge paragraphs.
    wc=len(words)
    if 12<=wc<=42: score += 0.8
    elif wc>60: score -= 0.8
    if re.search(r"\b(?:I|we|our|my)\b",sentence,re.I): score -= 1.2
    if re.search(r"\b(?:you must|buy now|click|subscribe|shocking|unbelievable)\b",sentence,re.I): score -= 2.0
    return score

def _jaccard(a,b):
    a=set(_content_words(a)); b=set(_content_words(b))
    return len(a&b)/max(1,len(a|b))

def select_sentences(text,limit,title=""):
    """Select complementary factual sentences without rewriting their facts."""
    items=sentences(text)
    limit=max(1,int(limit))
    if len(items)<=limit:return items

    title_words=set(_content_words(title))
    frequency=Counter(w for item in items for w in _content_words(item))
    ranked=[]
    for i,item in enumerate(items):
        score=_score(item,i,len(items),title_words)
        # Repeated generic words are less informative than distinctive facts.
        words=_content_words(item)
        if words:
            score += sum(1.0/max(1,frequency[w]) for w in set(words))*0.18
        ranked.append((score,i,item))

    chosen=[]
    remaining=ranked[:]
    while remaining and len(chosen)<limit:
        best=None
        for score,i,item in remaining:
            # MMR-style diversity: do not spend all 3 slots on near-duplicate
            # sentences that repeat the same fact.
            redundancy=max((_jaccard(item,x[2]) for x in chosen),default=0.0)
            adjusted=score-(2.2*redundancy)
            # Headline-duplicate leads are deliberately deprioritized.
            if title and _is_duplicate_of_title(item,title):
                adjusted-=4.0
            candidate=(adjusted,score,i,item)
            if best is None or candidate>best:best=candidate
        _,_,idx,item=best
        chosen.append((idx,item))
        remaining=[x for x in remaining if x[1]!=idx]

    return [item for _,item in sorted(chosen,key=lambda x:x[0])]

def _first_complete_sentence(value):
    items=sentences(value)
    return items[0] if items else ""

def _headline_from_sentence(sentence):
    sentence=sentence.rstrip(".!?").strip()
    clauses=re.split(r"\s+(?=[—–-])|,\s+",sentence)
    for clause in clauses:
        clause=clause.strip(" -–—")
        if 5<=len(clause.split())<=16:return clause
    return sentence

def make_headline(title,source_text):
    value=SPACE_RE.sub(" ",clean_text(title)).strip(" .:-")
    if 4<=len(value.split())<=18 and len(value)<=140:return value
    first=_first_complete_sentence(value)
    if first:
        clause=_headline_from_sentence(first)
        if 4<=len(clause.split())<=18:return clause[:140].rstrip(" .:-")
    items=sentences(source_text)
    if items:
        clause=_headline_from_sentence(items[0])
        return clause[:140].rstrip(" .:-")
    return value[:140].rstrip(" .:-") or "Latest news update"

def _norm_words(text):
    return set(_words(re.sub(r"[^A-Za-z0-9' -]"," ",text or "")))

def _is_duplicate_of_title(sentence,title):
    sentence_words=_norm_words(sentence)
    title_words=_norm_words(title)
    if not sentence_words or not title_words:return False
    overlap=len(sentence_words & title_words)/max(1,len(title_words))
    reverse=len(sentence_words & title_words)/max(1,len(sentence_words))
    return overlap>=0.72 and reverse>=0.55

def _unique_news_sentences(title,source_text,limit):
    chosen=select_sentences(source_text,max(limit+3,6),title=title)
    result=[];seen=set()
    for item in chosen:
        key=re.sub(r"[^a-z0-9]+"," ",item.lower()).strip()
        if not key or key in seen:continue
        if _is_duplicate_of_title(item,title):continue
        seen.add(key);result.append(item)
        if len(result)>=limit:break
    return result

def make_summary(title,source_text):
    chosen=_unique_news_sentences(title,source_text,3)
    if not chosen:return ""
    # Extractive by design: every sentence is copied from source material,
    # only whitespace/punctuation cleanup is performed.
    return " ".join(chosen)

def make_article(title,source_text):
    chosen=_unique_news_sentences(title,source_text,40)
    if not chosen:return ""
    paragraphs=[]
    if chosen[:3]:
        paragraphs.append(f"What happened: {' '.join(chosen[:3])}")
    buckets=[chosen[3:8],chosen[8:14],chosen[14:20],chosen[20:28],chosen[28:40]]
    labels=["Key details","What is known","Context","What comes next","Additional details"]
    for label,bucket in zip(labels,buckets):
        if bucket:paragraphs.append(f"{label}: {' '.join(bucket)}")
    return "\n\n".join(paragraphs).strip()

def process_news(title,source_text,category="general"):
    material=clean_text(source_text)
    if len(material)<80:return None
    result={
        "headline":make_headline(title,material),
        "summary":make_summary(title,material),
        "article":make_article(title,material),
    }
    if len(result["summary"])<50 or len(result["article"])<120:return None
    return result
