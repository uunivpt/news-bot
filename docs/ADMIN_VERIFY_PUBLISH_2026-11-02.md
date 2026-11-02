# Admin Room: direct publication and actual data

## Current action

The owner's **Verify & publish** action publishes the selected story in one
authenticated, CSRF-protected transaction. It does not open source-URL, notes,
typed-confirmation or subsequent Publish prompts. Selected bulk publication uses
the same action sequentially for up to ten stories. A repeated request does not
create duplicate publication/audit records; optional revisions reject stale
edits. Readable source summaries can publish as briefs without manufacturing a
full article. Historical items keep their original date; future source dates and
missing readable content/source URLs return specific errors.

The click records the editor's publication decision, not an independently
performed cross-source fact check. It does not fabricate evidence, source-fetch
success, rights or originality. Separate ad eligibility remains conservative.
Existing matching genuine full-copy monetization evidence is retained.

## Public delivery

The commit queues a durable SQL delivery receipt and wakes a phone-only worker.
It uses the already-provisioned phone SSH identity and a separate, tool-owned
Git checkout. It does not reset the operator's source checkout or collect/approve
additional news. A single push updates the reviewed export, full public article
copy and archive. Source URLs retain stable public IDs even when they differ
from private phone primary keys. Only allowlisted public fields are exported.

The dashboard distinguishes saved publication from public delivery: queued,
failed, not configured or synced. Failed delivery never changes a committed
story back to pending. Retrying Verify can requeue delivery without republishing
the database row. The worker resumes queued work on admin restart and uses a
bounded retry budget. Missing credentials do not become a successful sync.
The private `/api/admin/story/ID/delivery` endpoint reports the actual receipt.

Synced links include the immutable Git commit. Public rendering reads that
commit's full feed immediately, without waiting for the bundled archive to be
redeployed. Mutable reviewed-article lookup refreshes separately; public feed
cache lifetimes are shorter. Network/CDN propagation is still not a guarantee of
zero elapsed time. The UI polls boundedly and never reports synced before the
push receipt exists.

## Data and reliability fixes

The authenticated live baseline contained 454 stored stories, 453 pending and
one published. The workspace's server work took about 210 ms, but a cold network
request took 9.8 seconds; operations hit the previous 12-second gateway timeout.
The gateway now allows 20 seconds. Browser reads can retry a transient failure
once under one overall deadline; mutations never automatically retry. Stale
responses cannot overwrite newer workspace state, and a refresh failure cannot
undo or misreport a successful publication. Initial schema/user setup is cached
per database/configuration instead of running DDL on every admin request.

The old resource display counted a relative local `data` directory, not the
actual phone PostgreSQL database. Size now comes from `pg_database_size()`;
SQLite fixtures use allocation metadata. Missing media or failed measurement is
unavailable/not configured, not zero. Dashboard GETs do not insert resource
history or manufacture processing runs.

Actual source/story inventory is shown independently from worker history. The
live scoring, event, source-reliability and alert history tables were empty at
baseline; emptiness alone is not a failed data fetch. New real editorial
publications record a score/event without claiming independent corroboration.
Collection and publication timestamps are reported separately.

## Validation and deployment boundary

Tests cover empty-body one-click publication, concurrency/idempotency, historical
dates, readable briefs, failed post-commit telemetry/delivery, real Git push and
archive contents, canonical ID preservation, durable delivery retries, immutable
public lookup, actual PostgreSQL sizing, honest unavailable metrics, no-prompt UI,
bulk publication, transient read retry and stale-response recovery.

Both website and the phone service need this release. The deployment workspace
does not update a physical phone automatically. The reviewed phone updater backs
up PostgreSQL and local edits before applying an immutable commit and restarting
the known daemon. It preserves owner accounts. No real story was published as a
test, and no credential was printed or added to source.

Release verification: 364 Python tests passed with a real local PostgreSQL 18
fixture and none skipped; 46 JavaScript tests, 19 syntax checks, 23 reader
browser checks and 21 Admin Room browser checks passed. Git integration tests
used disposable local bare repositories, never production news publication.
