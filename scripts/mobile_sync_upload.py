"""Safe Termux -> GitHub reviewed-news uploader.

Defaults to preview-only. --push writes only public/mobile-reviewed.json to
the production main branch after the integration PR is merged; skips empty exports.
No PostgreSQL port exposure, force push, or writes to unrelated files.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import shlex
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BRANCH = "main"
REMOTE = "git@github.com:uunivpt/news-bot.git"
TARGET = "public/mobile-reviewed.json"
ALLOWED_CHECKS = {"passed", "verified", "approved", "reviewed"}
PUBLIC_TARGETS = (TARGET, "public/news-data.json", "app/data/public-archive.json.gz")


def _git(args, cwd, env=None, timeout=30):
    result = subprocess.run(['git', *args], cwd=cwd, env=env, text=True,
                            capture_output=True, check=True, timeout=timeout)
    return result.stdout.strip()


def sync_public_rows(rows, checkout, remote, *, env=None, now=None):
    """Update a tool-owned checkout only; never reset the user's source checkout.

    The injected local bare remote makes the real commit/push path testable
    without contacting production or generating ad impressions.
    """
    from scripts.publish_mobile_reviewed import publish
    from scripts.offline_snapshot import mobile_reviewed_story
    from app.seo_indexing import SITE_ORIGIN, canonical_path
    from app.normalize import normalize_url
    from app.live_publication import publication_key
    from datetime import datetime, timezone
    from app.phone_publication import public_export
    rows = [public_export(dict(row)) for row in rows]
    validated(rows)
    now = now or datetime.now(timezone.utc)
    if any(mobile_reviewed_story(row, now) is None for row in rows):
        raise ValueError('Publication contains an incomplete or future-dated story')
    checkout = Path(checkout)
    checkout.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = checkout/'.phone-publication-owned'
    if not (checkout/'.git').exists():
        if any(checkout.iterdir()):
            raise ValueError('Delivery checkout is not empty; refusing to modify it')
        _git(['init', '-b', BRANCH], checkout, env)
        _git(['remote', 'add', 'origin', str(remote)], checkout, env)
        marker.write_text('Managed public-feed delivery checkout\n')
    if not marker.is_file() or _git(['remote','get-url','origin'],checkout,env) != str(remote):
        raise ValueError('Unrecognized delivery checkout')
    # This directory contains generated delivery state only. All authoritative
    # queued content remains in PostgreSQL until a successful push receipt.
    _git(['fetch','--depth=1','origin',BRANCH],checkout,env)
    _git(['reset','--hard','FETCH_HEAD'],checkout,env)
    incoming = {publication_key(row): dict(row) for row in rows}
    target = checkout/TARGET
    saved = json.loads(target.read_text()) if target.is_file() else []
    combined = list(incoming.values()) + [public_export(row) for row in saved if publication_key(row) not in incoming]
    kept = []
    for row in combined:
        attempt = kept+[row]
        if len(attempt)>1000 or len(json.dumps(attempt,ensure_ascii=False).encode())>1_950_000:
            if publication_key(row) in incoming:
                raise ValueError('Publication batch too large')
            break
        kept=attempt
    validated(kept)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(kept,ensure_ascii=False,separators=(',',':'))+'\n')
    publish(checkout,now=now)
    public = json.loads((checkout/'public/news-data.json').read_text())
    by_url = {publication_key(row):row for row in public}
    archive_file = checkout/'app/data/public-archive.json.gz'
    if archive_file.is_file():
        import gzip
        with gzip.open(archive_file,'rt',encoding='utf-8') as archive:
            by_url = {**{publication_key(row):row for row in json.load(archive)}, **by_url}
    if any(publication_key(row) not in by_url for row in rows):
        raise ValueError('Public identity conflict; story was not added to the feed/archive')
    # Public exports use the same canonical ID as the public feed/archive.
    # The caller's private phone PK remains the outbox key and return-map key.
    normalized = [{**row, 'id':by_url.get(publication_key(row),row)['id']} for row in kept]
    validated(normalized)
    target.write_text(json.dumps(normalized,ensure_ascii=False,separators=(',',':'))+'\n')
    _git(['add','--',*PUBLIC_TARGETS],checkout,env)
    staged = _git(['diff','--cached','--name-only'],checkout,env).splitlines()
    if any(path not in PUBLIC_TARGETS for path in staged):
        raise ValueError('Unexpected staged publication files')
    if staged:
        _git(['-c','user.name=PoliticsHub phone publication',
              '-c','user.email=politicshub-mobile-sync@users.noreply.github.com',
              'commit','-m','Publish editor-approved phone stories'],checkout,env)
        _git(['push','origin','HEAD:refs/heads/'+BRANCH],checkout,env)
    commit = _git(['rev-parse','HEAD'],checkout,env)
    # The feed may retain an existing canonical ID for a previously seen URL.
    urls = {}
    for row in rows:
        public_row = by_url.get(publication_key(row)) or mobile_reviewed_story(row,now)
        urls[str(row['id'])] = SITE_ORIGIN+canonical_path(public_row)+'?v='+commit
    return {'commit_sha':commit,'public_urls':urls,'state':'synced'}


def upload_immediate(rows):
    """Use the existing phone SSH identity, with bounded exclusive delivery."""
    import fcntl
    key=Path.home()/'.ssh/politicshub_mobile_sync'
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077:
        raise ValueError('Phone publication SSH identity missing or unsafe')
    folder=Path.home()/'.local/share/politicshub/public-delivery'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/'delivery.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        env=dict(os.environ)
        env['GIT_SSH_COMMAND']='ssh -i '+shlex.quote(str(key))+' -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=10'
        return sync_public_rows(rows,folder/'checkout',REMOTE,env=env)


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
            or not 1 <= len(str(row.get("bot_summary") or row.get("summary") or "").strip()) <= 6000
            or len(str(row.get("title") or "")) > 500
        ):
            raise ValueError("Export contains an unapproved or incomplete story")
        sid = row.get("id")
        if type(sid) is not int or not (0 < sid < 2**53):
            raise ValueError("Unsafe story id")
        from app.live_publication import publication_key
        identity=publication_key(row)
        if sid in seen_ids or identity in seen_urls:
            raise ValueError("Duplicate story ID or URL in export")
        seen_ids.add(sid)
        seen_urls.add(identity)
    return len(rows)


def command(args, cwd=None, env=None, capture=False):
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True,
        capture_output=capture, check=True
    )
    return result.stdout.strip() if capture else None


def read_local_reviewed():
    """Read actual approved phone rows using its existing read-only worker identity."""
    from app.phone_publication import public_export
    import psycopg
    from psycopg.rows import dict_row
    passfile = Path.home()/'.politicshub-worker.pgpass'
    if not passfile.is_file() or passfile.is_symlink() or passfile.stat().st_mode & 0o077:
        raise ValueError('Existing local worker credential missing or unsafe')
    with psycopg.connect(dbname='politicshub',user='politicshub_collector',
                         host='127.0.0.1',port=5432,sslmode='disable',
                         passfile=str(passfile),row_factory=dict_row,connect_timeout=8) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        records = connection.execute("""SELECT * FROM news_items
            WHERE status='published' AND public_source=1 AND approved_at IS NOT NULL
              AND fact_check_status IN ('passed','verified','approved','reviewed')
            ORDER BY approved_at DESC,id DESC LIMIT 1000""").fetchall()
    return [public_export(dict(row)) for row in records]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--push', action='store_true',
                        help='Push already-published editor-approved phone records')
    args = parser.parse_args()
    rows = read_local_reviewed()
    count = validated(rows)
    print('Eligible published phone stories:',count,flush=True)
    if not count:
        print('NO ELIGIBLE STORIES: GitHub unchanged')
        return
    if not args.push:
        print('DRY RUN PASSED: Nothing uploaded')
        return
    result = upload_immediate(rows)
    print('PRODUCTION MAIN UPDATED:',result['commit_sha'],flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PUBLIC SYNC FAILED:",type(exc).__name__,flush=True)
        raise SystemExit(1)
