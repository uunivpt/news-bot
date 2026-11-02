# PoliticsHub full-write Admin Room on the Termux phone

The public website at https://www.politicshub.in/admin/ remains read-only
because it is deployed on Vercel and intentionally has **no connection** to
the phone's writable PostgreSQL database. Granting the Vercel recovery
session write permission does not restore a database: it merely creates
misleading controls and insecure data loss.

Instead, this setup starts the existing **full editable Admin Room** on the
phone itself, using the exact same UI and API, but with the **real phone
PostgreSQL**. It binds **127.0.0.1 ONLY**; no public port, Neon, tunnel or
cloud database needed.

## One-time start in Termux

```sh
cd "$HOME/politicshub-live-upload" &&
git pull --ff-only origin main &&
git sparse-checkout add scripts/termux_local_admin.py &&
env -u DATABASE_URL -u DATABASE_3URL python scripts/termux_local_admin.py --start
```

The launcher:
1. Checks local PostgreSQL on `127.0.0.1:5432`.
2. Requests the **local postgres database password** in a hidden prompt.
3. On first use, requests a new **localowner website login password** twice.
4. Hashes the browser login password in the private local `admin_users` table.
5. Starts a separate loopback-only Admin Room service, then reports its address.

Open **http://127.0.0.1:8765/admin/** from the **same phone**, and log in as
`localowner` with the password you chose. The server runs in Termux while
Android allows the background process. It never displays or stores the
postgres password on disk, and neither secret is sent to GitHub/Vercel.

**Important:** The browser uses loopback HTTP, not internet HTTP. Do not
expose port 8765 with port-forwarding, public tunnels or proxies. It has
same-site, HTTP-only session cookies, CSRF checks, an eight-hour owner
session and a local-host/remote-address restriction.

## Available owner writes

- Edit story headline, summary, category and other supported metadata.
- Inspect private pending news and full database queue.
- Record independent source evidence, human verification and approval one
  story at a time, with audit entries.
- Publish an approved, fresh, source-attributed, substantial article.
- Reject bad reporting and update supported newsroom settings.
- Review activity, sources, agents and operational diagnostics.

The public news site continues to serve GitHub-published news. After you
approve and publish a story locally, the already-installed phone scheduler
exports **approved-only** items to GitHub on its next cycle. The new GitHub
workflow merges them into the public feed. You do not need to restart the
phone. There is no bulk auto-approval, and a review click does not itself
publish a story.

The existing web Admin Room doesn't have physical deletion controls, nor
does this setup silently delete historical records. Rejection/unpublication
and auditability are safer defaults.

## If the app stops on Android

The process is not guaranteed to survive Android battery management,
phone shutdown or Termux force-stop. Run the start command again; the existing
web owner password stays hashed in PostgreSQL. The postgres password must
be entered again, since it was deliberately not persisted.

Log file (private mode 0600):
`~/.local/share/politicshub/phone-admin.log`

To set a new localowner password, stop the existing local server deliberately
before using `--reset-owner`. Do not share passwords, logs containing
sensitive data, or database credentials in chat.
