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
- India news APIs: `NEWSAPI_KEY`, `NEWSDATA_API_KEY`.
Story processing is deterministic-only: source text is cleaned, selected, and assembled without an external LLM/API.

Generate admin hashes with `python scripts/hash_password.py`.

## Automation
`collector.yml` refreshes and publishes the public RSS/news snapshot on its scheduled release gate, without Neon. `news-processing.yml` is a read-only quality check for the published feed; it does not publish news. `offline-feed.yml` remains a lower-frequency recovery path. The publication workflows share a concurrency group to prevent overlapping updates. GitHub schedule times are best-effort, not a five-minute SLA; an external dispatch scheduler can trigger the collector for a stricter cadence.

Both collection paths receive news API keys. Source failures appear in the Actions summary and warnings; complete source failure fails the run. HTTP 403 responses from government sites require an approved accessible feed or permission from the provider; they are not bypassed.

The collector runs every 30 minutes and refreshes the emergency source feed when
the database is quota-blocked. Independent recovery runs every three hours; both
English paths share a persisted hourly publication gate. Hindi keeps its hourly
schedule and also checks sources after successful main-branch collector runs,
with its own persisted hourly release gate. Changed source data can therefore
create at most 48 commits per 24 hours (24 English + 24 Hindi), including recovery/manual refreshes while
the gate state is retained. Collection checks continue between publication
windows; held snapshot changes are rebuilt from the next available source feeds.
GitHub schedules are best-effort. Code releases and other projects also use
deployment capacity, and this does not reset an already-exhausted allowance.
See [the deployment-budget notes](docs/DEPLOYMENT_BUDGET.md).

Article text retains the lead fact even when the headline repeats it; summaries still avoid headline repetition.

Weekly Dependabot update PRs cover Python requirements and GitHub Actions.
Dependency updates still require the repository's compatibility checks.

## Local test
`pip install -r requirements.txt`
`python run.py --once`
`python scripts/auto_publish.py`

The worker uses PostgreSQL from `DATABASE_3URL` (or legacy `DATABASE_URL`) and uses SQLite as a local-development fallback.

## Reader tools and reliability checks

The private Admin Room runs at `/admin/` on the deployed website. Production
sets `POLITICSHUB_ADMIN_BACKEND=hosted` and uses its existing cloud PostgreSQL
connection and stable session secret. GitHub stores the application code;
Vercel runs the server and the database keeps drafts, users and permissions.
The phone bridge is bypassed in hosted mode. Existing owner credentials are
preserved. See [hosted Admin Room operations](docs/HOSTED_ADMIN_ROOM.md).
System diagnostics are available inside the authenticated workspace; public
pages show reading preferences and useful loading/offline notices only.

The homepage prioritizes source-linked stories and reader-friendly density controls. The old public Reading Room dashboard and feed/source/desk statistics were retired, while the news feed, keyboard search, and reduced-motion support remain. See [the UI license notes](docs/WATERMELON_UI_LICENSE.md).
Run `python scripts/newsroom_ui_browser_audit.py` for the isolated dashboard,
keyboard and responsive checks.

`/sources.html` links to original publishers and official records. `/saved.html`
stores up to 100 article links on the reader's browser after optional preferences
are allowed. Readers can search saved headlines and sort by save time or headline;
filtering stays on this browser and does not rewrite the list. Article pages include text-size controls, a print layout and the
existing share sheet. Copy reference collects the displayed headline, source,
publication label, reading link and available original-report link, with a
selectable-text fallback if clipboard access is unavailable. It does not copy
the article body or invent missing publication metadata. These features do not
require an account.

The source directory supports keyword and source-type filters. BBC World adds
attributed international headline metadata to the existing RSS sources. Run
`PYTHONPATH=. python scripts/check_sources.py --output artifacts/sources.json`
for a read-only feed freshness report. Source HTTP reads share redirect, public
destination and streaming size checks; see
[the source hardening notes](docs/SOURCE_SAFETY_2026-10-31.md) for exact scope.

Public API cards omit full articles; `/api/news/<id>` returns the article body.
Reviewed numerical datasets can add source-linked metric cards, interactive
charts and exact-value tables to individual articles. Download chart (SVG) saves
a static image with the displayed labels, units and source context; CSV retains
exact reported precision. Canonical figures also
work without JavaScript. See [article data authoring](docs/ARTICLE_DATA.md).
The command center uses the uncached `/api/admin/news` endpoint for private
listing/filtering. Anonymous public responses avoid `Vary: Cookie`, which would
disable Vercel CDN caching. Authenticated responses remain `private, no-store`.

The homepage uses `home-critical.css`, built from `site.css`, `editorial.css`
and `polish.css` in that order. After editing these source stylesheets, run
`python scripts/build_home_css.py` and commit the updated bundle. CI runs the
read-only `--check` mode to catch drift. The source Google Fonts import stays
out of the bundle; the homepage loads its font stylesheet separately.

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
node --test tests/*.test.cjs
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
