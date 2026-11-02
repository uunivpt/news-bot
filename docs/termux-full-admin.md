# PoliticsHub full-write Admin Room on the Termux phone

The Admin Room uses the real phone PostgreSQL database. Direct phone access is
`http://127.0.0.1:8765/admin/`. The public `/admin/` can also edit this same
phone database when the signed HTTPS bridge is configured; without that bridge,
public access remains read-only. It never silently substitutes a local SQLite
file or the public JSON news feed for writable PostgreSQL.

The phone daemon binds 127.0.0.1 only. A configured tunnel may report the browser's
external address; fresh HMAC authentication authorizes those gateway requests.
Unsigned direct requests require both a loopback peer and a local Host header.
Neither a claimed Host nor a proxy-supplied address alone authorizes remote use.

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

**Important:** Direct phone browsing uses loopback HTTP. Do not expose port
8765 or PostgreSQL publicly; use only the configured signed HTTPS bridge for
remote admin access. It has
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

After updating source, `--restart` reloads the launcher-owned daemon while
preserving the database and existing owner password. It stops only the PID whose
command matches the recognized launcher, never PostgreSQL or the collector.
`--reset-owner` explicitly changes the owner password, even while the existing
server is running; normal updates never invoke it.

## Check committed storage and make a backup

Run on the real phone, after updating the source:

```sh
env -u DATABASE_URL -u DATABASE_3URL python scripts/termux_database_check.py
```

The default reads committed PostgreSQL counts, collection time, database size,
`fsync`, `full_page_writes` and `synchronous_commit`, without changing records.
To test an actual committed write across fresh connections and create a private
backup, use:

```sh
env -u DATABASE_URL -u DATABASE_3URL python scripts/termux_database_check.py --verify-write --backup
```

That command prompts for the local PostgreSQL password in Termux. It uses a
separate empty probe table and deletes its marker afterwards; it never modifies
news or owner records. A custom-format `pg_dump` archive is created atomically
under `~/.local/share/politicshub/backups` with mode 0600 and checked using
`pg_restore --list`. Connection readback plus durability settings are evidence
of committed storage, not a guarantee against device loss; keep a protected
backup outside the phone as well. No test on a cloud fixture proves phone data.

## Apply a reviewed release safely

`scripts/termux_admin_update.py --ref FULL_COMMIT_SHA --apply` works with the
existing `~/politicshub-live-upload` main-branch checkout. It fetches exactly the
reviewed commit, refuses divergent local history, first runs the database
readback/backup checks, saves tracked and untracked local edits in a local Git
stash, then fast-forwards the checkout including tracked file deletions. Existing
sparse-checkout rules are expanded to include all app/API/admin dependencies.
Local edits stay in the stash and are not automatically applied over fixed code.
Ignored local data, credential files and logs are retained. It restarts the
recognized admin daemon; it never resets the owner password.

The launcher automatically loads a matching bridge secret already provided in
`POLITICSHUB_ADMIN_BRIDGE_SECRET`, an explicit private
`POLITICSHUB_ADMIN_BRIDGE_SECRET_FILE`, the private default
`~/.config/politicshub/admin-bridge-secret`, or the existing legacy
`~/.politicshub-admin-bridge.secret`. Files must be regular and mode 0600. A
missing secret permits direct phone access only; a short or insecure secret file
fails visibly. No new shared secret is generated or substituted for Vercel's.
Do not share passwords or private logs in chat.
