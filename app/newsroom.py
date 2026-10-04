from __future__ import annotations
import re
from collections import Counter

from app.extractive_summarizer import hybrid_scores

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
    r"effective|scheduled|resigned|appointed|elected|found|identified|"
    r"returned|operated|operate|publish|published|generating|generated|"
    r"treated|remain|remains|reviewed|review|continues|continuing|"
    r"installed|added|deployed|receive|received|applies|affects|"
    r"available|begin|begins|run|runs|resume|resumed|includes|connects|provides|contains|covers)\b",re.I
)
CONSEQUENCE_WORDS=re.compile(
    r"\b(?:effective|from|starting|next|result|following|after|because|"
    r"allow|require|mean|means|expected|scheduled|deadline|impact|affect|"
    r"remain|remains|suspended|continue|continues|continuing|review|"
    r"return|returned|operate|operates|published|publish)\b",re.I
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

    if DATE_OR_NUMBER_RE.search(sentence): score += 5.0
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
    """Select complementary factual source sentences without rewriting them."""
    items=sentences(text)
    limit=max(1,int(limit))
    if len(items)<=limit:return items

    title_words=set(_content_words(title))
    frequency=Counter(w for item in items for w in _content_words(item))
    editorial_scores=[]
    for i,item in enumerate(items):
        score=_score(item,i,len(items),title_words)
        words=_content_words(item)
        if words:
            score += sum(1.0/max(1,frequency[w]) for w in set(words))*0.18
        editorial_scores.append(score)

    # TextRank/LexRank remain part of the ranking, but they are tie-breakers
    # around the newsroom's factual coverage rules. Centrality alone must never
    # be allowed to discard a distinct date, number or material outcome.
    algorithm_scores=hybrid_scores(items,editorial_scores)
    ranked=sorted(range(len(items)),key=lambda i:algorithm_scores[i],reverse=True)

    def valid(i):
        return not _is_duplicate_of_title(items[i],title)

    source_order=[i for i in range(len(items)) if valid(i)]

    MATERIAL_FACT_RE=re.compile(
        r"(?i)(?:"
        r"\b(?:\d+(?:\.\d+)?%?|\$\d[\d,.]*|₹\s?\d[\d,.]*|\d{4})\b"
        r"|\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
        r"|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s+[A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*){0,2}\b"
        r"|\b(?:first|second|third|fourth|fifth|next|another|additional)\s+[A-Za-z][A-Za-z-]*"
        r"(?:\s+[A-Za-z][A-Za-z-]*){0,2}\b"
        r")"
    )
    outcomes=[i for i in ranked if valid(i) and CONSEQUENCE_WORDS.search(items[i])]
    concrete=[
        i for i in source_order
        if MATERIAL_FACT_RE.search(items[i])
    ]

    # Deterministic coverage policy:
    # - keep up to three sentences carrying explicit material facts;
    # - fill remaining slots with the earliest distinct factual sentences;
    # - prefer a clear status outcome only when no better factual detail exists.
    # This preserves source order while preventing dates, quantities and
    # operational details from being dropped by a centrality tie-breaker.
    chosen=concrete[:limit]
    if len(chosen)<limit:
        factual_fill=[
            i for i in source_order
            if i not in chosen and FACT_VERBS.search(items[i])
        ]
        for i in factual_fill:
            if len(chosen)>=limit:break
            chosen.append(i)

    if len(chosen)<limit:
        status_outcome_re=re.compile(r"\b(?:remain|remains|remained|suspended|shutdown|closed|cancelled|reopen|reopened|not affected)\b",re.I)
        status_fill=[
            i for i in source_order
            if i not in chosen and status_outcome_re.search(items[i])
        ]
        for i in status_fill:
            if len(chosen)>=limit:break
            chosen.append(i)

    if len(chosen)<limit:
        for i in source_order:
            if len(chosen)>=limit:break
            if i not in chosen:
                chosen.append(i)

    if len(chosen)>=limit:
        return [items[i] for i in sorted(chosen)[:limit]]

    chosen=[]

    # If the source has three or more concrete-fact sentences, use those as
    # the core of a 3-sentence summary. This prevents centrality from dropping
    # distinct dates/numbers such as capacity, deadlines and worker counts.
    if len(concrete)>=limit:
        chosen.extend(concrete[:limit])
    else:
        # Keep every distinct concrete fact first; then reserve a slot for a
        # material outcome/next step when one exists.
        chosen.extend(concrete[:limit])

        for i in outcomes:
            if i not in chosen:
                chosen.append(i)
                break

        # Fill the remaining slot(s) using hybrid rank with MMR diversity.
        while len(chosen)<limit:
            best=None
            for i in ranked:
                if i in chosen or not valid(i):
                    continue
                redundancy=max((_jaccard(items[i],items[j]) for j in chosen),default=0.0)
                adjusted=algorithm_scores[i]-(2.2*redundancy)
                candidate=(adjusted,algorithm_scores[i],-i,i)
                if best is None or candidate>best:
                    best=candidate
            if best is None:
                break
            chosen.append(best[3])

    # Do NOT replace a concrete-fact sentence with a generic outcome such as
    # "a review will continue". Only a strong operational outcome may occupy
    # the final slot when it carries a material status/change.
    STRONG_OUTCOME_RE=re.compile(
        r"\b(?:remain|remains|remained|suspend|suspended|"
        r"resume|resumed|reopen|reopened|continue|continues|"
        r"continued|cancel|cancelled|closed|shutdown|"
        r"take effect|will operate|is not affected)\b",re.I
    )
    # Strong outcomes must be detected from every source sentence, not only
    # the softer consequence-word bucket; otherwise material status changes can
    # be missed by the final coverage pass.
    strong_outcomes=[
        i for i in ranked
        if valid(i) and STRONG_OUTCOME_RE.search(items[i])
    ]

    # If fewer than limit factual sentences exist, add one strong operational
    # outcome. If the summary already has limit concrete facts, never evict one
    # merely because another sentence contains a generic "review" phrase.
    for i in strong_outcomes:
        if i in chosen:
            break
        if len(chosen)<limit:
            chosen.append(i)
            break
        # Only replace a non-concrete sentence. Concrete facts are protected.
        non_concrete=[j for j in chosen if not MATERIAL_FACT_RE.search(items[j])]
        if non_concrete:
            replace=min(
                non_concrete,
                key=lambda j: (
                    _score(items[j],j,len(items),title_words),
                    algorithm_scores[j],
                ),
            )
            chosen[chosen.index(replace)]=i
        break

    chosen=set(chosen)
    return [item for i,item in enumerate(items) if i in chosen][:limit]

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
    chosen=select_sentences(source_text,limit,title=title)
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
