"""Coalesce source-data commits before they consume deployment capacity.

The two English feed workflows share one persisted hourly gate. Hindi has its
own hourly gate. Data collection schedules and application releases are separate.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess


INTERVAL = timedelta(hours=1)
CHANNEL_FILES = {
    "news": ("public/news-data.json", "app/data/public-archive.json.gz"),
    "hindi": ("public/hindi-news.json",),
}


@dataclass(frozen=True)
class ReleaseDecision:
    publish: bool
    reason: str
    next_allowed_at: datetime | None = None


def decide_release(channel, changed, state, now):
    if channel not in CHANNEL_FILES:
        raise ValueError("Unknown feed channel")
    if not changed:
        return ReleaseDecision(False, "No changed source data")
    if state is None:
        return ReleaseDecision(True, "First release for this feed gate")
    if not isinstance(state, dict) or state.get("version") != 1 or state.get("channel") != channel:
        raise ValueError("Invalid feed release state")
    try:
        previous = datetime.fromisoformat(str(state["last_commit_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("Invalid feed release timestamp") from error
    if previous.tzinfo is None or previous > now:
        raise ValueError("Feed release timestamp is naive or ahead of the runner clock")
    next_allowed = previous + INTERVAL
    if now < next_allowed:
        return ReleaseDecision(False, "Coalescing changed data until the next release window", next_allowed)
    return ReleaseDecision(True, "Hourly release window is open")


def prepare_release(channel, root, now, *, dry_run=False):
    paths = CHANNEL_FILES[channel]
    diff = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], cwd=root, check=False)
    if diff.returncode not in (0, 1):
        raise RuntimeError("Could not inspect feed changes")
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *paths], cwd=root, text=True)
    changed = diff.returncode == 1 or bool(untracked.strip())
    state_path = root / ".github" / "feed-release-state" / (channel + ".json")
    state = json.loads(state_path.read_text(encoding="utf-8")) if changed and state_path.exists() else None
    decision = decide_release(channel, changed, state, now)
    if decision.publish and not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "channel": channel,
                                        "last_commit_at": now.isoformat()}, indent=2) + "\n", encoding="utf-8")
        temporary.replace(state_path)
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=CHANNEL_FILES, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Inspect the decision without changing state or step outputs")
    options = parser.parse_args()
    decision = prepare_release(options.channel, Path.cwd(), datetime.now(timezone.utc), dry_run=options.dry_run)
    notice = decision.reason
    if decision.next_allowed_at:
        notice += "; next eligible at " + decision.next_allowed_at.isoformat()
    print(f"{options.channel}: {notice}. publish={str(decision.publish).lower()}")
    if not options.dry_run:
        output = os.getenv("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write("publish=" + str(decision.publish).lower() + "\n")
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(f"\n### {options.channel.title()} feed release\n{notice}.\n")


if __name__ == "__main__":
    main()
