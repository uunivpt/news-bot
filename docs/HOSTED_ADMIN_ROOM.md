# Website-hosted Admin Room

The application lives in `uunivpt/news-bot` and deploys to Vercel. Set
`POLITICSHUB_ADMIN_BACKEND=hosted` in the Production environment. The Admin Room
then runs at `https://www.politicshub.in/admin/` using the existing
`DATABASE_3URL` (or local compatibility `DATABASE_URL`) and `FLASK_SECRET_KEY`.
No phone, tunnel, SSH key or Termux process is required for login, editing or
publication. The legacy phone workflow stays available only outside hosted mode.

## Accounts and sessions

Use the existing owner username and password. Existing database accounts always
take precedence: deployment bootstrap verifiers are inserted only when
`admin_users` is empty. Passwords are never reset by this change. Sessions use
Secure, HttpOnly, SameSite=Strict cookies; authenticated responses are private
and uncacheable. Editorial writes keep role checks, CSRF checks and revision
conflict protection. Anonymous `/api/admin/me` returns `authenticated:false`
without contacting storage or a remote gateway.

## Public delivery

The current GitHub source feed remains available. Approved hosted articles and
editorial changes overlay it directly from persistent cloud storage. Rejected
or edited copies suppress their stale public versions. Untouched legacy imports
do not replace newer source copies. Full manuscripts use the article endpoint;
feed cards keep a bounded public projection. Publication reports a persisted
hosted delivery result, and the public version endpoint prompts active readers
to refresh. Public feed caching is short in hosted mode.

If storage becomes unavailable, the saved public feed remains readable while
editorial writes fail. The public health endpoint contains only `ok`; database,
session and operational diagnostics belong to the private Admin Room. Public
status links and healthy-feed technical notices have been removed. Old status
entry points lead to the Admin Room or ordinary reader preferences.

## Checks

Run the Python/Node suites plus:

```sh
python scripts/hosted_admin_browser_audit.py --output artifacts/hosted-admin
```

The audit uses temporary SQLite fixtures, forbids phone transports, and checks
login, session reload, permissions, CSRF, publication, logout, privacy and
responsive layouts. It does not submit production articles or credentials.
