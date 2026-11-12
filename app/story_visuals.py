"""Conservative visual summaries of numbers explicitly stated in a news article.

No model call, external dataset, invented remainder or inferred fact.
Only explicit, comparable observations become a chart; other quantities retain
verbatim report context in cards. Editing the copy changes the figures with it.
"""
from html import escape
import math
import re
import unicodedata
from .source_http import public_http_url
from .source_text import source_text

NUM = r'-?\d[\d,]*(?:\.\d+)?'
UNITS = r'%|per\s+cent|percent|टक्के|crore|कोटी|lakh|लाख|billion|million|seats?|जागा|votes|मते|cases|रुग्ण|mm|मिमी|km|किमी|tonnes?|टन'
QUANTITY = re.compile(r'(?<![\w.])(?P<currency>[₹$€])?\s*(?P<value>'+NUM+r')\s*(?P<unit>'+UNITS+r')(?!\w)',re.I)
# A range may repeat its unit at both ends. Exclude both observations, rather
# than turning an endpoint into an exact metric or an incomplete comparison.
RANGE_VALUE = r'[₹$€]?\s*'+NUM+r'\s*(?:'+UNITS+r'|points?|AQI)?'
RANGE = re.compile(r'(?<![\w.])(?:\bbetween\s+'+RANGE_VALUE+r'\s+and\s+'+RANGE_VALUE+
                   r'|[₹$€]?\s*'+NUM+r'\s+and\s+'+RANGE_VALUE+
                   r'|'+RANGE_VALUE+r'\s*(?:[-–—]|\bto\b|ते)\s*'+RANGE_VALUE+r')(?!\w)', re.I)
# Crossing/exceeding a threshold does not state an exact observation, even
# when the report supplies a precise-looking percentage or currency amount.
QUALIFIER = re.compile(r'(?:\b(?:over|under|above|below|more than|less than|about|around|up to|nearly|approximately|roughly|at least|at most|(?:cross(?:ed|es|ing)?|exceed(?:ed|s|ing)?|surpass(?:ed|es|ing)?)(?:\s+the)?)|सुमारे|अंदाजे|किमान|कमाल|[~≈<>≤≥])\s*[₹$€]?\s*$', re.I)
QUALIFIED_END = re.compile(r'^\s*(?:\+|\b(?:or more|or less|and above|and below)\b)', re.I)
# Market-index names/counts are not levels. Require a reported relation for
# Nifty/Sensex, while retaining the established bare "AQI 344" shorthand.
INDEX_READING = re.compile(
    r'\b(?P<label>AQI|Nifty(?:\s+50)?|Sensex)\b(?:\s+index)?\s*'
    r'(?P<relation>(?:was|is|at|stood\s+at|stands\s+at)\b|[:=])?\s*'
    r'(?P<value>'+NUM+r')(?![\w,]|\.\d)(?:\s+points?\b)?', re.I)
INDEX_OTHER_UNIT = re.compile(r'^\s*(?:%|(?:percent|per\s+cent|टक्के|stocks?|shares?|constituents?|companies)(?!\w))', re.I)
INDEX_CHANGE = re.compile(r'^\s*(?:higher|lower|up|down)\b', re.I)
UNIT_MAP = {'per cent':'%','percent':'%','टक्के':'%','कोटी':'crore','लाख':'lakh','seat':'seats','जागा':'seats','मिमी':'mm','किमी':'km','tonne':'tonnes','टन':'tonnes'}
MEASURES = [(r'\b(?:vote share|voting share)\b|मतांचा वाटा','Vote share'),(r'\b(?:seats?|seat tally)\b|जागा','Seat comparison'),(r'\bturnout\b','Voter turnout'),(r'\bmargin\b','Margin'),(r'\bvotes\b|मते','Vote comparison'),(r'\bcases\b|रुग्ण','Reported cases'),(r'\bAQI\b|air quality index','Air quality index'),(r'\b(?:GDP|growth)\b|वाढ','Growth'),(r'inflation|महागाई','Inflation'),(r'\b(?:sales|revenue)\b|विक्री|महसूल','Sales / revenue'),(r'\b(?:budget|allocation|spending|expenditure)\b|खर्च|अर्थसंकल्प','Budget / allocation'),(r'\b(?:rainfall|rain)\b|पाऊस','Rainfall')]
COLORS = ['#2463ad','#b51f36','#20927b','#b27a21','#795caa','#50797c','#8e6250','#65758a']


def normalize(text):
    return ''.join(str(unicodedata.digit(c)) if c.isdecimal() else c for c in str(text or ''))


