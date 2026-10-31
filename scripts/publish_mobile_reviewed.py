"""Immediately merge editorially approved Termux exports into the public feed.

Runs in GitHub Actions after public/mobile-reviewed.json changes. This does
not connect to Termux or any cloud database and cannot grant approvals.
The approved-only export must already pass the phone-side review checks.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.public_archive import retain_public_records
from scripts.mobile_sync_upload import validated
from scripts.offline_snapshot import (
    MAX_STORIES,
    load_mobile_reviewed,
    merge_mobile_reviewed,
    mobile_reviewed_story,
)

PUBLIC = Path("public/news-data.json")
REVIEWED = Path("public/mobile-reviewed.json")
ARCHIVE = Path("app/data/public-archive.json.gz")


def publish(root: Path = Path("."), now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    target = root / PUBLIC
    reviewed_file = root / REVIEWED
    archive_path = root / ARCHIVE

    if not target.is_file():
        raise ValueError("Public feed missing; refusing to replace it")
    public = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(public, list) or len(public) > MAX_STORIES:
        raise ValueError("Existing public feed malformed; refusing to modify it")

    incoming = load_mobile_reviewed(reviewed_file)
    if not incoming:
        return {"reviewed": 0, "eligible": 0, "inserted": 0, "changed": False}

    # Reject the whole feed on any unapproved item rather than skipping a
    # malicious or partial record and claiming the export was verified.
    validated(incoming)
    eligible = [story for row in incoming
                if (story := mobile_reviewed_story(row, now)) is not None]

    # A news item older than the source freshness policy remains in private
    # storage; do not republish it as a current event under a new timestamp.
    merged, added = merge_mobile_reviewed(public, incoming, now)
    if added == 0:
        return {
            "reviewed": len(incoming), "eligible": len(eligible),
            "inserted": 0, "changed": False,
        }

    # Preserve the approved story in the public archive even if the rotating
    # 140-entry home page window is too full to show it.
    retain_public_records(public + merged + eligible, path=archive_path)
    output = json.dumps(merged, ensure_ascii=False, separators=(",", ":")) + "\n"
    if target.read_text(encoding="utf-8") != output:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".mobile-approval-", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {
        "reviewed": len(incoming),
        "eligible": len(eligible),
        "inserted": added,
        "changed": True,
    }


def main():
    result = publish()
    for key, val in result.items():
        print(f"{key}: {val}")
    print("NO AUTO-APPROVAL; PUBLISHED FEED ONLY")


if __name__ == "__main__":
    main()
