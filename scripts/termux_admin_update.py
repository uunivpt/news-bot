"""Apply one immutable reviewed phone release, preserving DB and local edits.

Run from anywhere with --checkout pointing to the existing main-branch checkout.
Default is a read-only release preview. --apply backs up the database, preserves
staged/unstaged changes and untracked files in a local Git stash, fast-forwards
the existing checkout (including tracked deletions), then restarts only the
launcher-owned admin process. It never resets an owner password or modifies
private environment/credential files. A divergent branch is left untouched.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def git(checkout, *args, capture=True):
    result = subprocess.run(['git', '-C', str(checkout), *args], text=True,
                            capture_output=capture, check=True, timeout=120)
    return result.stdout.strip() if capture else ''


def validate_checkout(checkout):
    if git(checkout, 'branch', '--show-current') != 'main':
        raise RuntimeError('Existing phone checkout must be on main; no branch changed')
    remote = git(checkout, 'remote', 'get-url', 'origin').rstrip('/')
    if remote not in {'https://github.com/uunivpt/news-bot.git',
                      'https://github.com/uunivpt/news-bot',
                      'git@github.com:uunivpt/news-bot.git'}:
        raise RuntimeError('Unexpected repository; no source changed')


def apply_release(checkout, ref, apply=False):
    if not re.fullmatch('[0-9a-f]{40}', ref):
        raise ValueError('--ref must be an immutable full 40-character commit SHA')
    checkout = Path(checkout).expanduser().resolve()
    validate_checkout(checkout)
    git(checkout, 'fetch', '--no-tags', 'origin', ref)
    expected = git(checkout, 'rev-parse', ref+'^{commit}')
    if expected != ref:
        raise RuntimeError('Fetched revision does not match the reviewed release')
    # Never rewrite phone-only commits. A normal fast-forward applies tracked
    # file removals as well as updates while preserving ignored local state.
    git(checkout, 'merge-base', '--is-ancestor', 'HEAD', ref)
    changes = git(checkout, 'status', '--porcelain')
    print('PHONE RELEASE:', ref)
    print('LOCAL EDITS:', 'will be preserved in a local stash' if changes else 'none')
    if not apply:
        print('PREVIEW ONLY: no source, process or database changes')
        return 0
    env = os.environ.copy()
    env.pop('DATABASE_URL', None)
    env.pop('DATABASE_3URL', None)
    # Run the checker from the reviewed revision before changing live source.
    checker = git(checkout, 'show', ref+':scripts/termux_database_check.py')
    with tempfile.TemporaryDirectory(prefix='politicshub-update-') as temporary:
        script = Path(temporary)/'check.py'
        script.write_text(checker)
        subprocess.run([sys.executable, str(script), '--verify-write', '--backup'],
                       env=env, check=True, timeout=240)
    if changes:
        git(checkout, 'stash', 'push', '--include-untracked', '-m', 'Phone edits before reviewed release '+ref)
        print('LOCAL EDITS PRESERVED: git stash list (not automatically reapplied to reviewed code)')
    git(checkout, 'merge', '--ff-only', ref)
    try:
        sparse = git(checkout, 'config', '--bool', '--get', 'core.sparseCheckout') == 'true'
    except subprocess.CalledProcessError:
        sparse = False
    if sparse:
        # Older phone installations intentionally downloaded only the feed.
        # Expand rather than replace their sparse rules; all runtime imports,
        # templates and admin assets must be present for the new daemon.
        git(checkout, 'sparse-checkout', 'add', 'app', 'api', 'public', 'scripts', 'config')
    subprocess.run([sys.executable, '-m', 'compileall', '-q',
                    str(checkout/'app'), str(checkout/'api'), str(checkout/'scripts')], check=True)
    subprocess.run([sys.executable, str(checkout/'scripts/termux_local_admin.py'), '--restart'],
                   cwd=checkout, env=env, check=True, timeout=120)
    print('PHONE UPDATE COMPLETE: existing database and owner password preserved')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, default=Path.home()/'politicshub-live-upload')
    parser.add_argument('--ref', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--bridge-secret-file', type=Path,
                        help='Existing private file containing the same shared secret configured on Vercel')
    args = parser.parse_args()
    if args.bridge_secret_file:
        os.environ['POLITICSHUB_ADMIN_BRIDGE_SECRET_FILE'] = str(args.bridge_secret_file.expanduser())
    return apply_release(args.checkout, args.ref, args.apply)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # stderr from child commands can include infrastructure identifiers.
        print('PHONE UPDATE STOPPED:', type(exc).__name__)
        print('Database backup/local stashes, if created, remain on this phone. No owner password reset.')
        sys.exit(1)
