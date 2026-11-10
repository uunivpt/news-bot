"""Read-only editorial quality summary. No private manuscripts or user data."""
from collections import Counter
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit


def _valid_source(value):
    try:
        p=urlsplit(str(value or "").strip())
        return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def quality_report(news_rows, exam_payload, now=None):
    """Separate reader-facing source briefs from reviewed long-form copy."""
    clock=now or datetime.now(timezone.utc)
    news=[dict(x) for x in news_rows if isinstance(x,dict) and x.get("status","published")=="published"]
    exams=exam_payload if isinstance(exam_payload,dict) else {}
    sources=[x for x in exams.get("sources",[]) if isinstance(x,dict)]
    headlines=Counter(re.sub(r"\s+"," ",str(x.get("title") or "")).casefold().strip() for x in news)
    duplicates=sum(v-1 for k,v in headlines.items() if k and v>1)
    issues=[]
    image_count=article_count=longform_count=short_summary=bad_url=0
    for row in news:
        article=str(row.get("bot_article") or row.get("article") or "").strip()
        summary=str(row.get("bot_summary") or row.get("summary") or "").strip()
        image=bool(str(row.get("image_url") or "").strip())
        if article:article_count+=1
        if len(article.split())>=500:longform_count+=1
        if image:image_count+=1
        if len(summary)<80:short_summary+=1
        valid_url=_valid_source(row.get("url"))
        if not valid_url:bad_url+=1
        flags=[]
        if not article:flags.append("Source-linked brief only")
        if not image:flags.append("No rights-cleared image")
        if not valid_url:flags.append("Source link needs verification")
        if len(summary)<80:flags.append("Short summary")
        if flags and len(issues)<15:
            issues.append({"id":str(row.get("id") or ""),"title":str(row.get("title") or "")[:180],
                "flags":flags,"url":str(row.get("url") or "") if valid_url else ""})
    sources_unavailable=[]
    for source in sources:
        state=str(source.get("status") or "unknown")
        last=source.get("last_success_at")
        stale=state!="available"
        if last:
            try:
                date=datetime.fromisoformat(str(last).replace("Z","+00:00"))
                if date.tzinfo:stale=stale or (clock-date.astimezone(timezone.utc)).total_seconds()>48*3600
            except (ValueError,TypeError):stale=True
        else:stale=True
        if stale:
            sources_unavailable.append({"name":str(source.get("name") or "Official authority")[:120],
                "status":state,"last_success_at":last,"notice_count":int(source.get("notice_count") or 0)})
    available=sum(s.get("status")=="available" for s in sources)
    return {
        "checked_at":clock.isoformat(),
        "scope":"Current public news feed and configured official-exam sources, not all historical records.",
        "news":{"total":len(news),"with_article":article_count,"longform_500_plus":longform_count,
          "source_briefs":len(news)-article_count,"with_image":image_count,
          "missing_rights_cleared_image":len(news)-image_count,
          "short_summary":short_summary,"unsafe_or_missing_source_link":bad_url,
          "repeated_headlines":duplicates},
        "exams":{"authorities":len(sources),"available":available,
          "needs_manual_review":len(sources_unavailable),"notices":len(exams.get("items",[])),
          "issues":sources_unavailable},
        "sample_issues":issues,
        "note":"Missing source-owned images and short RSS briefs are quality signals, not permission to fabricate articles, rights or unverified deadlines."
    }
