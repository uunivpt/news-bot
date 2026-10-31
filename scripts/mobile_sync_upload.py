"""Safe Termux -> GitHub reviewed-news uploader.

Defaults to preview-only. --push writes only public/mobile-reviewed.json to
the requested integration branch, and skips empty exports.
No PostgreSQL port exposure, force push, or production main updates.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

BRANCH = "mobile-reviewed-fallback-20261031"
REMOTE = "git@github.com:uunivpt/news-bot.git"
TARGET = "public/mobile-reviewed.json"
ALLOWED_CHECKS = {"passed", "verified", "approved"}


def validated(rows):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid export list")
    seen_ids, seen_urls = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Non-object export entry")
        u = urlsplit(str(row.get("url") or ""))
        if (
            row.get("status") != "published"
            or row.get("public_source") is not True
            or not row.get("approved_at")
            or str(row.get("fact_check_status") or "").lower() not in ALLOWED_CHECKS
            or u.scheme != "https"
            or not u.hostname
            or u.username
            or not str(row.get("title") or "").strip()
            or not str(row.get("source_name") or "").strip()
            or len(str(row.get("summary") or "")) < 30
        ):
            raise ValueError("Export contains an unapproved or incomplete story")
        sid = row.get("id")
        if type(sid) is not int or not (0 < sid < 2**53):
            raise ValueError("Unsafe story id")
        if sid in seen_ids or row["url"] in seen_urls:
            raise ValueError("Duplicate story ID or URL in export")
        seen_ids.add(sid)
        seen_urls.add(row["url"])
    return len(rows)


def command(args, cwd=None, env=None, capture=False):
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True,
        capture_output=capture, check=True
    )
    return result.stdout.strip() if capture else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true",
                        help="Opt in to push to the integration branch (never main)")
    args = parser.parse_args()
    home = Path.home()
    stage = home / "politicshub-stage"
    repo = home / "politicshub-mobile-upload"
    key = home / ".ssh/politicshub_mobile_sync"
    output = home / "politicshub-sync/mobile-reviewed.json"

    if not (stage / "mobile_sync_export.py").is_file():
        raise SystemExit("STOP: Existing phone exporter missing")
    if not (repo / ".git").is_dir():
        raise SystemExit("STOP: Isolated Git working copy missing")
    if not key.is_file() or key.is_symlink() or (key.stat().st_mode & 0o077):
        raise SystemExit("STOP: SSH private key missing or permissions unsafe")
    if command(["git", "branch", "--show-current"], cwd=repo, capture=True) != BRANCH:
        raise SystemExit("STOP: Wrong checkout branch")
    if command(["git", "remote", "get-url", "origin"], cwd=repo, capture=True) != REMOTE:
        raise SystemExit("STOP: Unexpected remote; refusing upload")

    print("=== POLITICSHUB MOBILE SYNC ===", flush=True)
    command([sys.executable, str(stage / "mobile_sync_export.py")], cwd=stage)
    rows = json.loads(output.read_text(encoding="utf-8"))
    count = validated(rows)
    print("Eligible reviewed stories:", count, flush=True)

    if count == 0:
        print("NO ELIGIBLE STORIES: GitHub unchanged")
        return

    tracked = command(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo, capture=True
    )
    if tracked and any(TARGET not in entry for entry in tracked.splitlines()):
        raise SystemExit("STOP: Other tracked changes present")

    if not args.push:
        print("DRY RUN PASSED: Nothing uploaded")
        print("Run with --push only after PR integration is approved")
        return

    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {key} -o IdentitiesOnly=yes "
        "-o StrictHostKeyChecking=yes -o BatchMode=yes"
    )
    command(["git", "fetch", "--depth", "1", "origin", BRANCH], cwd=repo, env=env)
    command(["git", "merge", "--ff-only", "FETCH_HEAD"], cwd=repo)

    target = repo / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mobile-reviewed-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(rows, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    command(["git", "add", "--", TARGET], cwd=repo)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", TARGET],
        cwd=repo, check=False
    ).returncode
    if changed == 0:
        print("NO CONTENT CHANGE: GitHub unchanged")
        return
    if changed != 1:
        raise SystemExit("STOP: Git diff failed")

    command([
        "git", "-c", "user.name=PoliticsHub mobile sync",
        "-c", "user.email=politicshub-mobile-sync@users.noreply.github.com",
        "commit", "-m", "Update approved mobile news feed", "--", TARGET
    ], cwd=repo)
    command(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH],
            cwd=repo, env=env)
    print("REVIEW BRANCH UPDATED; production main unchanged")


if __name__ == "__main__":
    main()
