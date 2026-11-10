import unittest
from datetime import datetime,timezone
from app.public_quality import quality_report

class QualityReportTests(unittest.TestCase):
    def test_counts_gaps_without_exposing_private_drafts(self):
        news=[{'id':1,'title':'Regional headline','url':'https://example.org/story','status':'published',
                'summary':'Brief text','bot_article':'','image_url':''},
              {'id':2,'title':'Regional headline','url':'javascript:alert(1)','status':'published',
                'summary':'Full, attributed news summary that contains plenty of context for readers. '*2,
                'bot_article':'Verified article text. '*600,'image_url':'/api/image/2'},
              {'id':3,'title':'Never publish draft','status':'pending'}]
        exams={'sources':[{'name':'Board A','status':'available','last_success_at':'2026-11-10T00:00:00Z'},
                          {'name':'Board B','status':'unavailable','notice_count':0}], 'items':[{'id':4}]}
        report=quality_report(news,exams,datetime(2026,11,10,12,tzinfo=timezone.utc))
        self.assertEqual(report['news']['total'],2)
        self.assertEqual(report['news']['source_briefs'],1)
        self.assertEqual(report['news']['with_image'],1)
        self.assertEqual(report['news']['repeated_headlines'],1)
        self.assertEqual(report['news']['unsafe_or_missing_source_link'],1)
        self.assertEqual(report['exams']['needs_manual_review'],1)
        self.assertEqual(report['exams']['notices'],1)
        self.assertNotIn('Never publish draft',str(report))
