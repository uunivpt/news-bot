"""One bounded local phone cycle: prepare private drafts, then sync only reviewed news.

The phone's PostgreSQL never becomes reachable from the public internet.
Preparing a draft does NOT certify facts or grant publication privileges.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".local/share/politicshub/draft-prep-last-success"
DRAFT_INTERVAL = 3600


def run_local(command: list[str], timeout: int) -> bool:
    env = os.environ.copy()
    # Never accidentally run against the quota-limited cloud DB.
    env.pop("DATABASE_URL", None)
    env.pop("DATABASE_3URL", None)
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: {Path(command[1]).name}", flush=True)
        return False
    if result.stdout:
        print(result.stdout[-4500:], flush=True)
    if result.stderr and result.returncode:
        print(result.stderr[-1400:], flush=True)
    return result.returncode == 0


def cycle() -> int:
    print("=== POLITICSHUB PHONE PIPELINE ===", flush=True)
    print("DRAFT PREPARATION: hourly; EDITORIAL APPROVAL: manual", flush=True)
    print("LIVE SYNC: published and individually approved stories only", flush=True)
    try:
        last = float(STATE.read_text().strip())
    except (OSError, ValueError):
        last = 0.0

    if time.time() - last >= DRAFT_INTERVAL:
        prepared = run_local(
            [sys.executable, str(ROOT / "scripts/mobile_prepare_drafts.py"),
             "--limit", "5", "--write"],
            timeout=65,
        )
        if prepared:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            temp = STATE.with_suffix(".tmp")
            temp.write_text(str(time.time()))
            temp.replace(STATE)
        else:
            print("DRAFT PREP FAILED; earlier drafts left untouched", flush=True)
    else:
        print("DRAFT PREP SKIPPED: hourly interval not elapsed", flush=True)

    # Push is safe even when there are zero approved stories. The uploader
    # validates public_source, approved_at, status, fact_check, HTTPS, IDs.
    successful = run_local(
        [sys.executable, str(ROOT / "scripts/mobile_sync_upload.py"), "--push"],
        timeout=45,
    )
    print("SYNC CYCLE PASSED" if successful else "SYNC CYCLE FAILED", flush=True)
    # This is a private, read-only report of draft/source flags, refreshed
    # after each local cycle; it never changes status or approval metadata.
    refreshed = run_local(
        [sys.executable, str(ROOT / "scripts/mobile_review_report.py")],
        timeout=15,
    )
    if not refreshed:
        print("REVIEW REPORT UNAVAILABLE; publication gates unchanged", flush=True)
    return 0 if successful else 1


if __name__ == "__main__":
    sys.exit(cycle())
