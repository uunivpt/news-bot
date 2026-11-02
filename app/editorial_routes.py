"""Authenticated editorial events, Marathi studio, claim evidence and updates."""
from contextlib import contextmanager
import json
import re
import secrets
from datetime import datetime,timezone
from urllib.parse import urlsplit
from flask import request,session,jsonify,g
from .editorial_store import ensure_editorial_schema,ph,now,insert_id,preserve_source
from .editorial_access import allowed_story,assign_story,scope_sql,table_exists,PRIMARY_OWNER
from .editorial_studio import source_rows,candidate_groups,source_pack,source_draft,model_draft,claims_for,FIELDS,preserved_rows,words
from .monetization import review_fingerprint
from .admin_workspace import editorial_revision
from .source_http import public_http_url
from .source_text import source_text


def register_editorial_routes(app,factory,authorize,csrf,rate_limit):
    @contextmanager
    def storage(write=False):
        db=factory()
        try:
            if write:ensure_editorial_schema(db)
            yield db
        finally:db.close()

    def gate(write=False):return authorize() or (csrf() if write else None)
    def error(message,status=400):return jsonify({'error':message}),status
    def policy():return getattr(g,'admin_policy',None)
    def username():return session.get('admin_user') or 'API administrator'
    def allowed(db,sid):return allowed_story(db,sid,policy(),username())
    def story(db,sid):
        row=db.get_by_id(sid)
        return dict(row) if row is not None and allowed(db,sid) else None
    def chosen(db,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=10:raise ValueError('Select 1–10 source stories.')
        result=[]
        for value in dict.fromkeys(ids):
            if not isinstance(value,int) or isinstance(value,bool):raise ValueError('Invalid story selection.')
            row=story(db,value)
            if not row:raise ValueError('A selected story is unavailable or outside your access.')
            result.append(row)
        return result
    def body_text(body,key,minimum,maximum):
        value=source_text(body.get(key))
        if not minimum<=len(value)<=maximum:raise ValueError(f'{key}: use {minimum}–{maximum} characters.')
        return value
    def public_url(value):
        value=str(value or '').strip()
        if not value.startswith('https://') or not public_http_url(value):raise ValueError('A public HTTPS source URL is required.')
        return value
    def revision_check(item,body):
        if body.get('revision')!=editorial_revision(item):raise ValueError('This story changed. Reload the studio before saving.')
    def event_data(db,event):
        p=ph(db);restriction,args=scope_sql(db,policy(),username(),'n')
        rows=[dict(r) for r in db.conn.execute('SELECT '+','.join('n.'+x for x in FIELDS.split(','))+' FROM news_items n JOIN ph_editorial_event_items e ON e.item_id=n.id WHERE e.event_id='+p+(' AND '+restriction if restriction else '')+' ORDER BY n.id DESC',(event['id'],*args)).fetchall()]
        return dict(event,stories=rows,source_pack=source_pack(preserved_rows(db,rows))) if rows else None

    @app.get('/api/admin/editorial/sources')
    def editorial_sources():
        err=gate()
        if err:return err
        with storage() as db:
            rows,count=source_rows(db,policy(),username(),request.args.get('search',''),100)
            return jsonify({'stories':rows,'total':count,'limit':100,'scope':'Newest 100 matching accessible database stories'})

    @app.get('/api/admin/editorial/events')
    def editorial_events():
        err=gate()
        if err:return err
        with storage() as db:
            events=[]
            if table_exists(db,'ph_editorial_events'):
                for raw in db.conn.execute('SELECT * FROM ph_editorial_events ORDER BY updated_at DESC LIMIT 50').fetchall():
                    value=event_data(db,dict(raw))
                    if value:events.append(value)
            rows,total=source_rows(db,policy(),username(),request.args.get('search',''),200)
            return jsonify({'events':events,'suggestions':candidate_groups(rows),'suggestion_scope':f'Lexical candidates among {len(rows)} recent matching stories; editor grouping is required. Cross-language events may need manual grouping.','source_total':total})

    @app.post('/api/admin/editorial/events')
    def create_editorial_event():
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            try:
                title=body_text(body,'title',3,300);rows=chosen(db,body.get('story_ids'))
            except (ValueError,TypeError) as exc:return error(str(exc))
            p=ph(db);eid=secrets.token_hex(12);stamp=now()
            transaction=db.conn.transaction() if db._postgres else db.conn
            with transaction:
                db.conn.execute('INSERT INTO ph_editorial_events(id,title,category,created_by,created_at,updated_at) VALUES ('+','.join([p]*6)+')',(eid,title,rows[0]['category'],username(),stamp,stamp))
                for row in rows:db.conn.execute('INSERT INTO ph_editorial_event_items(event_id,item_id) VALUES ('+p+','+p+')',(eid,row['id']))
                db.log_activity(username(),'editorial.event.create',details=eid)
            return jsonify({'ok':True,'id':eid}),201

    @app.post('/api/admin/editorial/events/<event_id>/sources')
    def extend_editorial_event(event_id):
        err=gate(True)
        if err:return err
        with storage(True) as db:
            p=ph(db);raw=db.conn.execute('SELECT * FROM ph_editorial_events WHERE id='+p,(event_id,)).fetchone()
            if not raw or not event_data(db,dict(raw)):return error('Event not found.',404)
            # A scoped editor cannot modify another editor's mixed-desk event.
            if policy() and raw['created_by']!=username():return error('Only the event creator or an unrestricted editor can change this group.',403)
            try:rows=chosen(db,(request.get_json() or {}).get('story_ids'))
            except (ValueError,TypeError) as exc:return error(str(exc))
            transaction=db.conn.transaction() if db._postgres else db.conn
            with transaction:
                for row in rows:db.conn.execute('INSERT INTO ph_editorial_event_items(event_id,item_id) VALUES ('+p+','+p+') ON CONFLICT DO NOTHING',(event_id,row['id']))
                db.conn.execute('UPDATE ph_editorial_events SET updated_at='+p+' WHERE id='+p,(now(),event_id))
                db.log_activity(username(),'editorial.event.sources',details=event_id)
            return jsonify({'ok':True})

    @app.get('/api/admin/studio/<int:item_id>')
    def studio_read(item_id):
        err=gate()
        if err:return err
        with storage() as db:
            item=story(db,item_id)
            if not item:return error('Story not found.',404)
            sources={item_id:item};events=[];p=ph(db)
            if table_exists(db,'ph_editorial_events'):
                for event in db.conn.execute('SELECT e.* FROM ph_editorial_events e JOIN ph_editorial_event_items i ON i.event_id=e.id WHERE i.item_id='+p,(item_id,)).fetchall():
                    data=event_data(db,dict(event))
                    if data:
                        events.append({'id':data['id'],'title':data['title']})
                        for row in data['stories']:sources[row['id']]=row
            updates=[dict(r) for r in db.conn.execute('SELECT * FROM ph_editorial_updates WHERE item_id='+p+' ORDER BY id DESC',(item_id,)).fetchall()] if table_exists(db,'ph_editorial_updates') else []
            owner=db.conn.execute('SELECT username FROM ph_story_owners WHERE item_id='+p,(item_id,)).fetchone() if table_exists(db,'ph_story_owners') else None
            jobs=[dict(r) for r in db.conn.execute('SELECT id,status,updated_at FROM ph_studio_jobs WHERE item_id='+p+' AND username='+p+' ORDER BY created_at DESC LIMIT 5',(item_id,username())).fetchall()] if table_exists(db,'ph_studio_jobs') else []
            from .phi4 import enabled
            pack=source_pack(preserved_rows(db,list(sources.values())))
            suggestions=[dict(r,label=r['headline'],body=r['text'],confirmed_event=True) for r in pack['reports'] if r['id']!=item_id and int(r['id'])>item_id]
            recent,_=source_rows(db,policy(),username(),limit=200)
            original=preserved_rows(db,[item])[0];tokens=words(original['title'])
            for candidate in recent:
                if candidate['id']<=item_id or candidate['id'] in sources or candidate['category']!=item['category']:continue
                other=words(candidate['title'])
                if len(tokens&other)/max(1,len(tokens|other))<.28:continue
                report=source_pack([candidate])['reports'][0]
                suggestions.append(dict(report,label=report['headline'],body=report['text'],confirmed_event=False))
                if len(suggestions)>=10:break
            return jsonify({'story':{k:item.get(k) for k in ('id','title','summary','bot_summary','bot_article','category','url','source_name','status','image_url','image_license','image_credit')},
                            'revision':editorial_revision(item),'source_pack':pack,'events':events,'claims':claims_for(db,item),'updates':updates,
                            'assigned_to':owner['username'] if owner else None,'model_configured':enabled(),'jobs':jobs,
                            'suggested_updates':suggestions})

    @app.post('/api/admin/studio/<int:item_id>/prepare')
    def studio_prepare(item_id):
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            try:rows=chosen(db,body.get('story_ids') or [item_id])
            except (ValueError,TypeError) as exc:return error(str(exc))
            if item_id not in [r['id'] for r in rows]:return error('The primary story must remain in the source selection.')
            for row in rows:preserve_source(db,row)
            pack=source_pack(preserved_rows(db,rows))
            if body.get('mode')=='model':
                if not rate_limit(4,60):return error('Please wait before generating another draft.',429)
                from .phi4 import enabled
                if not enabled():return error('Automatic Marathi drafting is not configured. Use the source outline or manual editor.',503)
                from .studio_jobs import submit_job
                try:job_id=submit_job(db,item_id,username(),pack)
                except RuntimeError:return error('The drafting queue is busy. Try again shortly.',429)
                return jsonify({'ok':True,'job_id':job_id,'status':'queued'}),202
        result=source_draft(pack)
        return jsonify({'ok':True,'draft':result,'source_pack':pack})

    @app.get('/api/admin/studio/<int:item_id>/jobs/<job_id>')
    def studio_job(item_id,job_id):
        err=gate()
        if err:return err
        with storage() as db:
            if not story(db,item_id) or not table_exists(db,'ph_studio_jobs'):return error('Draft job not found.',404)
            p=ph(db);row=db.conn.execute('SELECT * FROM ph_studio_jobs WHERE id='+p+' AND item_id='+p,(job_id,item_id)).fetchone()
            if not row or row['username']!=username():return error('Draft job not found.',404)
            from .studio_jobs import job_payload
            return jsonify(job_payload(dict(row)))

    @app.post('/api/admin/studio/<int:item_id>/save')
    def studio_save(item_id):
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            item=story(db,item_id)
            if not item:return error('Story not found.',404)
            if item['status']=='published':return error('This article is published. Use the update/correction workflow to preserve its public history.',409)
            try:
                revision_check(item,body)
                title=body_text(body,'title',3,500);summary=body_text(body,'summary',1,6000);article=body_text(body,'article',1,50000)
                category=str(body.get('category') or item['category'])
                from .editorial_access import DESKS
                if category not in DESKS:raise ValueError('Select a valid desk.')
                if policy() and policy()['categories'] and category not in policy()['categories']:return error('That desk is outside your assigned access.',403)
                image=str(body.get('image_url') or '').strip();licence=str(body.get('image_license') or '');credit=source_text(body.get('image_credit'))[:300]
                if image:public_url(image)
                if image and (licence not in {'licensed','rights-owned','cc0','pdm'} or not credit):raise ValueError('An image needs a licence and credit.')
            except ValueError as exc:return error(str(exc),409 if 'changed' in str(exc) else 400)
            preserve_source(db,item)
            p=ph(db)
            conditions=' AND '.join(f"COALESCE({key},'')={p}" for key in ('title','bot_summary','bot_article','status','approved_at'))
            cursor=db.conn.execute('UPDATE news_items SET title='+p+',bot_summary='+p+',bot_article='+p+',category='+p+',image_url='+p+',image_license='+p+',image_credit='+p+",status='pending',fact_check_status='pending',approved_at=NULL,fact_check_notes='' WHERE id="+p+' AND '+conditions,
                (title,summary,article,category,image,licence,credit,item_id,*(str(item.get(key) or '') for key in ('title','bot_summary','bot_article','status','approved_at'))))
            if not db._postgres:db.conn.commit()
            if cursor.rowcount!=1:return error('This story changed during your save. Reload it.',409)
            db.log_activity(username(),'editorial.studio.save',item_id,'Draft saved; no publication or independent verification performed')
            return jsonify({'ok':True,'id':item_id,'status':'pending'})

    @app.post('/api/admin/editorial/story/<int:item_id>/assign')
    def editorial_assign(item_id):
        err=gate(True)
        if err:return err
        target=str((request.get_json() or {}).get('username') or '')
        with storage() as db:
            p=ph(db)
            if not db.get_by_id(item_id):return error('Story not found.',404)
            row=db.conn.execute('SELECT role FROM admin_users WHERE username='+p,(target,)).fetchone()
            if not row or row['role']=='disabled':return error('Select an active team member.')
            assign_story(db,item_id,target);db.log_activity(username(),'editorial.assign',item_id,target)
            return jsonify({'ok':True})

    @app.post('/api/admin/editorial/story/<int:item_id>/claims')
    def editorial_claim(item_id):
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            item=story(db,item_id)
            if not item:return error('Story not found.',404)
            try:statement=body_text(body,'statement',3,1500)
            except ValueError as exc:return error(str(exc))
            p=ph(db);stamp=now()
            claim_id=insert_id(db,'INSERT INTO ph_story_claims(item_id,statement,assessment,content_revision,created_by,created_at,updated_at) VALUES ('+','.join([p]*7)+')',(item_id,statement,'insufficient',review_fingerprint(item),username(),stamp,stamp))
            if not db._postgres:db.conn.commit()
            db.log_activity(username(),'editorial.claim.create',item_id,str(claim_id))
            return jsonify({'ok':True,'id':claim_id}),201

    @app.post('/api/admin/editorial/story/<int:item_id>/claims/<int:claim_id>')
    def editorial_evidence(item_id,claim_id):
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            item=story(db,item_id);p=ph(db)
            claim=db.conn.execute('SELECT * FROM ph_story_claims WHERE id='+p+' AND item_id='+p,(claim_id,item_id)).fetchone()
            if not item or not claim:return error('Claim not found.',404)
            try:
                url=public_url(body.get('source_url'));publisher=body_text(body,'publisher',1,200);excerpt=body_text(body,'excerpt',3,4000)
                stance=body.get('stance');assessment=body.get('assessment')
                if stance not in {'supports','disputes','context'} or assessment not in {'supported','disputed','insufficient'}:raise ValueError('Select an evidence stance and editorial assessment.')
            except ValueError as exc:return error(str(exc))
            stamp=now();transaction=db.conn.transaction() if db._postgres else db.conn
            with transaction:
                insert_id(db,'INSERT INTO ph_claim_evidence(claim_id,source_url,publisher,excerpt,stance,recorded_by,created_at) VALUES ('+','.join([p]*7)+')',(claim_id,url,publisher,excerpt,stance,username(),stamp))
                db.conn.execute('UPDATE ph_story_claims SET assessment='+p+',content_revision='+p+',updated_at='+p+' WHERE id='+p,(assessment,review_fingerprint(item),stamp,claim_id))
                db.log_activity(username(),'editorial.claim.evidence',item_id,str(claim_id))
            return jsonify({'ok':True,'note':'Recorded editor-supplied evidence and assessment; this does not claim automated or independent verification.'})

    @app.post('/api/admin/editorial/story/<int:item_id>/updates')
    def editorial_update(item_id):
        err=gate(True)
        if err:return err
        body=request.get_json() or {}
        with storage(True) as db:
            item=story(db,item_id)
            if not item:return error('Story not found.',404)
            try:
                label=body_text(body,'label',3,250);copy=body_text(body,'body',3,6000);url=public_url(body.get('source_url'));kind=body.get('kind','update')
                if kind not in {'update','correction'}:raise ValueError('Select update or correction.')
                revision_check(item,body)
            except ValueError as exc:return error(str(exc),409 if 'changed' in str(exc) else 400)
            p=ph(db);uid=insert_id(db,'INSERT INTO ph_editorial_updates(item_id,label,body,kind,source_url,status,created_by,created_at,base_revision) VALUES ('+','.join([p]*9)+')',(item_id,label,copy,kind,url,'pending',username(),now(),review_fingerprint(item)))
            if not db._postgres:db.conn.commit()
            db.log_activity(username(),'editorial.update.propose',item_id,str(uid))
            return jsonify({'ok':True,'id':uid,'status':'pending'}),201

    @app.post('/api/admin/editorial/story/<int:item_id>/updates/<int:update_id>/publish')
    def publish_editorial_update(item_id,update_id):
        err=gate(True)
        if err:return err
        with storage(True) as db:
            p=ph(db);transaction=db.conn.transaction() if db._postgres else db.conn
            with transaction:
                if not db._postgres:db.conn.execute('BEGIN IMMEDIATE')
                row=db.conn.execute('SELECT * FROM news_items WHERE id='+p+(' FOR UPDATE' if db._postgres else ''),(item_id,)).fetchone()
                update=db.conn.execute('SELECT * FROM ph_editorial_updates WHERE id='+p+' AND item_id='+p,(update_id,item_id)).fetchone()
                if not row or not update or not allowed(db,item_id):return error('Update not found.',404)
                item=dict(row);update=dict(update)
                if update['status']!='published':
                    if item['status']!='published':return error('Publish the main article with Verify first.',409)
                    if update['base_revision']!=review_fingerprint(item):return error('The article changed after this proposal. Review it and create a fresh proposal.',409)
                    stamp=now();local=datetime.fromisoformat(stamp).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %H:%M IST')
                    article=str(item.get('bot_article') or item.get('summary') or '').rstrip()+f"\n\n{'Correction' if update['kind']=='correction' else 'Update'} — {local}\n{update['label']}\n{update['body']}\nSource: {update['source_url']}"
                    if len(article)>50000:return error('Article reached the editorial body limit; create a follow-up report.',409)
                    db.conn.execute('UPDATE news_items SET bot_article='+p+',fact_check_notes='+p+' WHERE id='+p,(article,'Editor approved this public update. Independent verification and originality were not established by this action.',item_id))
                    db.conn.execute("UPDATE ph_editorial_updates SET status='published',published_by="+p+',published_at='+p+' WHERE id='+p,(username(),stamp,update_id))
                    db.log_activity(username(),'editorial.update.publish',item_id,str(update_id))
            try:
                from .phone_publication import deliver_publication
                delivery=deliver_publication(item_id,database=db)
            except Exception:delivery={'state':'failed','last_error':'Delivery unavailable'}
            return jsonify({'ok':True,'status':'published','public_delivery':delivery})

    @app.get('/api/admin/editorial/readiness')
    def ads_readiness():
        err=gate()
        if err:return err
        try:page=max(1,int(request.args.get('page',1)))
        except ValueError:return error('Invalid page.')
        from .ads_readiness import readiness
        with storage() as db:return jsonify(readiness(db,page))

    @app.post('/api/admin/editorial/readiness/probe')
    def ads_readiness_probe():
        err=gate(True)
        if err:return err
        if not rate_limit(4,60):return error('Please wait before checking again.',429)
        from .ads_readiness import live_probe
        return jsonify(live_probe())
