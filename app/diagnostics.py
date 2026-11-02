"""Fresh, read-only diagnosis from the connected database, never a UI snapshot."""
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
import threading
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .source_inventory import source_inventory
from .advanced_system import resource_usage

_FONT_LOCK = threading.Lock()


def diagnosis(database, days=None, actor=''):
    started = datetime.now(timezone.utc)
    cutoff = (started - timedelta(days=days)).isoformat() if days else None
    p = '%s' if database._postgres else '?'
    report = {'generated_at': started.isoformat(), 'requested_by': actor,
              'scope': 'Live connected database; all-time news totals and full configured source inventory',
              'history_days': days or 'all', 'history_since': cutoff or 'All stored history', 'sections': {}, 'availability': {},
              'limits': {'history_rows_per_section': None, 'news_article_bodies': 'Not part of an operational diagnosis'},
              'sources': source_inventory(database), 'resources': resource_usage(database)}
    sections = report['sections']
    for label, column in [('Publication status','status'), ('Review status','fact_check_status'), ('News desks','category')]:
        sections[label] = [dict(row) for row in database.conn.execute(f'SELECT {column} AS name,COUNT(*) AS records FROM news_items GROUP BY {column} ORDER BY records DESC').fetchall()]
    sections['Content completeness'] = [dict(database.conn.execute("""SELECT COUNT(*) AS total,
        SUM(CASE WHEN COALESCE(NULLIF(bot_summary,''),summary,'')='' THEN 1 ELSE 0 END) AS missing_summary,
        SUM(CASE WHEN COALESCE(bot_article,'')='' THEN 1 ELSE 0 END) AS missing_body,
        SUM(CASE WHEN COALESCE(image_url,'')='' THEN 1 ELSE 0 END) AS missing_image,
        MAX(collected_at) AS latest_collection FROM news_items""").fetchone())]
    if database._postgres:
        sections['PostgreSQL durability'] = [dict(row) for row in database.conn.execute("SELECT name,setting FROM pg_settings WHERE name IN ('fsync','full_page_writes','synchronous_commit','transaction_read_only','server_version') ORDER BY name").fetchall()]
    checks = [
        ('Editorial event groups','ph_editorial_events','updated_at','id,title,category,created_by,created_at,updated_at'),
        ('Claim assessments','ph_story_claims','updated_at','id,item_id,statement,assessment,created_by,updated_at'),
        ('Claim source evidence','ph_claim_evidence','created_at','claim_id,publisher,source_url,excerpt,stance,recorded_by,created_at'),
        ('Updates and corrections','ph_editorial_updates','created_at','id,item_id,label,body,kind,source_url,status,created_by,created_at,published_by,published_at'),
        ('Agent run history','ph_agent_runs','started_at', 'agent_id,operation,status,duration_seconds,started_at'),
        ('Admin audit history','admin_activity','created_at','username,action,item_id,created_at'),
        ('Alerts','ph_alerts','created_at','severity,bot,step,item_id,resolved,created_at'),
        ('Failure history','ph_bot_failures','created_at','bot,item_id,step,attempt,action,resolved,created_at'),
        ('Website visibility receipts','ph_live_receipts','checked_at','item_id,public_url,checked_at'),
        ('Homepage editorial lead','ph_home_primary','featured_at','item_id,featured_at'),
        ('Publication archive delivery','ph_public_delivery','updated_at','item_id,state,attempts,updated_at,public_url'),
        ('Editorial scores','ph_news_scores','updated_at','item_id,score,freshness,coverage,importance,verification,updated_at'),
        ('Event groups','ph_events','updated_at','event_id,canonical_title,category,status,updated_at'),
    ]
    for label, table, date_column, columns in checks:
        try:
            exists = database.conn.execute("SELECT to_regclass('" + table + "') AS name").fetchone()['name'] if database._postgres else database.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                report['availability'][label] = {'status':'not_recorded', 'total':None}; continue
            total = int(database.conn.execute(f'SELECT COUNT(*) AS count FROM {table}').fetchone()['count'])
            where = f' WHERE {date_column}>={p}' if cutoff else ''
            params = (cutoff,) if cutoff else ()
            in_window = int(database.conn.execute(f'SELECT COUNT(*) AS count FROM {table}'+where, params).fetchone()['count'])
            data = [dict(row) for row in database.conn.execute(f'SELECT {columns} FROM {table}'+where+f' ORDER BY {date_column} DESC', params).fetchall()]
            report['availability'][label] = {'status':'available','total':total,'in_window':in_window,'included':len(data),'truncated':in_window>len(data)}
            sections[label] = data
            if label == 'Agent run history':
                sections['Agent totals (selected period)'] = [dict(row) for row in database.conn.execute(f"SELECT agent_id,status,COUNT(*) AS runs,AVG(duration_seconds) AS avg_seconds FROM {table}"+where+" GROUP BY agent_id,status ORDER BY agent_id,status", params).fetchall()]
        except Exception:
            # Failed measurements stay unavailable; they never become false zeroes.
            report['availability'][label] = {'status':'unavailable','total':None}
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    return report


