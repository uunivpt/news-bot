# Phase 4 — Operational history and newsroom alerts

This release extends the existing, authenticated **Admin Room → Source coverage** panel. It does not modify the public publishing gate, change an editorial decision, or connect private phone data to a public endpoint.

## Evidence and alert rules

- **Source history:** Each finished `healthy`, `failed` or `not_configured` collection check is appended to `ph_source_collection_history`. The existing `ph_source_collection` latest-outcome table remains intact. `checking` (a transient state) is not counted as an outcome. Only error **classes** are stored; source URLs, exception strings, API tokens and passwords are never copied into history.
- **Retention:** The phone collector prunes source-outcome history older than **45 days** during its next completed check. A 14-day source outcome and published-story trend uses database records. History is **not backfilled** from the most recent outcome; no fabricated older points.
- **Source incidents:** latest failed, overdue and not-configured source attempts; status is not inferred from article counts.
- **Delivery incidents:** failed published-story delivery, or queued/syncing delivery unchanged for over **45 minutes**. A database queue's `synced` state alone is not proof of real-time anonymous URL visibility.
- **Corrections:** a proposed correction still pending after **6 hours**, or another editorial update pending after **24 hours**. Alerts are advisory; an authorized editor must compare evidence and make the publication decision.
- **Security:** only authenticated users with `operations.read` receive the private Phase 4 panel data. SQL queries are read-only, parameterized using the existing admin story scope, and capped at 30 alerts and 40 follow-ups. No new admin GET can create tables.
- **Unavailable states:** if the secure phone bridge is offline or a history table has not yet been initialized by the upgraded collector, the panel reports **Unavailable** or **Not recorded**, never zero successful/failed checks.
- **Delivery:** alert analysis is calculated on Admin Room refresh, not a push notification. Nothing calls, emails, retries, or auto-publishes on its own.

## Independent public monitoring

`.github/workflows/provider-health.yml` runs the existing credential-free public reliability check every two hours. Failing endpoints are marked with GitHub Actions `::error::` annotations and a failed workflow run, which can be seen in **GitHub → Actions**. GitHub account notification preferences determine whether that becomes an email; no new private notification channel was enabled.

## Rollout and verification

1. GitHub CI, JavaScript, Postgres/SQLite tests and browser fixtures must pass before merging.
2. Vercel deploys the reviewed `main` commit automatically. Verify deployment `READY` and live Admin assets, homepage/news API and health. **Production code deployment does not update the Termux worker automatically.**
3. The phone admin/collector must later run the reviewed code using its existing signed updater workflow. Only subsequent completed source checks populate the 14-day chart.
4. If the phone or its secured bridge is offline, private metrics stay unavailable. Do not expose PostgreSQL to the internet or share credentials to make the metrics appear.

No private credentials are required for the new public-health schedule.
