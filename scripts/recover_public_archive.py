"""Recover previously public snapshots from local Git history without DB writes.

Run with full Git history: PYTHONPATH=. python scripts/recover_public_archive.py
Only public/news-data.json is read; private database/admin fields are excluded.
"""
import json
import subprocess
from app.public_archive import retain_public_records


def main():
    commits = subprocess.check_output(
        ["git", "log", "--reverse", "--format=%H", "--", "public/news-data.json"], text=True
    ).splitlines()
    records = []
    for commit in commits:
        payload = json.loads(subprocess.check_output(["git", "show", commit + ":public/news-data.json"]))
        if isinstance(payload, list):
            records.extend(payload)
    count = retain_public_records(records)
    print(f"Recovered {count} public stories from {len(commits)} snapshots; databases unchanged.")


if __name__ == "__main__":
    main()