def numeric(raw):
    try:
        if ',' in raw and not re.fullmatch(r'-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3})(?:\.[0-9]+)?',raw):return None
        value=float(raw.replace(',',''))
        return value if math.isfinite(value) and abs(value)<=1e12 else None
    except ValueError:return None


def exact_observation(paragraph, start, end, ranges):
    return not (any(start < right and end > left for left, right in ranges)
                or QUALIFIER.search(paragraph[max(0, start-80):start])
                or QUALIFIED_END.search(paragraph[end:]))


def fmt(value):
    return f'{value:,.3f}'.rstrip('0').rstrip('.') if value%1 else f'{value:,.0f}'


def label_for(prefix):
    prefix=re.split(r'(?<!\d)[,;\n]|(?<=\d),(?!\d)',prefix)[-1]
    prefix=re.sub(r'^\s*(?:while|and|followed by|compared with|compared to|whereas|the)\s+','',prefix,flags=re.I)
    prefix=re.sub(r'\b(?:recorded|clocked|reported|registered|won|secured|received|earned|at|was|were|stood at|stands at|accounted for)\b.*$','',prefix,flags=re.I)
    prefix=re.sub(r'[₹$€]','',prefix).strip(' :–—-.,;\t')
    prefix=prefix.rsplit(':',1)[-1].strip()
    prefix=re.sub(r'^the\s+','',prefix,flags=re.I)
    return prefix if 0<len(prefix)<=65 and len(prefix.split())<=9 and not re.search(r'\d{5,}',prefix) else ''


def measure_for(text):
    found=[label for pattern,label in MEASURES if re.search(pattern,text,re.I)]
    return found[0] if len(found)==1 else ''


def chart_kind(points,unit,context):
    labels=[p['label']for p in points]
    if all(re.fullmatch(r'(?:19|20)\d{2}',label)for label in labels):
        years=list(map(int,labels))
        return 'line' if years==sorted(years) and len(set(years))==len(years) else 'bar'
    if unit=='%' and re.search(r'\b(?:share|distribution|breakdown)\b|वाटप|हिस्सा|वाटा',context,re.I) and all(p['value']>=0 for p in points) and abs(sum(p['value']for p in points)-100)<.001:
        return 'pie'
    return 'bar'


