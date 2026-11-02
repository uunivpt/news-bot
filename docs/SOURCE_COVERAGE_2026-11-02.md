# Source coverage and phone collection repair

The Sources page previously counted only the latest 200 queue rows. Configured publishers with no rows, and publishers outside that sample, disappeared. TV9 Marathi, ABP Majha and The Hindu were already enabled in config/sources.json, but the private phone admin daemon did not start collection from that checkout.

The authenticated workspace now supplies a complete configured source directory merged with full database aggregates. Zero counts, disabled sources, historical sources, separate Hindi collection, missing API keys, successful fetches, failed fetches and overdue checks are distinct. No network requests, collection, telemetry schema creation or history writes occur on dashboard reads. Recovery uses explicitly labelled public snapshot counts and cannot claim phone health. The Vercel function explicitly bundles the source configuration.

The local admin daemon starts one background collection worker against its existing loopback PostgreSQL database, immediately and every 20 minutes. It loads the source configuration relative to the installed project, records actual checks, honors per-source intervals and duplicate constraints, and stores new items as pending. This worker does not approve or publish articles. Existing one-click Verify and public delivery behavior remains in place. Missing API credentials are reported without pretending a fetch succeeded.

Validation completed on 2 November 2026:

- 381 Python tests passed with local PostgreSQL 18, including full source counts across a 100,000-row synthetic archive.
- 52 JavaScript tests and public script syntax/compile checks passed.
- 21 admin browser acceptance checks passed, including source directory search, zero-count configured publishers, database drill-down, mobile layout and one-click publication.
- An independent live fetch and disposable local SQLite insertion collected The Hindu 50, TV9 Marathi 35, ABP Majha 10 and BBC India 20 items. All 115 remained pending, with zero approvals. These counts are evidence of that test only, not phone database counts.
- Actual PostgreSQL telemetry upsert preserved last success after a failed check and stored only the error class.

Phone activation requires the reviewed immutable updater command after deployment. It backs up the existing database, preserves local edits and account passwords, updates the existing checkout and restarts only its admin daemon. Existing accounts are preserved. The phone must remain running and online for private collection and the remote admin bridge.
