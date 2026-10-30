# Admin Room

Entry point: `/admin/`. The workspace uses external CSP-compatible scripts and
styles, a responsive navigation drawer, light/dark display preference, keyboard
navigation (Ctrl/Cmd+K), and explicit data and permission status.

## Authentication and database continuity

The deployment includes the owner's salted scrypt password verifier in the
server-only `app/admin_access.py` module. No plaintext password is stored in code,
browser storage or public assets. `ADMIN_USERS_JSON`, when explicitly configured,
replaces the packaged identity; `{}` disables that fallback. Existing database
owners and their password verifiers are never overwritten. An empty owner table
can bootstrap from the configured verifier.

Normal login checks the database's user record, persistent login throttling, and
password verifier. A valid packaged/configured verifier is accepted for recovery
**only when the database is unavailable**, never after a healthy database rejects
a password. Recovery access expires after one hour and permits the workspace's
public snapshot only. It cannot inspect private moderation queues, read private
telemetry, change settings, publish/reject/edit reports, or run workers. Both the
API and UI enforce these restrictions. Database recovery does not elevate an
existing recovery session: sign out and authenticate against the database again.

Owner sessions expire after eight hours. Cookies remain Secure, HttpOnly and
SameSite=Strict. Mutations require CSRF protection; cross-origin admin requests
are rejected. A bounded per-process login limiter also operates during outages;
it complements persistent throttling and is not a distributed WAF. Existing
deployment session-signing secrets remain outside source control.

To revoke packaged recovery access, remove/replace the verifier and deploy, or
explicitly override `ADMIN_USERS_JSON`. Changing only a database password does
not change the separately configured recovery verifier. Recovery exposes only
already public reporting and cannot become owner access without database login.

## Editorial tools

- Overview: database-wide totals when live, bounded recent-story coverage, true
  snapshot freshness, content-completeness flags and dependency status.
- Newsroom: full database search with source/desk/status/review filters, 25-row
  server pagination and whitelisted sort options. Recovery searches up to 200
  loaded public reports locally; this scope is labeled explicitly.
- Inspector: original source, publication/review details, text reader and
  clipboard link. Owner editing loads full untruncated drafts on demand and uses
  revision checks plus conditional SQL updates to reject stale concurrent edits.
- Actions: process, review, publish and reject. Bulk actions are limited to ten
  stories, confirmed explicitly, and run sequentially, stopping at first failure.
  Persisted actions are recorded in the activity trail.
- Exports: filtered snapshot or current live queue page as CSV, with spreadsheet
  formula neutralization. Diagnostic JSON excludes identity, cookie, CSRF token,
  connection credentials and private story contents.
- Source coverage: publisher and desk counts from the labeled loaded sample.
  Completeness checks are not claimed as fact checking or reliability scores.
- Agent operations and QA retain existing actual worker telemetry. Unavailable
  telemetry is labeled; no success numbers or runs are invented by page refresh.
- Settings persist website publishing controls and reviewed knowledge events.
  Knowledge logging does not silently train or invoke an AI model.

Overview refresh shares in-flight requests, runs at most once per minute while
visible, and does not poll expensive telemetry views. Queue requests cancel
superseded searches and use sequence checks. Private responses are `no-store`,
and admin data is never persisted in localStorage or the service worker.

## Verification

`tests/test_admin_workspace.py` covers authentication outages, permission/CSRF/
origin/expiry boundaries, SQL filter safety, pagination and concurrent edit
protection. Real PostgreSQL checks exercise the workspace projection and queue
against 100,000 synthetic records; this is not a claim of 100,000 concurrent users.

`python scripts/admin_browser_audit.py --output /tmp/admin-browser` starts an
isolated temporary SQLite server and tests owner/recovery flows, responsive
layouts, edits, exports, knowledge/settings writes and telemetry states. It uses
synthetic credentials, never production records or real newsletter sends.
