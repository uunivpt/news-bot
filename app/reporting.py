from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from .phase_system import phase_analytics


def operations_pdf(db, days=7):
    data = phase_analytics(db, days)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=34, leftMargin=34, topMargin=34, bottomMargin=34)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#555555")))
    story = [
        Paragraph("PoliticsHub — Operations Report", styles["Title"]),
        Paragraph(datetime.now(timezone.utc).strftime("Generated %Y-%m-%d %H:%M UTC"), styles["Small"]),
        Spacer(1, 14),
        Paragraph("System operational summary", styles["Heading2"]),
        Paragraph(
            f"Successful agent runs: {data['totals']['successes']} / {data['totals']['runs']} "
            f"({data['totals']['success_rate'] if data['totals']['success_rate'] is not None else 'n/a'}%). "
            "This is an operational completion metric, not a factual-truth score.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
    ]
    phase_rows=[["Phase","Area","Agents","Runs","Success rate"]]
    for p in data["phases"]:
        phase_rows.append([str(p["phase"]),p["name"],str(p["agents"]),str(p["runs"]),str(p["operational_success_rate"] if p["operational_success_rate"] is not None else "n/a")+"%"])
    t=Table(phase_rows,colWidths=[40,250,55,55,75],repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#202433")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d5d7de")),("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f6f8")])]))
    story += [t, Spacer(1,16), Paragraph("Agent performance", styles["Heading2"])]
    agent_rows=[["Agent","Phase","Runs","Success","Failed","Load","Avg sec"]]
    for a in data["agents"]:
        agent_rows.append([a["name"],str(a["phase"]),str(a["runs"]),str(a["successes"]),str(a["failed"]),str(a["current_load"]),str(a["avg_duration_seconds"])])
    at=Table(agent_rows,colWidths=[145,40,45,50,45,45,55],repeatRows=1)
    at.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#202433")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#d5d7de")),("FONTSIZE",(0,0),(-1,-1),7.5),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f6f8")])]))
    story += [at, Spacer(1,16), Paragraph("Quality notes", styles["Heading2"]), Paragraph("Research clustering, verification prechecks, agent training events, queue automation and public/Instagram publishing are tracked in the operational database. Human/source verification remains required for flagged stories.", styles["BodyText"])]
    doc.build(story)
    return buf.getvalue()
