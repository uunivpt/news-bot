"""Public delivery counts, distinct from Google's indexing decisions."""
from .news_numbers import news_number
from .seo_indexing import is_indexable
from .category_routing import normalize_category

def counts(archive,recent,hindi,exams,discovery=lambda row:row):
    unique={};ids=set()
    # Current feeds win over historical copies of the same source URL.
    for row in recent+hindi+exams+archive:
        if str(row['id']) in ids or row.get('url') in unique:continue
        ids.add(str(row['id']));unique[row.get('url') or str(row['id'])]=row
    current_ids={str(r['id']) for r in recent+hindi}
    current={str(r['id']) for r in unique.values() if str(r['id']) in current_ids}
    exam_rows=[r for r in unique.values() if r.get('source_type')=='official_exam']
    return {'website_total':len(unique),'news_articles':len(unique)-len(exam_rows),
     'official_exam_notices':len(exam_rows),'homepage_feed':len(current),
     'archive_only':sum(str(r['id']) not in current and r.get('source_type')!='official_exam' for r in unique.values()),
     'search_eligible':sum(is_indexable(discovery(r)) for r in unique.values()),
     'google_indexed':None,'google_indexed_note':'Not measured here. Search eligibility and sitemap inclusion do not establish Google indexing.',
     'scope':'Unique public articles and official notices in the deployed archive and current public feeds. Drafts, rejected and private stories are excluded.'}
