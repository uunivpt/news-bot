"""Consent-based PoliticsHub Brief email subscription and delivery.

No subscriber is activated until they click the confirmation button in their
email. A real SMTP credential and a durable database are required to send mail.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote
from zoneinfo import ZoneInfo

from itsdangerous import BadSignature, URLSafeSerializer

OWNER = "politicshub.in@gmail.com"
ORIGIN = "https://www.politicshub.in"
INDIA = ZoneInfo("Asia/Kolkata")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MAX_PER_DIGEST_RUN = 20
GENERIC_SIGNUP = "If the address is eligible, a confirmation link will arrive shortly. Please check your inbox and spam folder."

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS newsletter_optins (
      email TEXT PRIMARY KEY, subscriber_id TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL, verify_hash TEXT, requested_at TEXT NOT NULL,
      confirmed_at TEXT, welcome_sent_at TEXT, owner_sent_at TEXT,
      last_digest_on TEXT, last_manage_mail_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS newsletter_deliveries (
      subscriber_id TEXT NOT NULL, digest_day TEXT NOT NULL,
      status TEXT NOT NULL, attempted_at TEXT NOT NULL,
      completed_at TEXT, PRIMARY KEY (subscriber_id, digest_day))""",
)


def now_utc():
    return datetime.now(timezone.utc)


def iso(value=None):
    return (value or now_utc()).isoformat()


def valid_email(email):
    return bool(5 <= len(email) <= 254 and EMAIL_RE.fullmatch(email))


def mail_configured():
    return bool(os.getenv("GMAIL_APP_PASSWORD", "").strip())


def _commit(database):
    if not database._postgres:
        database.conn.commit()


def _ph(database):
    return "%s" if database._postgres else "?"


def ensure_tables(database):
    for ddl in SCHEMA:
        database.conn.execute(ddl)
    _commit(database)


def _row(row):
    return dict(row) if row else None


def _signer(secret):
    if not secret or len(str(secret)) < 16:
        raise RuntimeError("A durable signing key is required for newsletter links")
    return URLSafeSerializer(str(secret), salt="politicshub-newsletter-unsubscribe-v1")


def unsubscribe_token(subscriber_id, signing_key):
    return _signer(signing_key).dumps({"id": str(subscriber_id)})


def email_unsubscribe_link(subscriber_id, signing_key):
    return ORIGIN + "/newsletter/unsubscribe?token=" + quote(unsubscribe_token(subscriber_id, signing_key), safe="")


