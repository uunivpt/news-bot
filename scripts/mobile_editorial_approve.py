"""Human-only Termux editorial approval for ONE fully checked story.

Usage:
  python scripts/mobile_editorial_approve.py --id 455
  python scripts/mobile_editorial_approve.py --id 455 --approve

The default is a READ-ONLY preview. Approval prompts for independently
checked evidence and editorial notes, requires an exact typed confirmation
and a LOCAL PostgreSQL admin password. The automated collector and worker
never receive approval/write permissions. No remote database is contacted.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOCAL_DATABASE = (
    "postgresql://politicshub_collector@127.0.0.1:5432/"
    "politicshub?sslmode=disable"
)
MAX_AGE = timedelta(days=5)
HIGH_RISK = re.compile(
    r"\b(?:russia|russian|ukraine|ukrainian|attack|strikes?|missiles?|"
    r"war|explosion|killed|deaths?|dead|crash|elections?|fraud|arrests?|"
    r"allegations?|terror|military|invasion)\b", re.I
)
TELEGRAM_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}


def source_host(raw: str) -> str | None:
    try:
        parsed = urlsplit(str(raw or ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            return None
        if parsed.port not in (None, 443):
            return None
        return parsed.hostname.lower()
    except ValueError:
        return None


def parse_published(raw: str):
    if not raw:
        return None
    try:
        result = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            result = parsedate_to_datetime(str(raw))
        except (ValueError, TypeError, IndexError):
            return None
    if result.tzinfo is None:
        return None
    return result.astimezone(timezone.utc)


def risk_flags(row):
    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    flags = []
    if source_host(row.get("url")) in TELEGRAM_HOSTS:
        flags.append("Telegram-source verification required")
    if HIGH_RISK.search(title + " " + summary):
        flags.append("High-impact claim: independent confirmation required")
    return flags


def review_eligibility(row, now=None):
    """Validate record structure, NOT truth of its claims."""
    now = now or datetime.now(timezone.utc)
    problems = []
    if row is None:
        return ["Story not found"]
    if row.get("status") != "pending":
        problems.append("Story is not pending; cannot approve it again")
    if row.get("approved_at"):
        problems.append("Existing approval metadata: manual inspection required")
    if str(row.get("fact_check_status") or "").lower() in {
        "rejected", "failed", "false", "blocked", "disputed"
    }:
        problems.append("Previously rejected/disputed story requires separate correction workflow")
    if not bool(row.get("public_source")):
        problems.append("Source is not marked public")
    if not source_host(row.get("url")):
        problems.append("Original reporting link is not valid HTTPS")
    title = str(row.get("title") or "").strip()
    summary = str(row.get("bot_summary") or row.get("summary") or "").strip()
    article = str(row.get("bot_article") or "").strip()
    if not 20 <= len(title) <= 210:
        problems.append("Headline missing or incomplete")
    if len(summary) < 55:
        problems.append("Summary too short for public feed")
    if len(article) < 600:
        problems.append("Full draft is too short for editorial approval")
    published = parse_published(row.get("published_at_site") or row.get("published_at"))
    if published is None:
        problems.append("Original publication date unavailable")
    elif published > now + timedelta(minutes=30) or now - published > MAX_AGE:
        problems.append("Old or future-dated story: do not republish as new")
    return problems


def check_evidence(row, urls):
    """Record editorial corroboration; does NOT assert source reliability."""
    hosts, clean, errors = set(), [], []
    original = str(row.get("url") or "").strip()
    for value in urls:
        value = str(value or "").strip()
        if not value:
            continue
        host = source_host(value)
        if not host or len(value) > 2000:
            errors.append("Evidence must be a valid HTTPS public URL")
            continue
        if value == original or host in TELEGRAM_HOSTS:
            errors.append("Telegram/original post alone is not independent corroboration")
            continue
        if host in hosts:
            errors.append("Use different publisher domains for independent sources")
            continue
        hosts.add(host)
        clean.append(value)
    min_sources = 2 if risk_flags(row) else 1
    if len(clean) < min_sources:
        errors.append(
            f"Need {min_sources} independent reporting/source link(s) "
            "before human approval"
        )
    return clean, errors


def display(row, *, complete=False):
    print("\n=== PRIVATE EDITORIAL REVIEW ===")
    print("ID:", row.get("id"))
    print("Title:", row.get("title"))
    print("Source:", row.get("source_name"))
    print("Original:", row.get("url"))
    print("Original date:", row.get("published_at"))
    print("Status:", row.get("status"), "/ Fact-check:", row.get("fact_check_status"))
    print("Summary:", row.get("bot_summary") or row.get("summary") or "")
    article = str(row.get("bot_article") or "")
    print("Draft length:", len(article))
    print("Draft:\n", article if complete else article[:2400])
    if not complete and len(article) > 2400:
        print("[Preview shortened; use --approve for full draft review]")
    for flag in risk_flags(row):
        print("REVIEW FLAG:", flag)


def read_local(item_id):
    """The worker role is read-only for approvals; previews need no admin password."""
    from app.database import NewsDatabase

    worker = Path.home() / ".politicshub-worker.pgpass"
    if not worker.is_file():
        raise RuntimeError("Local worker credential file not found")
    os.environ["PGPASSFILE"] = str(worker)
    db = NewsDatabase(
        database_url=LOCAL_DATABASE, initialize_schema=False,
        connect_attempts=1,
    )
    try:
        if not db._postgres:
            raise RuntimeError("Only local PostgreSQL is supported")
        row = db.get_by_id(item_id)
        return dict(row) if row else None
    finally:
        db.close()


def list_local(limit=15):
    """Show human-reviewable drafts without any admin password or DB writes."""
    from app.database import NewsDatabase

    worker = Path.home() / ".politicshub-worker.pgpass"
    if not worker.is_file():
        raise RuntimeError("Local worker credential file not found")
    os.environ["PGPASSFILE"] = str(worker)
    db = NewsDatabase(
        database_url=LOCAL_DATABASE, initialize_schema=False,
        connect_attempts=1,
    )
    try:
        rows = db.conn.execute(
            """SELECT id,title,source_name,url,summary,bot_summary,bot_article,
                      status,public_source,approved_at,published_at,
                      published_at_site,fact_check_status
               FROM news_items
               WHERE status='pending'
                 AND LENGTH(COALESCE(bot_article,'')) >= 600
               ORDER BY id DESC LIMIT %s""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def approve_local(preview, sources, notes, password, admin_user="postgres", now=None):
    """Atomic local approval, followed separately by approved-only upload."""
    from psycopg import connect
    from psycopg.rows import dict_row

    now = now or datetime.now(timezone.utc)
    if len(notes.strip()) < 40:
        raise ValueError("Provide substantive verification notes (at least 40 characters)")
    evidence, errors = check_evidence(preview, sources)
    if errors:
        raise ValueError("; ".join(errors))
    snapshot = (
        "status", "approved_at", "url", "title", "summary", "bot_summary",
        "bot_article", "published_at", "published_at_site", "public_source",
    )
    record_id = int(preview["id"])
    # Never use the remote DB env variables or grant write privileges to the
    # automated worker. Admin password is used in-memory only, once.
    with connect(
        dbname="politicshub", user=admin_user,
        host="127.0.0.1", port=5432, sslmode="disable",
        password=password, connect_timeout=8, row_factory=dict_row,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM news_items WHERE id=%s FOR UPDATE", (record_id,))
            current = cur.fetchone()
            if current is None:
                raise RuntimeError("Story no longer exists")
            if any(current.get(key) != preview.get(key) for key in snapshot):
                raise RuntimeError("Story changed during review; re-open it")
            problems = review_eligibility(current, now)
            if problems:
                raise RuntimeError("Approval blocked: " + "; ".join(problems))
            # Retain original article date so stale events never masquerade as
            # current breaking news in the public GitHub feed.
            stamp = str(current.get("published_at_site") or current.get("published_at"))
            event = now.isoformat()
            note = (
                f"Human editor reviewed at {event}. "
                f"Independent sources: {'; '.join(evidence)}. "
                f"Evidence/context: {notes.strip()}"
            )
            cur.execute(
                """UPDATE news_items
                   SET fact_check_status=%s, fact_check_notes=%s,
                       approved_at=%s, published_at_site=%s, status=%s
                   WHERE id=%s AND status='pending' AND approved_at IS NULL""",
                ("reviewed", note, event, stamp, "published", record_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError("Approval conflict; nothing published")
            cur.execute(
                """INSERT INTO admin_activity
                   (username, action, item_id, details, created_at)
                   VALUES (%s,%s,%s,%s,%s)""",
                (admin_user, "termux_human_approval", record_id,
                 "Explicit local human approval with recorded verification sources",
                 event),
            )
    return record_id


def sync_approved():
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("DATABASE_3URL", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mobile_sync_upload.py"), "--push"],
        cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=90, check=False,
    )
    if result.stdout:
        print(result.stdout[-3000:])
    if result.returncode:
        print("GITHUB SYNC NOT CONFIRMED; local approval is saved.")
        if result.stderr:
            print(result.stderr[-1200:])
        print("Existing 15-minute scheduler will retry the approved-only export.")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", type=int)
    target.add_argument("--list", action="store_true",
                        help="List available private editorial drafts, read-only")
    parser.add_argument("--approve", action="store_true",
                        help="Begin explicit human approval of one reviewed article")
    parser.add_argument("--admin-user", default="postgres")
    args = parser.parse_args()

    if args.id is not None and args.id <= 0:
        parser.error("--id must be a positive news ID")
    if args.list and args.approve:
        parser.error("--list is read-only and cannot approve stories")
    if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_3URL"):
        raise SystemExit("STOP: unset remote DATABASE_URL/DATABASE_3URL first")
    if args.list:
        print("=== TERMUX HUMAN REVIEW CANDIDATES (READ ONLY) ===")
        records = list_local()
        if not records:
            print("No substantial pending drafts available for editorial review")
        for item in records:
            status = "ELIGIBLE FOR HUMAN REVIEW" if not review_eligibility(item) else "HOLD"
            print(f"{item['id']}: {str(item.get('title') or '')[:95]}")
            print(f"  {status}; source: {item.get('source_name')}; "
                  f"draft: {len(item.get('bot_article') or '')} chars")
            for flag in risk_flags(item):
                print("  REVIEW FLAG:", flag)
        print("LIST DOES NOT APPROVE OR PUBLISH NEWS")
        return 0
    row = read_local(args.id)
    if row is None:
        raise SystemExit("Story ID not found in local phone PostgreSQL")
    display(row, complete=args.approve)
    problems = review_eligibility(row)
    for reason in problems:
        print("BLOCKED:", reason)
    if not args.approve:
        print("READ-ONLY PREVIEW: no database writes or publication")
        print("After checking original reporting, use --approve for interactive review")
        return 0
    if problems:
        print("REFUSED: Draft/source/date requirements not met. No changes made.")
        return 1

    minimum = 2 if risk_flags(row) else 1
    print(f"Supply {minimum} independently checked HTTPS evidence URLs.")
    sources = [input(f"Evidence URL {i+1}: ").strip() for i in range(minimum)]
    checked, errors = check_evidence(row, sources)
    if errors:
        print("REFUSED:", "; ".join(errors))
        return 1
    notes = input("Verified facts, date, context and originality notes: ").strip()
    if len(notes) < 40:
        print("REFUSED: At least 40 characters of evidence notes required")
        return 1
    confirmation = input(f"Type APPROVE {args.id} to publish this ONE story: ").strip()
    if confirmation != f"APPROVE {args.id}":
        print("CANCELLED: no approval saved")
        return 1
    password = getpass.getpass("Local PostgreSQL admin password (not saved): ")
    try:
        approve_local(row, checked, notes, password, args.admin_user)
    except Exception as exc:
        print("APPROVAL FAILED; no partial write:", type(exc).__name__, str(exc))
        return 1
    finally:
        password = ""
    print("LOCAL APPROVAL SAVED:", args.id)
    if not sync_approved():
        return 0  # Approval persisted; scheduler handles a transient push error.
    print("APPROVED NEWS UPLOADER COMPLETED; GitHub feed workflow will publish it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
