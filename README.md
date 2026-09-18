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

No AI API, AI model, or AI API key is required by the publishing workflow. Story processing is deterministic and extractive.

Generate admin hashes with `python scripts/hash_password.py`.

## Automation
`.github/workflows/process.yml` runs every 5 minutes. It installs ffmpeg, runs the deterministic newsroom tests, repairs eligible legacy stories, processes pending stories, and publishes to Instagram only when the required Meta and public-media configuration exists.

## Local test
`pip install -r requirements.txt`
`python run.py --once`
`python scripts/auto_publish.py`

The worker uses PostgreSQL when `DATABASE_URL` is present and otherwise falls back to SQLite.

<!-- deployment refresh -->
