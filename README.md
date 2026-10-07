# NewsDesk

Automated source collector and deterministic news publishing platform.

## Flow
Telegram/RSS/permitted websites → collector → duplicate check → PostgreSQL → deterministic newsroom bot → publication policy → website + Reel graphic → optional Instagram publishing.

Public site exposes only published stories. Source name and original source link are shown publicly. Admin is separate at `/admin/`.

## Sources
Configure permitted sources in `config/sources.json`. Do not copy full copyrighted articles; keep source attribution and link to the original source. Private sources remain disabled until collection permission is configured.

## Environment
- Database: `DATABASE_URL`
- Admin: `FLASK_SECRET_KEY`, `ADMIN_USERS_JSON` (username → Werkzeug password hash)
- Instagram: `META_ACCESS_TOKEN`, `META_INSTAGRAM_ACCOUNT_ID`, optional `META_API_VERSION`
- Public Reel storage: `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_UPLOAD_PRESET`
- Fixed music: `FIXED_AUDIO_PATH` on the worker. Only use music you have permission to publish.
- India news APIs: `NEWSAPI_KEY`, `NEWSDATA_API_KEY`.
Story processing is deterministic-only: source text is cleaned, selected, and assembled without an external LLM/API.

Generate admin hashes with `python scripts/hash_password.py`.

## Automation
`collector.yml` collects sources; a successful collection triggers `news-processing.yml`, which publishes website stories and then triggers `instagram-publisher.yml`. Existing scheduled triggers remain as recovery paths. All three use concurrency groups to prevent overlapping copies of the same worker. GitHub schedule times are best-effort, not a five-minute SLA; an external dispatch scheduler can trigger the collector for a stricter cadence.

Both collection paths receive news API keys. Source failures appear in the Actions summary and warnings; complete source failure fails the run. HTTP 403 responses from government sites require an approved accessible feed or permission from the provider; they are not bypassed. Instagram Login resolves its account from the token and caches it per worker process; Facebook Login retains the explicit account setting.

Image acquisition tries up to five relevant licensed candidates before falling back to a text-only Reel. Article text retains the lead fact even when the headline repeats it; summaries still avoid headline repetition.

## Local test
`pip install -r requirements.txt`
`python run.py --once`
`python scripts/auto_publish.py`

The worker uses PostgreSQL when `DATABASE_URL` is present and otherwise falls back to SQLite.

<!-- deployment refresh -->
