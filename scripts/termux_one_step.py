"""Finish phone news integration in one run, without reboot or auto-approval.

Only new private drafts are saved; the existing GitHub uploader remains
strictly approved-only. The production Neon database is never modified.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
SCHEDULER = HOME / "politicshub-mobile-upload/sync_scheduler.py"
LOG = HOME / ".local/share/politicshub/mobile-sync.log"
REPORT = HOME / "politicshub-sync/editorial-review-queue.md"

ORIGINAL = (
    'str(repo / "scripts/mobile_sync_upload.py"),\n'
    '                    "--push"'
)
COMBINED = 'str(repo / "scripts/mobile_pipeline_cycle.py")'


def configure_scheduler(source: str) -> str:
    if COMBINED in source:
        return source
    if source.count(ORIGINAL) != 1:
        raise ValueError("Unexpected scheduler format: existing file left unchanged")
    result = source.replace(ORIGINAL, COMBINED)
    compile(result, str(SCHEDULER), "exec")
    return result


def inspect_local_database() -> str:
    import psycopg

    worker = HOME / ".politicshub-worker.pgpass"
    if not worker.is_file():
        raise RuntimeError("Local worker credential file missing")
    os.environ["PGPASSFILE"] = str(worker)
    database_url = (
        "postgresql://politicshub_collector@127.0.0.1:5432/"
        "politicshub?sslmode=disable"
    )
    with psycopg.connect(database_url, connect_timeout=7) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*),
                  COUNT(*) FILTER (WHERE status='pending'),
                  COUNT(*) FILTER (WHERE status='published'),
                  COUNT(*) FILTER (
                     WHERE COALESCE(bot_article,'') <> ''),
                  COUNT(*) FILTER (
                     WHERE status='published'
                     AND approved_at IS NOT NULL
                     AND LOWER(COALESCE(fact_check_status,'')) IN
                         ('reviewed','passed','verified','approved'))
                FROM news_items
            """)
            total, pending, published, drafts, approved = cur.fetchone()
            cur.execute("""
                SELECT id,title,source_name,url,
                       LENGTH(COALESCE(bot_article,'')),
                       COALESCE(fact_check_status,'pending')
                FROM news_items
                WHERE status='pending' AND COALESCE(bot_article,'') <> ''
                ORDER BY id DESC LIMIT 20
            """)
            records = cur.fetchall()

    lines = [
        "# PoliticsHub local editorial review queue",
        "",
        f"Total news: {total}; pending: {pending}; published: {published}",
        f"Private drafts: {drafts}; approved-for-sync: {approved}",
        "",
        "These are UNVERIFIED private drafts, not publication approvals.",
        "Verify source, date, facts, context, originality, and current updates",
        "before changing status or setting any approval timestamp.",
        "",
    ]
    for ident, title, source, url, length, fact_check in records:
        lines.append(f"## {ident}: {str(title or '').strip()}")
        lines.append(f"Source: {str(source or '').strip()}")
        link = urlsplit(str(url or ""))
        if link.scheme == "https" and link.hostname:
            lines.append(f"Original reporting: {url}")
        lines.append(f"Draft characters: {length}; fact check: {fact_check}")
        lines.append("Review status: NEEDS HUMAN REVIEW and originality check")
        lines.append("")
    return "\n".join(lines)


def stop_existing_scheduler() -> bool:
    """Stop only the exact previously configured scheduler, never the collector."""
    if not SCHEDULER.is_file():
        return False
    target = str(SCHEDULER.resolve()).encode()
    result = subprocess.run(
        ["pgrep", "-f", "sync_scheduler[.]py"],
        text=True, capture_output=True, check=False,
    )
    pids = []
    for entry in result.stdout.split():
        try:
            pid = int(entry)
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\x00")
            if target in cmdline:
                os.kill(pid, signal.SIGTERM)
                pids.append(pid)
        except (OSError, ValueError):
            continue
    if not pids:
        return True
    for _ in range(40):
        live = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                live.append(pid)
            except ProcessLookupError:
                pass
        if not live:
            return True
        time.sleep(0.1)
    print("STOP: old scheduler did not exit; launch skipped")
    return False


def main() -> int:
    if not (ROOT / "scripts/mobile_sync_upload.py").is_file():
        print("STOP: missing uploader in production checkout")
        return 1
    if not SCHEDULER.is_file():
        print("STOP: original scheduler missing; nothing changed")
        return 1
    if not (HOME / ".ssh/politicshub_mobile_sync").is_file():
        print("STOP: existing SSH key missing")
        return 1
    print("=== POLITICSHUB ONE-STEP PHONE FINISH ===")
    if subprocess.run(
        ["pg_isready", "-q", "-h", "127.0.0.1", "-p", "5432"],
        check=False,
    ).returncode:
        print("STOP: local PostgreSQL is not ready")
        return 1

    # Fail before writing anything if the scheduler file is unfamiliar.
    previous = SCHEDULER.read_text()
    try:
        replacement = configure_scheduler(previous)
    except ValueError as exc:
        print(f"STOP: {exc}")
        return 1

    # This cycle writes only private bot_article and bot_summary drafts, and
    # uploads only stories already approved according to the existing gate.
    if subprocess.run(
        [sys.executable, str(ROOT / "scripts/mobile_pipeline_cycle.py")],
        cwd=ROOT, check=False, timeout=118,
    ).returncode:
        print("STOP: Sync failed; scheduler unchanged")
        return 1

    try:
        report = inspect_local_database()
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report, encoding="utf-8")
        REPORT.chmod(0o600)
        print(f"REVIEW QUEUE SAVED: {REPORT}")
    except Exception as exc:
        print("REVIEW REPORT FAILED:", type(exc).__name__)

    if replacement != previous:
        saved = SCHEDULER.with_suffix(".py.before-combined")
        if not saved.exists():
            shutil.copy2(SCHEDULER, saved)
        temp = SCHEDULER.with_suffix(".py.tmp")
        temp.write_text(replacement)
        temp.replace(SCHEDULER)
        print("SCHEDULER UPDATED: hourly draft prep, 15-min sync")
    else:
        print("SCHEDULER ALREADY CONFIGURED")

    if not stop_existing_scheduler():
        return 1
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        process = subprocess.Popen(
            [sys.executable, "-u", str(SCHEDULER)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            cwd=ROOT, start_new_session=True,
        )
    time.sleep(3)
    if process.poll() is not None:
        print("SCHEDULER DID NOT STAY RUNNING; check", LOG)
        return 1
    print("LIVE SYNC SCHEDULER RUNNING:", process.pid)
    print("POSTGRESQL DATA: preserved; no publication or approval bypass")
    print("WEBSITE: independent GitHub-published feed; no Neon dependency")
    print("ONE-STEP PHONE SETUP COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        print("STOP: cycle timed out; live scheduler was not modified")
        sys.exit(1)
