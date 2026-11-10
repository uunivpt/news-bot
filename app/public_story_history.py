"""Public history contains only explicitly published editorial update records."""
from datetime import datetime,timezone,timedelta
from html import escape
from urllib.parse import urlsplit

def _when(value):
    try:
        value=str(value or "")
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError,ValueError,OverflowError):
        return None

def _safe_source(value):
    try:
        u=urlsplit(str(value or ""))
        return str(value) if u.scheme=="https" and u.hostname and not u.username and not u.password else ""
    except ValueError:
        return ""

def public_updates(row, db_factory, limit=12):
    """Never read pending editorial notes, creator identities, or hidden drafts."""
    if row.get("status","published")!="published" or not (row.get("approved_at") or row.get("source_type")=="manual"):
        return []
    try:
        item_id=int(row.get("id"))
        if item_id<=0:return []
    except (TypeError,ValueError):
        return []
    database=None
    try:
        database=db_factory()
        placeholder="%s" if database._postgres else "?"
        records=database.conn.execute(
            "SELECT kind,label,source_url,published_at FROM ph_editorial_updates "
            "WHERE item_id="+placeholder+" AND status='published' "
            "ORDER BY published_at DESC,id DESC LIMIT "+str(max(1,min(int(limit),25))),
            (item_id,)).fetchall()
        return [dict(r) for r in records if str(r["kind"]) in {"update","correction"} and _when(r["published_at"])]
    except Exception:
        # The public report must still load if the hosted history database is absent.
        return []
    finally:
        if database is not None:
            try:database.close()
            except Exception:pass

def newest_modified(updates, publication):
    published=_when(publication)
    now=datetime.now(timezone.utc)+timedelta(minutes=30)
    dates=[d for d in (_when(u.get("published_at")) for u in updates) if d and d<=now]
    latest=max(dates,default=None)
    return latest.isoformat() if latest and (not published or latest>published) else None

def render_history(updates):
    items=[]
    for update in updates:
        stamp=_when(update.get("published_at"))
        if not stamp or stamp>datetime.now(timezone.utc)+timedelta(minutes=30):continue
        title=escape(str(update.get("label") or "Editorial update")[:250])
        kind="Correction" if update.get("kind")=="correction" else "Update"
        label=stamp.strftime("%d %b %Y, %H:%M UTC")
        source=_safe_source(update.get("source_url"))
        src=('<a href="'+escape(source,quote=True)+'" target="_blank" rel="nofollow noopener noreferrer">Original supporting source</a>') if source else ""
        items.append('<li><strong>'+kind+'</strong> · <time datetime="'+escape(stamp.isoformat(),quote=True)+'">'+label+'</time><p>'+title+'</p>'+src+'</li>')
    if not items:return ""
    return '<section class="src" aria-labelledby="story-history-title"><h2 id="story-history-title">Published updates &amp; corrections</h2><ol>'+''.join(items)+'</ol><p>Only published editorial updates appear here. For other issues, see <a href="/corrections.html">Corrections</a>.</p></section>'
