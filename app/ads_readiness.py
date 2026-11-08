"""Measured technical/content readiness, never an AdSense approval prediction."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from .monetization import is_monetizable,has_distinct_body,requires_sensitive_ad_review
from .seo_indexing import is_indexable,SITE_ORIGIN
from .source_http import fetch_source
from .editorial_store import now

ROOT=Path(__file__).resolve().parents[1]
PAGES=['about.html','contact.html','privacy.html','cookies.html','terms.html','editorial-policy.html','corrections.html','licenses.html']


def article_findings(row):
    findings=[]
    if not is_indexable(row):findings.append('Local search eligibility checks incomplete')
    if not has_distinct_body(row):findings.append('Source brief / insufficient distinct article context under local ad rules')
    if not row.get('source_name') or not row.get('url'):findings.append('Missing source attribution')
    if row.get('image_url') and (row.get('image_license') not in {'licensed','rights-owned','cc0','pdm'} or not row.get('image_credit')):findings.append('Image licence or credit missing')
    if requires_sensitive_ad_review(row) and 'Ad suitability reviewed for sensitive coverage.' not in str(row.get('fact_check_notes') or ''):
        findings.append('Sensitive coverage requires separate ad suitability review')
    if not is_monetizable(row):findings.append('Current-copy originality/evidence review incomplete')
    return findings


def readiness(db,page=1):
    p='%s' if db._postgres else '?';page=max(1,min(page,100000));size=25
    totals=dict(db.conn.execute("""SELECT COUNT(*) AS published,
        COALESCE(SUM(CASE WHEN LENGTH(COALESCE(bot_article,''))<600 THEN 1 ELSE 0 END),0) AS short_body,
        COALESCE(SUM(CASE WHEN COALESCE(source_name,'')='' OR COALESCE(url,'')='' THEN 1 ELSE 0 END),0) AS missing_attribution,
        COALESCE(SUM(CASE WHEN COALESCE(image_url,'')<>'' AND (COALESCE(image_license,'') NOT IN ('licensed','rights-owned','cc0','pdm') OR COALESCE(image_credit,'')='') THEN 1 ELSE 0 END),0) AS missing_image_rights
        FROM news_items WHERE status='published'""").fetchone())
    duplicate_titles=int(db.conn.execute("SELECT COUNT(*) AS count FROM (SELECT LOWER(TRIM(title)) AS headline FROM news_items WHERE status='published' GROUP BY LOWER(TRIM(title)) HAVING COUNT(*)>1) AS duplicates").fetchone()['count'])
    rows=[dict(r) for r in db.conn.execute(f'SELECT * FROM news_items WHERE status=\'published\' ORDER BY id DESC LIMIT {p} OFFSET {p}',(size,(page-1)*size)).fetchall()]
    articles=[{'id':r['id'],'title':r['title'],'source_name':r['source_name'],'category':r['category'],'monetizable_under_local_rules':is_monetizable(r),'findings':article_findings(r)} for r in rows]
    ads=ROOT/'public/ads.txt';text=ads.read_text() if ads.exists() else ''
    expected='google.com, pub-1752666987448533, DIRECT, f08c47fec0942fa0'
    return {'checked_at':now(),'scope':'All published database totals; article findings are paginated, 25 per page.',
            'totals':dict(totals,duplicate_title_groups=duplicate_titles),'articles':articles,'page':page,'page_size':size,
            'pages':max(1,(int(totals['published'])+size-1)//size),
            'ads_txt':{'present':ads.exists(),'expected_line_present':any(re.sub(r'\s*,\s*',', ',line.strip())==expected for line in text.splitlines())},
            'policy_pages':[{'path':'/'+name,'present':(ROOT/'public'/name).exists()} for name in PAGES],
            'notice':'Technical checks and local editorial standards only. Google decides AdSense approval; a file or word-count check cannot establish original reporting or policy compliance.',
            'guidance':[{'label':'Google ads.txt troubleshooting','url':'https://support.google.com/adsense/answer/12171612'}, {'label':'Google Publisher Policies','url':'https://support.google.com/publisherpolicies/answer/10502938'}]}


def live_probe():
    paths=['/ads.txt','/robots.txt','/sitemap.xml','/privacy.html','/']
    def check(path):
        checked=now()
        try:
            document=fetch_source(SITE_ORIGIN+path,timeout=6,max_bytes=2_000_000,allowed_hosts=['politicshub.in'])
            text=document.content.decode('utf-8','replace')
            result={'path':path,'checked_at':checked,'status':'accessible','http_status':200}
            if path=='/ads.txt':result['publisher_id_present']='pub-1752666987448533' in text
            if path=='/robots.txt':result['root_blocked']=bool(re.search(r'Disallow:\s*/\s*(?:\n|$)',text,re.I));result['body_excerpt']=text[:1500]
            return result
        except Exception as exc:
            response=getattr(exc,'response',None)
            return {'path':path,'checked_at':checked,'status':'unavailable_from_checker','http_status':getattr(response,'status_code',None),'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(check,paths))
    return {'checked_at':now(),'checks':results,'scope':'Actual HTTP GET from this server. This does not establish Google crawler access or the account review status.'}
