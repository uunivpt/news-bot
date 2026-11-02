"""Bounded background model jobs keep slow phone inference outside HTTP requests."""
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from .editorial_store import ph,now
from .editorial_studio import model_draft

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='marathi-draft')
_slots=threading.BoundedSemaphore(2)


def submit_job(db,item_id,username,pack):
    from .phi4 import enabled
    if not enabled():raise RuntimeError('Model unavailable')
    if not _slots.acquire(blocking=False):raise RuntimeError('Draft queue full')
    job=secrets.token_hex(12);p=ph(db);stamp=now()
    try:
        db.conn.execute('INSERT INTO ph_studio_jobs(id,item_id,username,status,created_at,updated_at) VALUES ('+','.join([p]*6)+')',(job,item_id,username,'queued',stamp,stamp))
        if not db._postgres:db.conn.commit()
        _pool.submit(_run,job,pack,getattr(db,'database_url',None),str(getattr(db,'path','data/news.db')))
    except Exception:
        _slots.release();raise
    return job


def _run(job,pack,dsn,path):
    from .database import NewsDatabase
    db=None
    try:
        db=NewsDatabase(path,database_url=dsn,connect_attempts=1,statement_timeout=10000);p=ph(db)
        db.conn.execute("UPDATE ph_studio_jobs SET status='running',updated_at="+p+' WHERE id='+p,(now(),job))
        if not db._postgres:db.conn.commit()
        result=model_draft(pack)
        db.conn.execute("UPDATE ph_studio_jobs SET status='complete',draft_json="+p+',updated_at='+p+' WHERE id='+p,(json.dumps(result,ensure_ascii=False),now(),job))
        if not db._postgres:db.conn.commit()
    except Exception as exc:
        if db:
            p=ph(db)
            try:
                db.conn.execute("UPDATE ph_studio_jobs SET status='failed',error="+p+',updated_at='+p+' WHERE id='+p,(type(exc).__name__,now(),job))
                if not db._postgres:db.conn.commit()
            except Exception:pass
    finally:
        if db:db.close()
        _slots.release()


def job_payload(row):
    status=row['status']
    if status in {'queued','running'}:
        try:
            age=datetime.now(timezone.utc)-datetime.fromisoformat(row['updated_at'])
            if age>timedelta(minutes=5):status='interrupted'
        except ValueError:status='interrupted'
    draft=json.loads(row['draft_json']) if status=='complete' and row.get('draft_json') else None
    return {'job_id':row['id'],'status':status,'draft':draft,'updated_at':row['updated_at'],
            'message':'Drafting failed or was interrupted. Your saved article was not changed.' if status in {'failed','interrupted'} else None}
