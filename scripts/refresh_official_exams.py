"""Refresh official exam notices; preserve last successful notices on failure."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
from app.official_exams import sources,fetch_notices
from app.public_archive import retain_public_records
from app.news_numbers import news_number,number_index

OUTPUT=Path('public/exam-notices.json')

def main():
    previous=json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    old=previous.get('items',[]);stamp=datetime.now(timezone.utc).isoformat()
    def collect(source):
        state=dict(source,checked_at=stamp)
        try:
            items=fetch_notices(source)
            state['status']='available' if items else 'no_extractable_notices'
            state['error']=None
            if not items:items=[r for r in old if r.get('exam_authority')==source['id']]
            else:state['last_success_at']=stamp
        except Exception as error:
            state.update(status='unavailable',error=type(error).__name__)
            items=[r for r in old if r.get('exam_authority')==source['id']]
        if not state.get('last_success_at'):
            state['last_success_at']=next((s.get('last_success_at') for s in previous.get('sources',[]) if s['id']==source['id']),None)
        state['notice_count']=len(items)
        return state,items
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(collect,[s for s in sources() if s.get('enabled')]))
    items={row['url']:row for _,batch in results for row in batch}
    for row in items.values():row['news_number']=news_number(row)
    number_index(items.values())
    payload={'checked_at':stamp,'sources':[s for s,_ in results],'items':list(items.values()),
      'notice':'Only official source-linked notices. Collection time is not the publication date. This is not a complete census of every Indian examination.'}
    retain_public_records(payload['items'])
    OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n')
    for s in payload['sources']:print(s['name'],s['status'],s['notice_count'])

if __name__=='__main__':main()
