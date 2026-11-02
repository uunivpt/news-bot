from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from app.database import NewsDatabase
from app.editorial_store import ensure_editorial_schema
from app.studio_jobs import submit_job,job_payload
from app.ads_readiness import live_probe
from app.source_http import SourceDocument


class EditorialJobTests(unittest.TestCase):
    def test_background_model_job_persists_result_without_approving_a_story(self):
        with tempfile.TemporaryDirectory() as folder:
            db=NewsDatabase(str(Path(folder)/'jobs.db'));ensure_editorial_schema(db)
            try:
                draft={'headline':'मूळ स्रोतावरील बातमी','summary':'सारांश','article':'उपलब्ध माहितीवर आधारित मराठी मसुदा','needs_editor_review':True}
                with patch('app.phi4.enabled',return_value=True),patch('app.studio_jobs.model_draft',return_value=draft):
                    jid=submit_job(db,45,'fixture_owner',{'reports':[]})
                    row=None
                    for _ in range(100):
                        row=dict(db.conn.execute('SELECT * FROM ph_studio_jobs WHERE id=?',(jid,)).fetchone())
                        if row['status'] in {'complete','failed'}:break
                        time.sleep(.02)
                    self.assertEqual(row['status'],'complete',row)
                    self.assertEqual(job_payload(row)['draft'],draft)
                    self.assertEqual(db.count(),0)
            finally:db.close()
    def test_failed_model_job_never_stores_raw_credentials_in_error(self):
        with tempfile.TemporaryDirectory() as folder:
            db=NewsDatabase(str(Path(folder)/'jobs.db'));ensure_editorial_schema(db)
            try:
                with patch('app.phi4.enabled',return_value=True),patch('app.studio_jobs.model_draft',side_effect=ValueError('secret-api-key-never-store')):
                    jid=submit_job(db,45,'fixture_owner',{'reports':[]})
                    for _ in range(100):
                        row=dict(db.conn.execute('SELECT * FROM ph_studio_jobs WHERE id=?',(jid,)).fetchone())
                        if row['status']=='failed':break
                        time.sleep(.02)
                    self.assertEqual(row['status'],'failed');self.assertEqual(row['error'],'ValueError');self.assertNotIn('secret-api',str(row))
            finally:db.close()
    def test_interrupted_job_is_not_reported_as_success(self):
        row={'id':'fixture','status':'running','draft_json':None,'updated_at':(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()}
        result=job_payload(row);self.assertEqual(result['status'],'interrupted');self.assertIsNone(result['draft'])
    def test_http_probe_measures_responses_and_does_not_claim_google_crawler_health(self):
        def fetch(url,**kwargs):
            if url.endswith('/privacy.html'):raise TimeoutError('private request detail')
            body=b'google.com, pub-1752666987448533, DIRECT, f08c47fec0942fa0' if url.endswith('ads.txt') else b'User-agent: *\nAllow: /\n'
            return SourceDocument(url,body,'text/plain')
        with patch('app.ads_readiness.fetch_source',side_effect=fetch):report=live_probe()
        self.assertEqual(len(report['checks']),5)
        checks={c['path']:c for c in report['checks']}
        self.assertTrue(checks['/ads.txt']['publisher_id_present']);self.assertEqual(checks['/privacy.html']['status'],'unavailable_from_checker');self.assertEqual(checks['/privacy.html']['error'],'TimeoutError')
        self.assertNotIn('private request detail',str(report));self.assertIn('does not establish Google crawler',report['scope'])
