# Remote write access at politicshub.in/admin (phone-owned PostgreSQL)

Remote editing is enabled only when a verified HTTPS tunnel and BOTH Vercel
bridge environment variables are configured. Do not remove the existing public read-only fallback just
to reveal write buttons. Never expose PostgreSQL port 5432.

## Final network

Browser → https://www.politicshub.in/admin/ (Vercel UI)
→ same-origin admin API on Vercel
→ timestamped HMAC-signed HTTPS request to a named outbound tunnel
→ private Termux Flask Admin Room on 127.0.0.1:8765
→ PostgreSQL on 127.0.0.1:5432.

* Browser credentials are verified by the private phone, not Vercel.
* The phone keeps all data and its existing `localowner` account.
* Public news continues to load from GitHub, not from a public phone API.
* If the phone is offline, admin editing returns 503. Public news remains live.
* Review/approval remains individually verified; no anonymous editing or
  automatic bulk publishing.

## Production prerequisites

1. Create a **named Cloudflare Tunnel** in a Cloudflare-managed zone with
   a stable protected HTTPS hostname, e.g. `admin-origin.politicshub.in`.
   The authoritative DNS zone for `politicshub.in` is currently external,
   so Cloudflare Tunnel creation may require carefully transferring DNS
   management. Import ALL existing website, mail, MX, SPF, DKIM, TXT,
   and other records BEFORE touching nameservers. Never switch
   nameservers as an automatic troubleshooting step.
2. Cloudflare Tunnel routes the fixed hostname to
   `http://127.0.0.1:8765` on the SAME phone and stays connected through
   the `cloudflared` Termux process. A temporary `trycloudflare.com`
   quick tunnel is for development ONLY, not a production endpoint.
3. Generate a unique random ≥32-character shared secret in Termux.
   Keep it in a local private file (mode 0600). Do NOT paste it into chat,
   GitHub, screenshots, CLI arguments, or a webpage. Add the SAME secret
   as an encrypted **Production** Vercel env variable:
   `POLITICSHUB_ADMIN_BRIDGE_SECRET`.
4. Add the exact verified tunnel HTTPS origin (NO trailing path) as
   `POLITICSHUB_ADMIN_BRIDGE_URL` on the same Vercel project.
5. Update `scripts/termux_local_admin.py`, `api/index.py`, and
   `app/remote_admin_bridge.py` to the audited main-branch versions on
   the phone (back up locally edited files first). Start the phone service
   with `POLITICSHUB_ADMIN_BRIDGE_SECRET` loaded from the private file.
   The phone now **rejects all unsigned requests** at the public tunnel;
   direct browser visits from a loopback peer using a localhost/127.0.0.1 Host
   remain available. A valid signed gateway request is accepted even if the
   tunnel preserves the browser's external address.
6. Deploy Vercel production with the two env vars, and validate the
   following **without performing any unreviewed news publication**:

   - Open `https://www.politicshub.in/admin/`.
   - Sign in using the existing `localowner` credentials. NEVER reuse
     the PostgreSQL superuser password as a web login.
   - Inspect the workspace: it must report a **live** local DB and owner
     access, not `recovery`/snapshot.
   - Test a safe draft edit and confirm it saved in phone PostgreSQL.
   - Verify an edit audit row and CSRF protection. Do not approve or
     publish uncertain reporting.
   - Temporarily disconnect the phone and confirm admin endpoints return
     503 while the public news feed continues working.

## Important constraints

* HTTPS Cloudflare Tunnel is an optional **outbound connection** from the
  phone. It must not publish the PostgreSQL port or expose the full
  localhost filesystem.
* HMAC includes method, URL path/query, request body digest, timestamp
  and a single-use nonce. Nonces expire and are replay-protected.
* Vercel forwards ONLY allowlisted admin API endpoints, not arbitrary
  URLs, SQL, internal network paths or system commands. It rejects
  cross-origin admin requests and redirects.
* The named tunnel and Vercel project are separate third-party services;
  completing their account/DNS configuration requires the domain owner.
* Do not store credentials in JavaScript bundles, GitHub, or plain public
  `public/` files.
* Phone sleep, Android force-stop, loss of internet or tunnel disruption
  makes remote editing temporarily unavailable. For 24/7 availability,
  use an always-on private server or reliable tunnel host.

## Updating an already running phone

Use the immutable-release updater described in `termux-full-admin.md`; a source
update alone does not replace Python code already loaded in the running daemon.
The updater backs up PostgreSQL, preserves local source edits and restarts only
the launcher-owned service. Existing shared-secret files are loaded privately;
if the phone starts without the same bridge secret as Vercel, remote login is
expected to return 403 while direct phone login remains available. Never solve
that by making the phone listener public or removing gateway authentication.
