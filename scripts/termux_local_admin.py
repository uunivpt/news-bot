"""Start a private writable PoliticsHub Admin Room directly on the Termux phone.

No Neon, no public database listener, no GitHub secret and no cloud tunnel.
The admin HTTP listener ONLY accepts this phone's 127.0.0.1 interface.

Run: python scripts/termux_local_admin.py --start
Open: http://127.0.0.1:8765/admin/
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
# Running `python scripts/termux_local_admin.py` normally puts only scripts/
# on sys.path, not the project root containing api/ and app/.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HOME = Path.home()
PORT = 8765
HOST = "127.0.0.1"
DEFAULT_OWNER = "pushkarthawari"
BASE = f"http://{HOST}:{PORT}"
LOCAL_DSN = "postgresql://postgres@127.0.0.1:5432/politicshub?sslmode=disable"
PID = HOME / ".local/share/politicshub/phone-admin.pid"
LOG = HOME / ".local/share/politicshub/phone-admin.log"
BRIDGE_SECRET_FILE = HOME / ".config/politicshub/admin-bridge-secret"


def load_bridge_secret():
    """Load only the configured private file; never shell-source an env file."""
    value = os.getenv("POLITICSHUB_ADMIN_BRIDGE_SECRET", "").strip()
    path = Path(os.getenv("POLITICSHUB_ADMIN_BRIDGE_SECRET_FILE") or str(BRIDGE_SECRET_FILE)).expanduser()
    legacy = HOME / ".politicshub-admin-bridge.secret"
    if not os.getenv("POLITICSHUB_ADMIN_BRIDGE_SECRET_FILE") and not path.exists() and legacy.exists():
        path = legacy
    if not value and path.exists():
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("Bridge secret file must be a regular private file (0600)")
        value = path.read_text().strip()
    if value:
        if len(value) < 32:
            raise ValueError("Bridge shared secret must be at least 32 characters")
        os.environ["POLITICSHUB_ADMIN_BRIDGE_SECRET"] = value
        return True
    return False


def configure_private_app():
    """Called only by the local daemon, not by the public Vercel API."""
    from api.index import app
    from flask import jsonify, request, g

    app.config.update(
        SESSION_COOKIE_NAME="politicshub_phone_admin",
        SESSION_COOKIE_SECURE=False,  # Only loopback HTTP; never remote.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_PATH="/",
    )

    @app.before_request
    def require_loopback():
        # A named HTTPS outbound tunnel delivers requests to 127.0.0.1.
        # In bridge mode EVERY request must carry a fresh signed gateway
        # assertion; a public tunnel URL alone never grants admin access.
        secret = os.getenv("POLITICSHUB_ADMIN_BRIDGE_SECRET", "")
        from urllib.parse import urlsplit
        hostname = (urlsplit("//" + request.host).hostname or "").lower()
        if secret:
            from app.remote_admin_bridge import verify_phone_bridge
            # Reverse proxies may preserve the caller's address. The HMAC,
            # including path/body/time/nonce, authenticates the gateway; an IP
            # reported by that proxy does not. Check the signature first.
            if verify_phone_bridge(request, secret):
                g.phone_bridge_verified = True
                return None
        # Direct phone browser access remains possible even with a bridge
        # configured, but requires BOTH a local peer and a local Host header.
        if request.remote_addr == HOST and hostname in {HOST, "localhost"}:
            return None
        return jsonify({"error": "Secure phone gateway required" if secret else "Phone-local admin only"}), 403

    @app.after_request
    def local_http_headers(response):
        # A loopback-only admin panel needs HTTP assets to load locally.
        response.headers.pop("Strict-Transport-Security", None)
        csp = response.headers.get("Content-Security-Policy", "")
        response.headers["Content-Security-Policy"] = csp.replace(
            "; upgrade-insecure-requests", ""
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def create_local_owner(conn, password, *, reset=False, username=DEFAULT_OWNER):
    """Only after authenticating as local PostgreSQL superuser."""
    from werkzeug.security import generate_password_hash

    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
        raise ValueError("Invalid owner username")
    if len(password) < 10 or len(password) > 256:
        raise ValueError("Owner password must be between 10 and 256 characters")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS admin_users
           (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner', created_at TEXT NOT NULL)"""
    )
    old = conn.execute(
        "SELECT username FROM admin_users WHERE username=%s", (username,)
    ).fetchone()
    if old and not reset:
        return False
    from datetime import datetime, timezone
    conn.execute(
        """INSERT INTO admin_users (username,password_hash,role,created_at)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (username) DO UPDATE
           SET password_hash=EXCLUDED.password_hash, role='owner'""",
        (username, generate_password_hash(password), "owner",
         datetime.now(timezone.utc).isoformat()),
    )
    return True


