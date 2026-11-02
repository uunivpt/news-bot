import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from api import index as api
from app.database import NewsDatabase
from app.models import NewsItem
from app.editorial_store import ensure_editorial_schema
from app.editorial_access import assign_story,save_policy
from app.editorial_studio import source_pack,model_draft


class EditorialFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password='isolated-editorial-owner-password';cls.verifier=generate_password_hash(cls.password)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=NewsDatabase(str(Path(self.temp.name)/'editorial.db'))
        self.env=patch.dict(os.environ,{'ADMIN_USERS_JSON':json.dumps({'pushkarthawari':self.verifier,'writer':self.verifier}),'PHI4_ENABLED':'false'});self.env.start();api._ensure_admin_users(self.db)
        self.factory=patch.object(api,'db',return_value=self.db);self.factory.start();self.close=patch.object(self.db,'close');self.close.start()
        api._ADMIN_LOGIN_RATE.clear();api._PUBLIC_RATE.clear()
        self.client=api.app.test_client();self.headers=self.login(self.client,'pushkarthawari')
        for index,(publisher,category,title) in enumerate([
            ('TV9 Marathi - Maharashtra','maharashtra','महाराष्ट्रातील पाणी पुरवठ्याबाबत प्रशासनाने 12 गावांसाठी नवीन वेळापत्रक जाहीर केले'),
            ('ABP Majha - Maharashtra','maharashtra','पाणी पुरवठ्यासाठी महाराष्ट्रातील 12 गावांचे नवीन वेळापत्रक प्रशासनाने जाहीर केले'),
            ('The Hindu - India','india','District administration announces updated water supply arrangements for 12 villages'),
        ]):
            self.db.insert(NewsItem(publisher,'rss',title,'https://example.org/editorial/'+str(index),summary='मूळ स्रोताचा तपशील: 12 गावांसाठी पाणी पुरवठ्याचे नवीन वेळापत्रक जाहीर करण्यात आले. स्थानिक प्रशासनाने सेवा कधी उपलब्ध होईल याची माहिती दिली.',published_at='2026-11-01T09:00:00Z',category=category,public_source=True))
        self.ids=[row['id'] for row in self.db.conn.execute('SELECT id FROM news_items ORDER BY id').fetchall()]
    def tearDown(self):
        self.close.stop();self.factory.stop();self.env.stop();self.db.close();self.temp.cleanup()
    def login(self,client,user):
        r=client.post('/api/admin/login',json={'username':user,'password':self.password});self.assertEqual(r.status_code,200,r.data);return {'X-CSRF-Token':r.json['csrf_token']}
    def post(self,path,data):return self.client.post(path,json=data,headers=self.headers)
    def studio(self,sid=None):return self.client.get('/api/admin/studio/'+str(sid or self.ids[0])).json
    def save(self,**changes):
        current=self.studio();row=current['story'];payload={'revision':current['revision'],'title':row['title'],'summary':row.get('bot_summary') or row['summary'],'article':'मराठी संपादकीय संदर्भ आणि उपलब्ध स्रोतांवर आधारित मसुदा. '*30,'category':row['category']};payload.update(changes)
        return self.post('/api/admin/studio/'+str(row['id'])+'/save',payload)
    def event(self):
        response=self.post('/api/admin/editorial/events',{'title':'पाणी पुरवठा वेळापत्रक','story_ids':self.ids});self.assertEqual(response.status_code,201,response.data);return response.json['id']

    def test_event_comparison_includes_real_sources_and_does_not_write_on_read(self):
        before=self.db.conn.total_changes;r=self.client.get('/api/admin/editorial/events');self.assertEqual(r.status_code,200);self.assertEqual(self.db.conn.total_changes,before)
        eid=self.event();event=self.client.get('/api/admin/editorial/events').json['events'][0]
        self.assertEqual(event['id'],eid);self.assertEqual(len(event['stories']),3)
        self.assertEqual({r['publisher'] for r in event['source_pack']['reports']},{'TV9 Marathi - Maharashtra','ABP Majha - Maharashtra','The Hindu - India'})
        self.assertEqual(len(self.studio()['source_pack']['reports']),3)
        self.assertEqual(self.db.conn.execute('SELECT COUNT(*) AS n FROM ph_editorial_events').fetchone()['n'],1)
    def test_studio_source_outline_and_save_preserve_original_and_require_current_revision(self):
        self.event();sid=self.ids[0];original=self.studio()['source_pack']['reports'][0]
        outline=self.post(f'/api/admin/studio/{sid}/prepare',{'story_ids':self.ids,'mode':'source'})
        self.assertEqual(outline.status_code,200);self.assertFalse(outline.json['draft']['translated']);self.assertIn('स्रोताधारित',outline.json['draft']['article']);self.assertTrue(outline.json['draft']['needs_editor_review'])
        previous=self.studio()['revision'];saved=self.save(title='महाराष्ट्रातील पाणी पुरवठ्याविषयी संपादकीय मसुदा')
        self.assertEqual(saved.status_code,200,saved.data)
        self.assertEqual(self.studio()['source_pack']['reports'][0]['headline'],original['headline'])
        self.assertEqual(self.studio()['story']['status'],'pending')
        stale=self.post(f'/api/admin/studio/{sid}/save',{'revision':previous,'title':'Old revision title','summary':'Summary','article':'Body'})
        self.assertEqual(stale.status_code,409)
    def test_evidence_assessments_become_stale_after_copy_changes(self):
        sid=self.ids[0];claim=self.post(f'/api/admin/editorial/story/{sid}/claims',{'statement':'नवीन वेळापत्रक 12 गावांना लागू आहे.'});self.assertEqual(claim.status_code,201)
        evidence=self.post(f'/api/admin/editorial/story/{sid}/claims/{claim.json["id"]}',{'source_url':'https://www.tv9marathi.com/report','publisher':'TV9 Marathi','excerpt':'नवीन वेळापत्रक 12 गावांना लागू आहे.','stance':'supports','assessment':'supported'})
        self.assertEqual(evidence.status_code,200,evidence.data);self.assertFalse(self.studio()['claims'][0]['stale'])
        self.assertEqual(self.save().status_code,200)
        self.assertTrue(self.studio()['claims'][0]['stale'])
        # Recorded assessment never silently becomes a factual-truth score.
        self.assertEqual(self.studio()['claims'][0]['assessment'],'supported')
        bad=self.post(f'/api/admin/editorial/story/{sid}/claims/{claim.json["id"]}',{'source_url':'http://127.0.0.1/private','publisher':'bad','excerpt':'Bad evidence','stance':'supports','assessment':'supported'})
        self.assertEqual(bad.status_code,400)
    def test_updates_publish_once_preserve_date_and_enter_public_delivery(self):
        sid=self.ids[0]
        self.assertEqual(self.post(f'/api/news/{sid}/approve',{}).status_code,200)
        original=dict(self.db.get_by_id(sid));self.assertEqual(self.save().status_code,409)
        proposal=self.post(f'/api/admin/editorial/story/{sid}/updates',{'revision':self.studio()['revision'],'label':'वेळापत्रकातील अद्ययावत माहिती','body':'प्रशासनाने पाणी पुरवठ्याच्या वेळेबद्दल अधिक माहिती दिली.','source_url':'https://example.org/official-update','kind':'correction'})
        self.assertEqual(proposal.status_code,201,proposal.data);uid=proposal.json['id']
        path=f'/api/admin/editorial/story/{sid}/updates/{uid}/publish'
        self.assertEqual(self.post(path,{}).status_code,200)
        once=dict(self.db.get_by_id(sid));self.assertEqual(once['published_at_site'],original['published_at_site']);self.assertIn('Correction —',once['bot_article']);self.assertIn('IST',once['bot_article']);self.assertIn('official-update',once['bot_article'])
        self.assertEqual(self.post(path,{}).status_code,200);self.assertEqual(self.db.get_by_id(sid)['bot_article'],once['bot_article'])
        self.assertEqual(self.studio()['updates'][0]['status'],'published')
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) AS count FROM admin_activity WHERE action='editorial.update.publish'").fetchone()['count'],1)
    def test_stale_update_proposal_cannot_overwrite_a_newer_article(self):
        sid=self.ids[0];self.post(f'/api/news/{sid}/approve',{})
        proposal=self.post(f'/api/admin/editorial/story/{sid}/updates',{'revision':self.studio()['revision'],'label':'New update','body':'Source updated report.','source_url':'https://example.org/update'})
        self.db.update(sid,bot_article='Another editor changed this body.')
        self.assertEqual(self.post(f'/api/admin/editorial/story/{sid}/updates/{proposal.json["id"]}/publish',{}).status_code,409)
    def test_custom_policy_filters_workspace_counts_queue_studio_and_mutations(self):
        sid=self.ids[0];assign_story(self.db,sid,'writer')
        response=self.post('/api/admin/users/writer',{'operation':'policy','permissions':['news.read','news.create','news.edit'],'categories':['maharashtra'],'own_only':True})
        self.assertEqual(response.status_code,200,response.data)
        staff=api.app.test_client();headers=self.login(staff,'writer')
        workspace=staff.get('/api/admin/workspace').json;self.assertEqual(workspace['stats']['total'],1);self.assertEqual(workspace['source_inventory']['total_stories'],1)
        queue=staff.get('/api/admin/stories').json;self.assertEqual(queue['total'],1);self.assertEqual(queue['stories'][0]['id'],sid)
        self.assertEqual(staff.get('/api/admin/studio/'+str(self.ids[1])).status_code,403)
        self.assertEqual(staff.post('/api/news/'+str(self.ids[2])+'/edit',json={'title':'Out of scope'},headers=headers).status_code,403)
        self.assertEqual(staff.get('/api/admin/editorial/readiness').status_code,403)
        self.assertEqual(staff.post('/api/admin/editorial/story/'+str(sid)+'/assign',json={'username':'writer'},headers=headers).status_code,403)
        bad=self.post('/api/admin/users/writer',{'operation':'policy','permissions':['news.read','users.manage'],'categories':[],'own_only':False});self.assertEqual(bad.status_code,400)
        bad=self.post('/api/admin/users/writer',{'operation':'policy','permissions':['news.read','reports.read'],'categories':['maharashtra'],'own_only':False});self.assertEqual(bad.status_code,400)
        self.assertEqual(staff.post('/api/news/'+str(sid)+'/edit',json={'category':'india'},headers=headers).status_code,403)
    def test_role_change_resets_custom_policy_and_source_choices_cannot_bypass_scope(self):
        assign_story(self.db,self.ids[0],'writer');save_policy(self.db,'writer',{'permissions':['news.read','news.edit'],'categories':['maharashtra'],'own_only':True})
        staff=api.app.test_client();headers=self.login(staff,'writer')
        denied=staff.post('/api/admin/editorial/events',json={'title':'Mixed event','story_ids':self.ids},headers=headers);self.assertEqual(denied.status_code,400)
        reset=self.post('/api/admin/users/writer',{'operation':'role','role':'publisher'});self.assertEqual(reset.status_code,200)
        self.assertEqual(staff.get('/api/admin/stories').json['total'],3)
        self.assertTrue(staff.get('/api/admin/workspace').json['capabilities']['publish'])
    def test_readiness_uses_actual_totals_and_never_claims_account_approval(self):
        before=self.db.conn.total_changes;r=self.client.get('/api/admin/editorial/readiness');self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(r.json['totals']['published'],0);self.assertEqual(self.db.conn.total_changes,before);self.assertTrue(r.json['ads_txt']['expected_line_present'])
        self.post(f'/api/news/{self.ids[0]}/approve',{})
        r=self.client.get('/api/admin/editorial/readiness');self.assertEqual(r.json['totals']['published'],1);self.assertFalse(r.json['articles'][0]['monetizable_under_local_rules']);self.assertIn('Google decides',r.json['notice'])
    def test_unconfigured_model_is_explicit_and_source_outline_still_works(self):
        sid=self.ids[0];r=self.post(f'/api/admin/studio/{sid}/prepare',{'mode':'model'});self.assertEqual(r.status_code,503)
        r=self.post(f'/api/admin/studio/{sid}/prepare',{'mode':'source'});self.assertEqual(r.status_code,200)
        self.assertEqual(self.db.get_by_id(sid)['status'],'pending')
    def test_claims_and_update_mutations_require_csrf_and_do_not_publish_incidentally(self):
        sid=self.ids[0]
        for path in (f'/api/admin/editorial/story/{sid}/claims',f'/api/admin/studio/{sid}/save','/api/admin/editorial/events'):
            self.assertEqual(self.client.post(path,json={}).status_code,403,path)
        self.assertTrue(all(r['status']=='pending' for r in self.db.latest()))
    def test_generated_numbers_not_present_in_sources_are_rejected(self):
        pack=source_pack([dict(self.db.get_by_id(self.ids[0]))])
        with patch('app.phi4._chat',return_value=json.dumps({'headline':'मराठी बातमी','summary':'माहिती','article':'नवीन 99999 गावांचा दावा'})):
            with self.assertRaisesRegex(ValueError,'unsupported numbers'):model_draft(pack)