def diagnosis_pdf(report):
    styles = getSampleStyleSheet()
    normal = styles['BodyText']; normal.fontSize = 8; normal.leading = 11
    with _FONT_LOCK:
        if 'DiagnosisUnicode' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DiagnosisUnicode', str(Path(__file__).parent/'fonts/NotoSansDevanagari.ttf')))
    normal.fontName = 'DiagnosisUnicode'
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=32, rightMargin=32, topMargin=34, bottomMargin=34,
                            title='PoliticsHub live diagnosis', author='PoliticsHub', pageCompression=1)
    content = [Paragraph('PoliticsHub — Live diagnosis report', styles['Title'])]
    def paragraph(value): return Paragraph(escape(str(value if value is not None else 'Unavailable')).replace('\n','<br/>'), normal)
    def table(rows):
        if not rows:
            content.append(paragraph('No records in this scope.')); return
        keys = list(dict.fromkeys(key for row in rows for key in row))
        # Vertical record format keeps every column readable even on A4/mobile.
        for index, row in enumerate(rows,1):
            data = [[paragraph(key.replace('_',' ').title()), paragraph(row.get(key))] for key in keys]
            t = LongTable(data, colWidths=[140,391], hAlign='LEFT')
            t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#eef3f0')),('LINEBELOW',(0,-1),(-1,-1),.3,colors.HexColor('#d0dad4')),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6)]))
            content.extend([t, Spacer(1,7)])
    for key in ('generated_at','completed_at','requested_by','scope','history_days','history_since'):
        content.append(paragraph(key.replace('_',' ').title() + ': ' + str(report[key])))
    content.append(paragraph('Captured on download. This report does not update after download. Missing telemetry is unavailable, not zero. No passwords, password hashes, API keys, session tokens or database connection credentials are included.'))
    content.append(paragraph('History details: all recorded entries in the selected period are included. All-time totals, complete source inventory and period totals are separately included. Article bodies are outside this operational report.'))
    for name, rows in report['sections'].items():
        content.extend([Spacer(1,14),Paragraph(escape(name),styles['Heading2'])])
        if name in report['availability']: table([report['availability'][name]])
        table(rows)
    for label, data in [('Database and media resources',report['resources']), ('Telemetry availability',report['availability'])]:
        content.extend([Spacer(1,14),Paragraph(label,styles['Heading2'])])
        for key,value in data.items():
            content.append(paragraph(key + ': ' + str(value)))
    content.extend([Spacer(1,14),Paragraph('Complete configured publisher inventory',styles['Heading2'])])
    table([{key:value for key,value in report['sources'].items() if key not in {'items'}}])
    table(report['sources']['items'])
    def footer(canvas, document):
        canvas.setFont('Helvetica',8);canvas.drawString(32,19,'Private operational report · ' + report['generated_at']);canvas.drawRightString(563,19,str(document.page))
    doc.build(content,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