def _listening():
    try:
        from urllib.request import Request
        secret = os.getenv("POLITICSHUB_ADMIN_BRIDGE_SECRET", "")
        headers = {}
        if secret:
            from app.remote_admin_bridge import bridge_headers
            headers = bridge_headers(secret, "GET", "/api/health", b"")
        with urlopen(Request(BASE + "/api/health", headers=headers), timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def stop_local_daemon():
    """Stop only the exact daemon started by this launcher, never PostgreSQL."""
    try:
        pid = int(PID.read_text().strip())
        if pid <= 1:
            return False
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\x00")
        allowed = {Path(__file__).resolve(), HOME / "politicshub-live-upload/scripts/termux_local_admin.py"}
        releases = HOME / ".local/share/politicshub/releases"
        scripts = [Path(os.fsdecode(arg)) for arg in command if arg.endswith(b"/termux_local_admin.py")]
        recognized = any(path in allowed or (path.is_relative_to(releases) and path.name == "termux_local_admin.py") for path in scripts)
        if not recognized or b"--serve" not in command:
            return False
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                PID.unlink(missing_ok=True)
                return True
            time.sleep(0.1)
        return False
    except FileNotFoundError:
        return not _listening()
    except (OSError, ValueError):
        return False


def serve():
    # A fresh private secret per runtime; never reuse the Vercel session key.
    os.environ.pop("VERCEL", None)
    os.environ.pop("POLITICSHUB_GITHUB_FEED_ONLY", None)
    os.environ["POLITICSHUB_LOCAL_ADMIN"] = "1"
    os.environ["DATABASE_3URL"] = LOCAL_DSN
    os.environ.pop("DATABASE_URL", None)
    os.environ["FLASK_SECRET_KEY"] = secrets.token_urlsafe(48)

    from werkzeug.serving import make_server
    app = configure_private_app()
    from app.phone_publication import start_delivery_worker
    start_delivery_worker()
    from app.phone_collection import start_collection_worker
    start_collection_worker()
    print(f"PRIVATE TERMUX ADMIN STARTED: {BASE}/admin/", flush=True)
    make_server(HOST, PORT, app, threaded=True).serve_forever()


def start(reset=False, restart=False, username=DEFAULT_OWNER):
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
        raise ValueError("Invalid owner username")
    listening = _listening()
    if listening and not reset and not restart:
        print("PHONE ADMIN ALREADY LISTENING:", BASE + "/admin/")
        print("No other server was started; phone DB unchanged")
        return 0

    try:
        import psycopg
    except ImportError:
        print("Missing psycopg: install the project's requirements first")
        return 1

    if subprocess.run(
        ["pg_isready", "-q", "-h", HOST, "-p", "5432"],
        check=False,
    ).returncode != 0:
        print("STOP: Termux PostgreSQL is not running")
        return 1

    pg_password = getpass.getpass("Termux PostgreSQL postgres password (hidden): ")
    if not pg_password:
        print("STOP: no PostgreSQL password entered")
        return 1

    try:
        with psycopg.connect(
            dbname="politicshub", user="postgres", host=HOST,
            port=5432, sslmode="disable", password=pg_password,
            connect_timeout=6, autocommit=True,
        ) as conn:
            record = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()
            print("PRIVATE POSTGRESQL CONNECTED; news records:", record[0])
            exists = conn.execute(
                "SELECT to_regclass('public.admin_users')"
            ).fetchone()[0]
            old = conn.execute(
                "SELECT 1 FROM admin_users WHERE username=%s", (username,)
            ).fetchone() if exists else None
            if not old or reset:
                owner_password = getpass.getpass(
                    f"Set {username} website login password (10+ chars): "
                )
                confirmation = getpass.getpass("Repeat website login password: ")
                if owner_password != confirmation:
                    print("STOP: passwords do not match")
                    return 1
                created = create_local_owner(conn, owner_password, reset=reset, username=username)
                if created:
                    print("LOCAL OWNER ACCOUNT READY:", username)
            else:
                print("Using existing", username, "account; --reset-owner to change its password.")
    except (psycopg.Error, ValueError) as exc:
        print("STOP: local credential or database check failed:", type(exc).__name__)
        return 1

    if listening and not restart:
        # Resetting the persisted account is useful specifically when an
        # existing server is running. Never start a second listener for it.
        print("LOCAL OWNER PASSWORD UPDATED; existing phone server kept running")
        print("LOGIN:", BASE + "/admin/", "as", username)
        return 0

    if restart and not stop_local_daemon():
        print("STOP: could not identify/stop the existing launcher-owned daemon")
        print("No database or unrelated process was stopped")
        return 1

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.touch(mode=0o600, exist_ok=True)
    LOG.chmod(0o600)
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["DATABASE_3URL"] = LOCAL_DSN
    env["PGPASSWORD"] = pg_password  # In the local process only. Never logged/saved.
    env["POLITICSHUB_LOCAL_ADMIN"] = "1"
    env.pop("VERCEL", None)
    env.pop("POLITICSHUB_GITHUB_FEED_ONLY", None)
    with LOG.open("ab") as log:
        child = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve()), "--serve"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    pg_password = ""
    # Termux can cold-import many Python packages substantially slower than CI.
    for _ in range(48):
        if child.poll() is not None:
            print("STOP: admin daemon failed; see", LOG)
            return 1
        if _listening():
            PID.write_text(str(child.pid))
            PID.chmod(0o600)
            print("WRITABLE PHONE ADMIN RUNNING:", BASE + "/admin/")
            print("LOGIN:", username, "(your chosen password)")
            print("Public website admin can use this phone through its configured signed bridge.")
            print("PostgreSQL only on the phone; no reboot needed.")
            return 0
        time.sleep(0.35)
    print("Unable to verify local web listener; see", LOG)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--start", action="store_true")
    group.add_argument("--serve", action="store_true")
    group.add_argument("--reset-owner", action="store_true")
    group.add_argument("--restart", action="store_true",
                       help="Load updated code; keep PostgreSQL and existing owner password")
    parser.add_argument("--owner", default=DEFAULT_OWNER,
                        help="Website login username; existing other accounts are preserved")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", args.owner):
        parser.error("Owner username must be 3-40 letters, digits, dots, underscores or hyphens")
    configured = load_bridge_secret()
    print("SIGNED PHONE BRIDGE:", "configured" if configured else "not configured; direct phone access only")
    if args.serve:
        serve()
        return 0
    return start(reset=args.reset_owner, restart=args.restart, username=args.owner)


if __name__ == "__main__":
    sys.exit(main())
