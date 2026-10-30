# NewsDesk

Automated source collector and deterministic news publishing platform.

## Flow
Telegram/RSS/permitted websites → collector → duplicate check → PostgreSQL → deterministic newsroom bot → publication policy → website.

Public site exposes only published stories. Source name and original source link are shown publicly. Admin is separate at `/admin/`.

## Sources
Configure permitted sources in `config/sources.json`. Do not copy full copyrighted articles; keep source attribution and link to the original source. Private sources remain disabled until collection permission is configured.

## Environment
- Database: `DATABASE_3URL` (preferred; legacy `DATABASE_URL` remains a local compatibility fallback)
- Admin: `FLASK_SECRET_KEY`, `ADMIN_USERS_JSON` (username → Werkzeug password hash)
- Fixed music: `FIXED_AUDIO_PATH` on the worker. Only use music you have permission to publish.
- India news APIs: `NEWSAPI_KEY`, `NEWSDATA_API_KEY`.
Story processing is deterministic-only: source text is cleaned, selected, and assembled without an external LLM/API.

Generate admin hashes with `python scripts/hash_password.py`.

## Automation
`collector.yml` collects sources; a successful collection triggers `news-processing.yml`, which publishes website stories. Existing scheduled triggers remain as recovery paths. Both use concurrency groups to prevent overlapping copies of the same worker. GitHub schedule times are best-effort, not a five-minute SLA; an external dispatch scheduler can trigger the collector for a stricter cadence.

Both collection paths receive news API keys. Source failures appear in the Actions summary and warnings; complete source failure fails the run. HTTP 403 responses from government sites require an approved accessible feed or permission from the provider; they are not bypassed.

The collector runs every 30 minutes and already refreshes the emergency source
feed when the database is quota-blocked. Independent emergency recovery runs
every three hours; Hindi remains hourly. This permits at most 80 scheduled
data-refresh commits/day (48 + 8 + 24), rather than overlapping 20-minute
collectors that can exhaust a 100-deployment daily allowance. GitHub schedules
are best-effort; code releases and other projects also use deployment capacity.

Image acquisition tries up to five relevant licensed candidates before falling back to a text-only Reel. Article text retains the lead fact even when the headline repeats it; summaries still avoid headline repetition.

## Local test
`pip install -r requirements.txt`
`python run.py --once`
`python scripts/auto_publish.py`

The worker uses PostgreSQL from `DATABASE_3URL` (or legacy `DATABASE_URL`) and uses SQLite as a local-development fallback.

## Reader tools and reliability checks

`/sources.html` links to original publishers and official records. `/saved.html`
stores up to 100 article links on the reader's browser after optional preferences
are allowed. Article pages include text-size controls, a print layout and the
existing share sheet. These features do not require an account.

Public API cards omit full articles; `/api/news/<id>` returns the article body.
The command center uses the uncached `/api/admin/news` endpoint for private
listing/filtering. Anonymous public responses avoid `Vary: Cookie`, which would
disable Vercel CDN caching. Authenticated responses remain `private, no-store`.

Web PostgreSQL connections use a process-local pool capped at 4 connections and
16 waiters, with a 2-second acquisition timeout and 5-second statement deadline.
Use Neon's pooled endpoint for web traffic. Core schema migration is skipped by
Vercel web requests; the existing collection/migration worker initializes the
schema. Component telemetry setup is cached once per database/process.

`ADMIN_USERS_JSON` can bootstrap hashed owner credentials only into an empty
admin-user table. Existing owners are never overwritten or supplemented from a
stale environment variable. Plaintext passwords are rejected.

```bash
python -m unittest discover -s tests -v
node --test tests/*.test.cjs reel/scripts/layout.test.mjs
pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/browser_audit.py --serve-fixture --base-url http://127.0.0.1:8010
```

Set `TEST_POSTGRES_URL` to an isolated local PostgreSQL database to enable the
100,000-record integration checks. The fixtures refuse a remote database host.
CI runs these checks on PostgreSQL 18 and runs browser flows with a temporary
SQLite fixture. `scripts/load_public.py` provides a small local HTTP benchmark.
See [the audit and capacity notes](docs/AUDIT_2026-10-30.md) for scope and limits.

<!-- deployment refresh -->
