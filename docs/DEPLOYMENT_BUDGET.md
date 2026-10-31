# Source publication and deployment capacity

## Evidence

On 31 October 2026 Vercel rejected new production builds with HTTP 402,
`api-deployments-free-per-day`, reporting more than 100 deployments and a 24-hour
retry window. The read-only deployment listing returned 62 visible deployments
for PoliticsHub in the previous 24 hours, 56 with source-refresh commit messages.
The visible listing is not a reconstruction of Vercel's full quota counter.

The existing schedules permitted 48 collector-triggered snapshot commits,
eight independent recovery commits and 24 Hindi commits per day: 80 data-only
commits before code/preview builds or manual refreshes. A shared concurrency
group prevented simultaneous English workers, but did not prevent sequential
workers from each pushing a new deployment-triggering commit.

## Change

`scripts/feed_release_gate.py` runs after collection and before a source-data
commit. Both English workflows use channel `news`; Hindi uses channel `hindi`.
Each channel records its last eligible commit time in
`.github/feed-release-state/<channel>.json`, committed with the data files.

The gate declines unchanged data without updating state. When there are data
changes, at least one hour must have elapsed since that channel's recorded
commit. An eligible run writes its marker; the workflow includes it in the same
commit and push as the feed. A failed push therefore cannot advance the marker
on main. Separate marker files avoid English/Hindi rebase conflicts; the two
English workflows retain their shared concurrency group.

This caps new feed-data commits at 24 per channel in a rolling 24-hour window,
or 48 total, while state is retained. Manual and code-triggered source refreshes
use the same gate. Application releases do not use this gate. No Vercel setting,
paid plan, credential, publisher URL or application runtime changes are made.

English collection checks continue every 30 minutes and recovery every three
hours. During a database outage, English snapshot publication is coalesced to
at most hourly; Hindi keeps its hourly cadence. Held working files are not
committed and the next job rebuilds from the available source feeds and last
committed snapshot. This is not a guarantee that every rapidly rotating source
entry will be retained, nor an exact freshness SLA. Live healthy-database
publishing is unchanged.

## Bootstrap, recovery and limits

- A missing marker permits the first changed-data commit to establish the gate.
  Keep subsequent markers in Git; deleting/resetting them resets that budget.
- Malformed, mismatched or future-dated state fails the job instead of silently
  opening another release. Inspect the affected marker and runner clock before
  repairing it; no automatic state reset is attempted.
- Step summaries explain whether the feed was unchanged, held or eligible.
  `python scripts/feed_release_gate.py --channel news --dry-run` inspects a local
  decision without changing markers or GitHub step outputs.
- This reduces future data-build pressure. It cannot clear today's exhausted
  Vercel allowance and cannot guarantee capacity used by other work/projects.
  The previously merged reader/security release remains pending that allowance.

## Validation

Ten new tests exercise real temporary Git repositories as well as publication
decisions: staged/unstaged/untracked feed changes, unchanged/code-only changes,
dry runs, marker persistence, the exact hour boundary, invalid state, shared
English gating and independent Hindi gating. A simulated day containing all
collector/recovery/Hindi invocations produces exactly 24 English and 24 Hindi
data commits. All 240 Python tests run successfully (six optional isolated
PostgreSQL tests skipped locally). Edited workflow YAML parses and every shell
block passes `bash -n`. CI runs the repository's full checks before merge.

This is a workflow-only change; a new website preview build is unnecessary.
Rollback is a revert of the gate/workflow commit; no database migration exists.