def lookup_unsubscribe(database, token, signing_key):
    if not token or len(token) > 1000:
        return None
    try:
        obj = _signer(signing_key).loads(token)
        ident = str(obj["id"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None
    ph = _ph(database)
    return _row(database.conn.execute(
        f"SELECT * FROM newsletter_optins WHERE subscriber_id = {ph} AND status = 'active'", (ident,)
    ).fetchone())


def _text_only(value, limit=500):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()[:limit]


def send_mail(to, subject, title, paragraphs, action=None, unsubscribe=None, one_click=False):
    """Send authenticated mail from the exact PoliticsHub Gmail identity."""
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not password:
        raise RuntimeError("Newsletter email delivery is not configured")
    recipient = to.strip().lower()
    if not valid_email(recipient):
        raise ValueError("Invalid email recipient")
    body_text = "\n\n".join(paragraphs)
    footer = "\n\nPoliticsHub.in | What matters, clearly."
    if action:
        body_text += "\n\n" + action[0] + ": " + action[1]
    if unsubscribe:
        footer += "\nUnsubscribe: " + unsubscribe
    msg = EmailMessage()
    msg["From"] = "PoliticsHub.in <" + OWNER + ">"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Reply-To"] = OWNER
    if unsubscribe:
        msg["List-Unsubscribe"] = "<" + unsubscribe.replace("/newsletter/unsubscribe?", "/api/newsletter/one-click?") + ">"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(title + "\n\n" + body_text + footer)
    message_parts = "".join("<p style='margin:0 0 16px;color:#333d48;line-height:1.6'>" +
                            html.escape(p) + "</p>" for p in paragraphs)
    action_html = ""
    if action:
        label, url = action
        action_html = "<p><a style='display:inline-block;background:#ed2939;color:white;padding:14px 20px;border-radius:8px;font-weight:700;text-decoration:none' href='" + html.escape(url, quote=True) + "'>" + html.escape(label) + "</a></p>"
    unsub_html = ("<a href='" + html.escape(unsubscribe, quote=True) + "' style='color:#aab1bb'>Unsubscribe</a>" if unsubscribe else "")
    page = ("<!doctype html><html><body style='margin:0;background:#f4f5f7;font-family:Arial,sans-serif'>"
        "<div style='max-width:560px;margin:30px auto;background:white;border-radius:14px;overflow:hidden'>"
        "<div style='background:#08090b;color:#fff;padding:26px 30px'><div style='font-size:26px;font-weight:900'>Politics<span style='color:#a3a3a3'>Hub</span><span style='color:#ed2939'>.in</span></div><div style='margin-top:8px;font-size:12px;letter-spacing:2px'>WHAT MATTERS, CLEARLY.</div></div>"
        "<div style='padding:30px'><h1 style='font-size:25px;line-height:1.2;color:#101114;margin:0 0 22px'>" + html.escape(title) + "</h1>"
        + message_parts + action_html +
        "</div><div style='background:#111;color:#aab1bb;padding:22px 30px;font-size:12px'>PoliticsHub.in — Independent, source-linked news.<br>" +
        unsub_html + "</div></div></body></html>")
    msg.add_alternative(page, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12, context=ssl.create_default_context()) as server:
        server.login(OWNER, password)
        server.send_message(msg)


def request_optin(database, email):
    """Prepare a pending request; never activate based on an unauthenticated POST."""
    ensure_tables(database)
    ph = _ph(database)
    old = _row(database.conn.execute(f"SELECT * FROM newsletter_optins WHERE email = {ph}", (email,)).fetchone())
    if old and old["status"] == "active":
        return None
    if old:
        try:
            last = datetime.fromisoformat(old["requested_at"].replace("Z", "+00:00"))
            if now_utc() - last < timedelta(minutes=30):
                return None
        except (ValueError, TypeError):
            pass
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    identifier = secrets.token_hex(16)
    timestamp = iso()
    if old:
        database.conn.execute(f"""UPDATE newsletter_optins SET subscriber_id={ph}, status='pending', verify_hash={ph},
        requested_at={ph}, confirmed_at=NULL, welcome_sent_at=NULL, owner_sent_at=NULL,
        last_digest_on=NULL, last_manage_mail_at=NULL WHERE email={ph}""",
        (identifier, digest, timestamp, email))
    else:
        database.conn.execute(f"""INSERT INTO newsletter_optins
        (email,subscriber_id,status,verify_hash,requested_at) VALUES ({ph},{ph},'pending',{ph},{ph})""",
        (email, identifier, digest, timestamp))
    _commit(database)
    return raw


def confirmation_link(raw_token):
    return ORIGIN + "/newsletter/confirm?token=" + quote(raw_token, safe="")


def confirm_optin(database, raw_token):
    ensure_tables(database)
    if not raw_token or len(raw_token) > 256:
        return None
    ph = _ph(database)
    hashed = hashlib.sha256(raw_token.encode()).hexdigest()
    row = _row(database.conn.execute(f"SELECT * FROM newsletter_optins WHERE verify_hash={ph} AND status='pending'", (hashed,)).fetchone())
    if not row:
        return None
    try:
        requested = datetime.fromisoformat(row["requested_at"].replace("Z", "+00:00"))
        if now_utc() - requested > timedelta(hours=48):
            return None
    except (TypeError, ValueError):
        return None
    database.conn.execute(f"""UPDATE newsletter_optins SET status='active', verify_hash=NULL,
       confirmed_at={ph} WHERE email={ph} AND verify_hash={ph} AND status='pending'""",
       (iso(), row["email"], hashed))
    _commit(database)
    return _row(database.conn.execute(f"SELECT * FROM newsletter_optins WHERE email={ph}", (row["email"],)).fetchone())


def unsubscribe(database, token, key):
    ensure_tables(database)
    row = lookup_unsubscribe(database, token, key)
    if not row:
        return False
    ph = _ph(database)
    database.conn.execute(f"DELETE FROM newsletter_optins WHERE subscriber_id={ph}", (row["subscriber_id"],))
    database.conn.execute(f"DELETE FROM newsletter_deliveries WHERE subscriber_id={ph}", (row["subscriber_id"],))
    database.unsubscribe_newsletter(row["email"])
    _commit(database)
    return True


def verified_story(rows):
    """Only recent source-linked, non-review articles; no invented/unsourced claims."""
    current = now_utc()
    for row in rows:
        title = _text_only(row.get("title"), 180)
        summary = _text_only(row.get("bot_summary") or row.get("summary"), 650)
        src = _text_only(row.get("source_name") or row.get("source"), 90)
        url = str(row.get("url") or "")
        published = row.get("published_at_site") or row.get("published_at")
        if row.get("fact_check_status") == "needs_review":
            continue
        if len(title.split()) < 5 or len(summary) < 75 or not src or not url.startswith("https://"):
            continue
        if not bool(row.get("public_source")):
            continue
        try:
            dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            if not timedelta(0) <= current - dt <= timedelta(hours=48):
                continue
        except (TypeError, ValueError):
            continue
        return {"title": title, "summary": summary, "source": src, "url": url}
    return None


def send_welcome(database, subscriber, story, key):
    if subscriber["welcome_sent_at"]:
        return
    unsub = email_unsubscribe_link(subscriber["subscriber_id"], key)
    paragraphs = [
        "Thank you for subscribing to PoliticsHub! We'll keep you updated with the latest verified news and a concise daily briefing.",
        "Today's story: " + story["title"] if story else "Our newsroom will send your first source-linked story when a fresh verified report is available.",
    ]
    if story:
        paragraphs += [story["summary"], "Source: " + story["source"]]
    send_mail(subscriber["email"], "Welcome to PoliticsHub Brief", "You're subscribed. Welcome aboard.", paragraphs,
              action=("Read today's source report", story["url"]) if story else ("Explore latest news", ORIGIN),
              unsubscribe=unsub)
    ph = _ph(database)
    database.conn.execute(f"UPDATE newsletter_optins SET welcome_sent_at={ph} WHERE subscriber_id={ph}", (iso(),subscriber["subscriber_id"]))
    _commit(database)


def send_owner_alert(database, subscriber):
    if subscriber["owner_sent_at"]:
        return
    send_mail(OWNER, "New PoliticsHub newsletter subscriber", "A reader just subscribed", [
        "New verified newsletter subscriber: " + subscriber["email"],
        "Confirmation time (UTC): " + str(subscriber["confirmed_at"]),
        "Manage subscriber removal requests from the PoliticsHub newsletter controls.",
    ])
    ph = _ph(database)
    database.conn.execute(f"UPDATE newsletter_optins SET owner_sent_at={ph} WHERE subscriber_id={ph}", (iso(),subscriber["subscriber_id"]))
    _commit(database)


def active_subscribers(database, limit=MAX_PER_DIGEST_RUN):
    ensure_tables(database)
    today = now_utc().astimezone(INDIA).strftime("%Y-%m-%d")
    ph = _ph(database)
    rows = database.conn.execute(f"""SELECT * FROM newsletter_optins
         WHERE status='active' AND confirmed_at IS NOT NULL AND
         (last_digest_on IS NULL OR last_digest_on <> {ph})
         ORDER BY COALESCE(last_digest_on,''), confirmed_at LIMIT {min(max(int(limit), 1), MAX_PER_DIGEST_RUN)}""", (today,)).fetchall()
    return [_row(x) for x in rows]


def claim_digest(database, subscriber_id, day):
    ph = _ph(database)
    cur = database.conn.execute(
        f"""INSERT INTO newsletter_deliveries (subscriber_id,digest_day,status,attempted_at)
            VALUES ({ph},{ph},'pending',{ph}) ON CONFLICT (subscriber_id,digest_day) DO NOTHING""",
        (subscriber_id, day, iso()))
    _commit(database)
    return cur.rowcount == 1


def finish_digest(database, subscriber_id, day, sent):
    ph = _ph(database)
    database.conn.execute(
        f"UPDATE newsletter_deliveries SET status={ph},completed_at={ph} WHERE subscriber_id={ph} AND digest_day={ph}",
        ("sent" if sent else "failed", iso(), subscriber_id, day))
    if sent:
        database.conn.execute(
            f"UPDATE newsletter_optins SET last_digest_on={ph} WHERE subscriber_id={ph} AND status='active'",
            (day, subscriber_id))
    _commit(database)


def send_daily(database, story, key):
    day = now_utc().astimezone(INDIA).strftime("%Y-%m-%d")
    sent = 0
    for subscriber in active_subscribers(database):
        if not claim_digest(database, subscriber["subscriber_id"], day):
            continue
        unsub = email_unsubscribe_link(subscriber["subscriber_id"], key)
        try:
            send_mail(
                subscriber["email"], "PoliticsHub Brief — " + story["title"][:110],
                "Your news briefing — " + day,
                [story["title"], story["summary"], "Source: " + story["source"],
                 "We send one concise, sourced news briefing a day. You can unsubscribe anytime."],
                action=("Read the source report", story["url"]), unsubscribe=unsub)
        except Exception:
            finish_digest(database, subscriber["subscriber_id"], day, False)
            continue
        finish_digest(database, subscriber["subscriber_id"], day, True)
        sent += 1
    return sent