def extract(row):
    """Return at most one coherent chart and three contextual numeric cards."""
    raw=str(row.get('bot_article') or row.get('article') or row.get('body') or row.get('bot_summary') or row.get('summary') or '')[:50000]
    if re.search(r'<[a-zA-Z!/]',raw):
        from bs4 import BeautifulSoup
        document=BeautifulSoup(raw,'html.parser')
        for table in document.select('table'):
            rows=[' | '.join(c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])) for tr in table.select('tr')]
            table.replace_with('\n'+'\n'.join(rows)+'\n')
        raw=str(document)
    body=normalize(source_text(raw,paragraphs=True))
    title=normalize(row.get('title'))
    paragraphs=[p.strip()for p in re.split(r'\n\s*\n|\n(?=[^\n]*\|)',body)if p.strip()]
    facts=[];chart=None;seen=set()
    # Explicit two-column source tables: a named unit/measure is mandatory.
    lines=body.splitlines()
    for i,line in enumerate(lines):
        if '|' not in line:continue
        header=[x.strip()for x in line.strip('|').split('|')]
        if len(header)!=2:continue
        unit_match=re.search(r'(?:'+UNITS+r'|AQI)\b|%',header[1],re.I)
        if not unit_match or re.fullmatch(r'(?:value|rate|amount|figures?|percentage)\s*\([^)]*\)',header[1],re.I):continue
        unit=UNIT_MAP.get(unit_match[0].lower(),unit_match[0])
        currency=re.search(r'[₹$€]',header[1])
        if currency:unit=currency[0]+' '+unit
        points=[]
        for entry in lines[i+1:i+15]:
            cells=[x.strip()for x in entry.strip().strip('|').split('|')]
            if len(cells)==2 and all(re.fullmatch(r'[:\- ]+',c or ' ')for c in cells):continue
            if len(cells)!=2 or not cells[0] or len(cells[0])>60:break
            raw=cells[1].strip()
            if currency:raw=raw.removeprefix(currency[0]).strip()
            raw=re.sub(r'\s*(?:'+re.escape(unit_match[0])+r')$','',raw,flags=re.I).strip()
            if not re.fullmatch(NUM,raw):break
            value=numeric(raw)
            if value is None:break
            points.append({'label':cells[0],'value':value,'reported':raw})
        mixed=len([1 for pattern,_ in MEASURES if re.search(pattern,' '.join(p['label']for p in points),re.I)])>1
        if not mixed and 2<=len(points)<=12 and len({p['label']for p in points})==len(points):
            chart={'points':points,'unit':unit,'measure':header[1],'context':line,'kind':chart_kind(points,unit,line)};break
    for paragraph in paragraphs:
        ranges = [match.span() for match in RANGE.finditer(paragraph)]
        for index_match in INDEX_READING.finditer(paragraph):
            name=index_match['label'];suffix=paragraph[index_match.end():]
            if name.upper()!='AQI' and not index_match['relation']:continue
            if INDEX_OTHER_UNIT.match(suffix) or INDEX_CHANGE.match(suffix):continue
            if not exact_observation(paragraph, index_match.start('value'), index_match.end(), ranges):continue
            value=numeric(index_match['value']);unit='AQI' if name.upper()=='AQI' else 'points'
            if value is not None and (value,unit) not in seen and len(facts)<3:
                seen.add((value,unit));facts.append({'label':name,'value':value,'unit':unit,'reported':index_match['value'],'context':paragraph[max(0,index_match.start()-100):index_match.end()+180]})
        matches=list(QUANTITY.finditer(paragraph))
        observations=[];uncertain=False
        for index,match in enumerate(matches):
            if not exact_observation(paragraph, match.start('value'), match.end(), ranges):
                uncertain=True;continue
            value=numeric(match['value'])
            if value is None:continue
            start=matches[index-1].end() if index else 0
            label=label_for(paragraph[start:match.start()])
            unit=UNIT_MAP.get(re.sub(r'\s+',' ',match['unit'].lower()),match['unit'].lower())
            unit=(match['currency']+' ' if match['currency'] else '')+unit
            observation={'label':label,'value':value,'unit':unit,'reported':match['value']}
            observations.append(observation)
            identity=(value,unit)
            if identity not in seen and len(facts)<3:
                seen.add(identity);facts.append({**observation,'context':paragraph[max(0,match.start()-120):match.end()+180]})
        if chart or uncertain or len(paragraph)>1800 or not 2<=len(observations)<=8:continue
        units={p['unit']for p in observations};labels=[p['label']for p in observations]
        measure=measure_for(paragraph) or measure_for(paragraph+' '+title)
        if len(units)!=1 or not all(labels) or len(set(labels))!=len(labels) or not measure:continue
        # Do not chart dissimilar indicators that happen to share a percent unit.
        if any(re.search(r'\d',label) and not re.fullmatch(r'(?:19|20)\d{2}',label)for label in labels):continue
        points=[{'label':p['label'],'value':p['value'],'reported':p['reported']}for p in observations]
        unit=next(iter(units));chart={'points':points,'unit':unit,'measure':measure,'context':paragraph,'kind':chart_kind(points,unit,paragraph)}
    return {'chart':chart,'facts':facts} if chart or facts else None


