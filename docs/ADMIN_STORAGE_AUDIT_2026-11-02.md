# Admin Room and phone storage repair

## Findings and changes

The public `/api/admin/me` request reached an upstream guard and returned 403
`Phone-local admin only`. That message can mean either a non-loopback peer or a
non-local Host with no shared-secret configuration; it does not prove a bad user
password or a failed database. A valid signed gateway assertion is now verified
before the peer-address restriction. Unsigned direct access still needs both a
loopback peer and local Host. Shared secrets load from a private configured file,
including the existing legacy file location; they are never generated or changed
by the repair.

The gateway now relays only the phone session cookie, preserves cookie deletion
on logout, rejects tunnel HTML/redirects masquerading as JSON success, handles
interrupted responses, and preserves legitimate authenticated PDF reports.
The browser verifies `/me` and CSRF/session retention after login before opening
the workspace. A malformed stored password verifier fails authentication instead
of causing HTTP 500. The stale preview-DOM reference that broke logout is removed.

The generated-video toolchain, templates, renderer, audio generator, publication
receipt, obsolete workflows, dependency automation and admin telemetry are
removed. The website's news pipeline and article/social preview images remain.
Unknown legacy database fields are excluded by a public API allowlist.

## Phone persistence and upgrade

`scripts/termux_database_check.py` reads actual local PostgreSQL identity, row
counts, replica status and durability settings. Its optional `--verify-write`
commits a synthetic marker, reads it through a new connection, then deletes only
that marker. `--backup` creates a private atomic custom-format pg_dump and checks
its archive directory. No news or login rows are overwritten by these checks.

`scripts/termux_admin_update.py` accepts an immutable full commit SHA. Before
changing source it runs the reviewed persistence check and database backup.
Local staged/unstaged/untracked edits are preserved in a local stash rather than
silently reapplied over reviewed code. It only fast-forwards the expected main
checkout, applies tracked deletions, expands existing sparse rules for runtime
files, compiles and restarts the launcher-owned daemon. It does not reset the
owner password, replace PostgreSQL or expose the database port. Divergent history
and unrecognized daemon processes stop the update.

The owner-reset command now actually resets an explicitly requested account even
if the daemon is running; ordinary restart preserves the account. Passwords are
entered only in Termux's hidden prompts, never in chat or command-line arguments.

## Validation

- Full Python suite: 335 tests passed with local PostgreSQL 18, none skipped.
- JavaScript suite: 28 tests passed; 19 files passed syntax checking.
- Reader browser suite: 23 flows passed.
- Admin Room browser suite: 18 flows passed, including live-database owner login,
  saved settings/history, logout, outage recovery, write restrictions and reauth.
- Signed-gateway integration: real password check, external-peer valid signature,
  retained secure cookie, `/me`, writable workspace, CSRF denial and logout passed.
- Independent real PostgreSQL persistence probe passed; fsync, full_page_writes
  and synchronous_commit were on. This was a local synthetic database, not the
  user's phone.

The actual phone must run the published updater before claiming its running
service or disk storage has been repaired. Public GitHub-feed health alone does
not establish phone database availability. No credentials were reset or printed,
and no real phone database was accessed from this workspace.
