import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch,MagicMock
from werkzeug.security import generate_password_hash
from api import index as api
from app.database import NewsDatabase
from app.models import NewsItem
from app import live_publication as live
from app.remote_admin_bridge import bridge_headers,_REPLAY
from app.phone_publication import delivery_status

KEY='isolated-live-publication-key-1234567890'


class LivePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.password='isolated-live-owner-password';cls.verifier=generate_password_hash(cls.password)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=NewsDatabase(str(Path(self.tmp.name)/'phone.db'))
        self.env=patch.dict(os.environ,{'VERCEL':'','POLITICSHUB_LOCAL_ADMIN':'1','POLITICSHUB_ADMIN_BRIDGE_SECRET':KEY,'ADMIN_USERS_JSON':json.dumps({'pushkarthawari':self.verifier,'other':self.verifier})});self.env.start()
        api._ensure_admin_users(self.db);self.factory=patch.object(api,'db',return_value=self.db);self.factory.start();self.closer=patch.object(self.db,'close');self.closer.start()
        api._ADMIN_LOGIN_RATE.clear();api._PUBLIC_RATE.clear();_REPLAY.clear()
        self.client=api.app.test_client();login=self.client.post('/api/admin/login',json={'username':'pushkarthawari','password':self.password});self.assertEqual(login.status_code,200)
        self.headers={'X-CSRF-Token':login.json['csrf_token']}
    def tearDown(self):self.closer.stop();self.factory.stop();self.env.stop();self.db.close();self.tmp.cleanup()
    def body(self,**kw):
        body={'title':'Original uploaded report explains a new public service schedule','summary':'An original summary explains the public service schedule and the source information available for residents.','article':'The public notice explains how residents can find the revised service arrangements and official contact information. '*8,'source_url':'https://example.org/official-notice','source_name':'PoliticsHub Editorial','category':'india','publish_now':True,'request_id':str(uuid.uuid4())};body.update(kw);return body
    def create(self,**kw):
        response=self.client.post('/api/admin/news/create',json=self.body(**kw),headers=self.headers);self.assertEqual(response.status_code,201,response.data);return response.json
    def signed(self,path,body=None):
        raw=json.dumps(body,separators=(',',':')).encode() if body is not None else b'';headers=bridge_headers(KEY,'POST' if body is not None else 'GET',path,raw)
        if body is not None:headers['Content-Type']='application/json'
        response=self.client.open(path,method='POST' if body is not None else 'GET',data=raw,headers=headers)
        self.assertEqual(response.headers.get('X-PH-Public-Signature'),live.proof(KEY,headers['X-PH-Bridge-Nonce'],response.data))
        return response
    def test_publish_now_creates_published_story_without_ssh_and_preserves_body(self):
        row=self.create();self.assertEqual(row['status'],'published');self.assertEqual(row['public_delivery']['channel'],'phone_bridge');self.assertEqual(row['public_delivery']['state'],'verifying')
        self.assertEqual(self.db.get_by_id(row['id'])['bot_article'],self.body()['article'].strip())
        self.assertTrue(live.is_public_id(row['public_delivery']['public_id']))
    def test_unsigned_service_access_cannot_export_private_data(self):
        self.assertEqual(self.client.get('/api/phone-public/feed').status_code,403)
        self.create(publish_now=False)
        published=self.create()
        row=self.db.get_by_id(published['id']);self.db.update(row['id'],fact_check_notes='PRIVATE-EVIDENCE-CANARY')
        feed=self.signed('/api/phone-public/feed');self.assertEqual(feed.status_code,200)
        self.assertEqual(len(feed.json['stories']),1);self.assertNotIn('PRIVATE-EVIDENCE',feed.text);self.assertNotIn('approved_at',feed.text);self.assertNotIn('password',feed.text)
        article=self.signed('/api/phone-public/article/'+str(live.public_id(row['id'])));self.assertEqual(article.status_code,200);self.assertIn('public notice',article.json['story']['bot_article'])
    def test_receipt_requires_current_revision_and_overrides_only_archive_failure(self):
        created=self.create();sid=created['id'];row=dict(self.db.get_by_id(sid));export=live.export_row(row)
        bad=self.signed('/api/phone-public/receipt',{'item_id':sid,'revision':'wrong'});self.assertEqual(bad.status_code,409)
        good=self.signed('/api/phone-public/receipt',{'item_id':sid,'revision':export['public_revision']});self.assertEqual(good.status_code,200)
        self.db.conn.execute("UPDATE ph_public_delivery SET state='failed' WHERE item_id=?",(sid,));self.db.conn.commit()
        status=delivery_status(self.db,sid);self.assertEqual(status['state'],'synced');self.assertEqual(status['archive_state'],'failed')
        self.db.update(sid,bot_article='Changed public manuscript')
        self.assertEqual(delivery_status(self.db,sid)['state'],'verifying')
    def test_draft_receives_no_public_page_and_retraction_stops_export(self):
        draft=self.create(publish_now=False)
        self.assertEqual(self.signed('/api/phone-public/article/'+str(live.public_id(draft['id']))).status_code,404)
        row=self.create();self.db.update(row['id'],status='rejected')
        self.assertEqual(self.signed('/api/phone-public/article/'+str(live.public_id(row['id']))).status_code,404)
    def test_lost_creation_response_retries_do_not_duplicate_articles(self):
        body=self.body();first=self.client.post('/api/admin/news/create',json=body,headers=self.headers);second=self.client.post('/api/admin/news/create',json=body,headers=self.headers)
        self.assertEqual(first.status_code,201,first.data);self.assertEqual(second.status_code,201,second.data);self.assertEqual(first.json['id'],second.json['id']);self.assertEqual(self.db.count(),1)
        bad=self.client.post('/api/admin/news/create',json=dict(body,title='A different article using an already committed request'),headers=self.headers);self.assertEqual(bad.status_code,409)
    def test_latest_approval_is_primary_without_changing_original_source_date(self):
        one=self.create();two=self.create(title='A different newly reported district water notice for residents')
        self.db.update(one['id'],published_at='2026-10-01T00:00:00Z',published_at_site='2026-10-01T00:00:00Z')
        self.client.post('/api/news/'+str(one['id'])+'/approve',json={},headers=self.headers)
        feed=self.signed('/api/phone-public/feed').json['stories'];ranked=api._rank_public(feed)
        self.assertEqual(ranked[0]['id'],live.public_id(one['id']));self.assertTrue(ranked[0]['editorial_featured']);self.assertEqual(self.db.get_by_id(one['id'])['published_at_site'],'2026-10-01T00:00:00Z')
        self.assertNotEqual(live.public_id(one['id']),live.public_id(two['id']))
    def test_model_namespace_supports_restored_large_private_ids(self):
        self.assertTrue(live.is_public_id(live.public_id(17484337268349)))
        self.assertLess(live.public_id(17484337268349),2**53)
    def test_reporters_cannot_bypass_role_with_publish_now(self):
        self.db.conn.execute("UPDATE admin_users SET role='reporter' WHERE username='other'");self.db.conn.commit()
        staff=api.app.test_client();login=staff.post('/api/admin/login',json={'username':'other','password':self.password})
        r=staff.post('/api/admin/news/create',json=self.body(),headers={'X-CSRF-Token':login.json['csrf_token']});self.assertEqual(r.status_code,403);self.assertEqual(self.db.count(),0)
    def test_website_confirmation_never_claims_success_before_public_api_matches(self):
        payload={'id':7,'status':'published','public_delivery':{'channel':'phone_bridge','revision':'a'*64}}
        response=MagicMock();response.__enter__.return_value=response;response.status=200
        response.read.return_value=json.dumps({'id':live.public_id(7),'public_revision':'b'*64}).encode()
        with patch.object(live,'build_opener') as opener,patch.object(live,'signed_read') as receipt:
            opener.return_value.open.return_value=response
            result=live.confirm_publication(payload)
            self.assertEqual(result['public_delivery']['state'],'verifying');receipt.assert_not_called()
        response.read.return_value=json.dumps({'id':live.public_id(7),'title':'Visible public article','category':'india','public_revision':'a'*64}).encode()
        with patch.object(live,'build_opener') as opener,patch.object(live,'signed_read',return_value=({'ok':True},200)):
            opener.return_value.open.return_value=response
            self.assertEqual(live.confirm_publication(payload)['public_delivery']['state'],'synced')