def plot(chart,key):
    e=lambda v:escape(str(v),quote=True)
    points,unit,kind=chart['points'],chart['unit'],chart['kind']
    label=lambda p:f"{p['label']}: {fmt(p['value'])} {unit}"
    if kind=='pie':
        angle=-math.pi/2;parts=[]
        for i,p in enumerate(points):
            if p['value']==0:continue
            end=angle+p['value']/100*2*math.pi
            # Two semicircles also support a single 100% slice.
            mid=(angle+end)/2
            coord=lambda a:f'{180+115*math.cos(a):.3f},{160+115*math.sin(a):.3f}'
            path=f'M180,160 L{coord(angle)} A115,115 0 0 1 {coord(mid)} A115,115 0 0 1 {coord(end)} Z'
            parts.append(f'<path d="{path}" fill="{COLORS[i%len(COLORS)]}" tabindex="0" class="story-slice" role="img" aria-label="{e(label(p))}" data-label="{e(p["label"])}" data-value="{e(fmt(p["value"])+" "+unit)}"><title>{e(label(p))}</title></path>')
            angle=end
        legend=''.join(f'<li><i style="background:{COLORS[i%len(COLORS)]}"></i><span>{e(p["label"])}</span><b>{e(fmt(p["value"]))}%</b></li>'for i,p in enumerate(points))
        return f'<div class="article-data-chart story-pie"><svg viewBox="0 0 360 320" role="group" aria-label="{e(chart["measure"])}">{"".join(parts)}</svg><ul>{legend}</ul><div class="article-data-tooltip" hidden></div></div>'
    values=[p['value']for p in points];low=min(0,min(values));high=max(0,max(values));span=high-low or 1
    power=10**math.floor(math.log10(max(span,1e-9)/4))
    tick=next((n*power for n in [1,2,2.5,5,10] if n*power>=span/4),10*power)
    low=math.floor(low/tick)*tick;high=math.ceil(high/tick)*tick
    if low==high:high=low+tick
    span=high-low
    y=lambda v:260-(v-low)/span*215
    step=600/len(points);baseline=y(0);parts=[]
    for i,p in enumerate(points):
        x=80+(i+.5)*step;py=y(p['value']);tooltip=f'tabindex="0" role="img" aria-label="{e(label(p))}" data-label="{e(p["label"])}" data-value="{e(fmt(p["value"])+" "+unit)}"'
        if kind=='line':parts.append(f'<circle class="story-point" cx="{x:.2f}" cy="{py:.2f}" r="7" {tooltip}><title>{e(label(p))}</title></circle>')
        else:parts.append(f'<rect class="data-bar" x="{x-step*.3:.2f}" y="{min(py,baseline):.2f}" width="{step*.6:.2f}" height="{max(abs(py-baseline),1):.2f}" rx="5" {tooltip}><title>{e(label(p))}</title></rect>')
        parts.append(f'<text x="{x:.2f}" y="{py-12 if p["value"]>=0 else py+20:.2f}" text-anchor="middle" class="data-value">{e(fmt(p["value"]))}</text><text x="{x:.2f}" y="294" text-anchor="middle">{e(p["label"][:24])}</text>')
    grid=''.join(f'<line class="data-grid" x1="70" x2="690" y1="{y(low+tick*i):.2f}" y2="{y(low+tick*i):.2f}"/><text x="60" y="{y(low+tick*i)+4:.2f}" text-anchor="end">{e(fmt(low+tick*i))}</text>'for i in range(round(span/tick)+1))
    line=''
    if kind=='line':
        coords=' '.join(f'{80+(i+.5)*step:.2f},{y(p["value"]):.2f}'for i,p in enumerate(points));line=f'<polyline class="story-line" points="{coords}"/>'
    return f'<div class="article-data-chart"><svg viewBox="0 0 720 330" role="group" aria-label="{e(chart["measure"])}">{grid}<line class="data-zero" x1="70" x2="690" y1="{baseline:.2f}" y2="{baseline:.2f}"/>{line}{"".join(parts)}</svg><div class="article-data-tooltip" hidden></div></div>'


def render(row):
    data=extract(dict(row))
    if not data:return ''
    e=lambda v:escape(str(v),quote=True)
    key='story-numbers-'+re.sub(r'[^a-zA-Z0-9-]','',str(row.get('id') or 'report'))
    chart=data['chart'];facts=data['facts']
    if chart:
        cards=''.join(f'<div class="article-data-metric"><span>{e(p["label"])}</span><strong>{e(fmt(p["value"]))} <small>{e(chart["unit"])}</small></strong><small>{e(chart["measure"])}</small></div>'for p in chart['points'][:3])
        hint='' if chart['kind']=='pie' else '<p class="article-data-scroll-hint">Swipe to see all observations.</p>'
        figure=f'<figure><figcaption>{e(chart["measure"])} · {e(chart["unit"])}</figcaption>{plot(chart,key)}{hint}</figure>'
        rows=''.join(f'<tr><th scope="row">{e(p["label"])}</th><td>{e(p.get('reported',fmt(p['value'])))}</td></tr>'for p in chart['points'])
        table=f'<details class="article-data-table"><summary>View the figures and report context</summary><div><table><caption>{e(chart["measure"])} ({e(chart["unit"])})</caption><tbody>{rows}</tbody></table><blockquote>{e(chart["context"])}</blockquote></div></details>'
    else:
        cards=''.join(f'<div class="article-data-metric"><span>{e(p["label"] or "Reported figure")}</span><strong>{e(fmt(p["value"]))} <small>{e(p["unit"])}</small></strong><small>{e(p["context"])}</small></div>'for p in facts)
        figure=table=''
    url=str(row.get('url') or '')
    source=f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(row.get("source_name") or "Original report")}</a>' if url.startswith('https://') and public_http_url(url) else e(row.get('source_name') or 'This report')
    identity=str(row.get('id') or '')
    download=(f'<p class="article-data-note"><a href="/api/article-visuals/{identity}/csv" download>Download figures (CSV)</a> · Includes units and original source details.</p>' if re.fullmatch(r'[1-9][0-9]{0,18}',identity) else '')
    return f'<section class="article-data story-numbers" aria-labelledby="{key}"><p class="article-data-eyebrow">THE STORY IN NUMBERS</p><h2 id="{key}">The figures behind this story</h2><p class="article-data-description">Figures from this report. Compare the named observations using the units and source context shown below.</p><div class="article-data-metrics">{cards}</div>{figure}<p class="article-data-source">Source: {source}. Figures as stated in the article; see the original report for context.</p>{download}{table}</section>'
