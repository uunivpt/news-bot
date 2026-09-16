# News Bot — Phase 1

A modular, low-cost news collection system.

## Phase 1 scope

- Collect new items from configured RSS/Atom feeds.
- Optionally collect posts from public Telegram channels using their public preview pages.
- Normalize title, URL, source and publication time.
- Prevent duplicates using a URL hash and normalized title hash.
- Store collected items in a local SQLite database.
- Keep source configuration outside the code in `config/sources.json`.
- Run once or continuously with a configurable polling interval.

Phase 1 intentionally has **no AI**, publishing, admin dashboard, or automatic article rewriting.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp config/sources.example.json config/sources.json
python run.py --once
```

For continuous polling:

```bash
python run.py --interval 300
```

The SQLite database is created at `data/news.db`.

## Adding sources

Edit `config/sources.json` and add RSS/Atom feeds. Telegram public channels can be added by username when their public preview is accessible.

Only collect and reuse material in accordance with each source's terms, permissions, copyright rules and applicable law. The system stores metadata and links by default; it does not copy full articles.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Phase 1 data flow

`RSS / public Telegram → collector → normalize → duplicate check → SQLite`

Later phases can consume this database without changing the collection layer.
