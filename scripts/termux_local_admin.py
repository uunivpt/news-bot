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
BASE = f"http://{HOST}:{PORT}"
LOCAL_DSN = "postgresql://postgres@127.0.0.1:5432/politicshub?sslmode=disable"
PID = HOME / ".local/share/politicshub/phone-admin.pid"
LOG = HOME / ".local/share/politicshub/phone-admin.log"


def configure_private_app():
    """Called only by the local daemon, not by the public Vercel API."""
    from api.index import app
    from flask import jsonify, request

    app.config.update(
        SESSION_COOKIE_NAME="politicshub_phone_admin",
        SESSION_COOKIE_SECURE=False,  # Only loopback HTTP; never remote.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_PATH="/",
    )

    @app.before_request
    def require_loopback():
        hostname = (request.host or "").split(":", 1)[0].lower()
        if request.remote_addr != HOST or hostname not in {HOST, "localhost"}:
            return jsonify({"error": "Phone-local admin only"}), 403

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


def create_local_owner(conn, password, *, reset=False):
    """Only after authenticating as local PostgreSQL superuser."""
    from werkzeug.security import generate_password_hash

    if len(password) < 12 or len(password) > 256:
        raise ValueError("Owner password must be between 12 and 256 characters")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS admin_users
           (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner', created_at TEXT NOT NULL)"""
    )
    old = conn.execute(
        "SELECT username FROM admin_users WHERE username=%s", ("localowner",)
    ).fetchone()
    if old and not reset:
        return False
    from datetime import datetime, timezone
    conn.execute(
        """INSERT INTO admin_users (username,password_hash,role,created_at)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (username) DO UPDATE
           SET password_hash=EXCLUDED.password_hash, role='owner'""",
        ("localowner", generate_password_hash(password), "owner",
         datetime.now(timezone.utc).isoformat()),
    )
    return True


def _listening():
    try:
        with urlopen(BASE + "/api/health", timeout=2):
            return True
    except Exception:
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
    print(f"PRIVATE TERMUX ADMIN STARTED: {BASE}/admin/", flush=True)
    make_server(HOST, PORT, app, threaded=True).serve_forever()


def start(reset=False):
    if _listening():
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
                "SELECT 1 FROM admin_users WHERE username='localowner'"
            ).fetchone() if exists else None
            if not old or reset:
                owner_password = getpass.getpass(
                    "Create localowner website login password (12+ chars): "
                )
                confirmation = getpass.getpass("Repeat website login password: ")
                if owner_password != confirmation:
                    print("STOP: passwords do not match")
                    return 1
                created = create_local_owner(conn, owner_password, reset=reset)
                if created:
                    print("LOCAL OWNER ACCOUNT READY: localowner")
            else:
                print("Using existing localowner account; --reset-owner to change it.")
    except (psycopg.Error, ValueError) as exc:
        print("STOP: local credential or database check failed:", type(exc).__name__)
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
            print("LOGIN: localowner (your chosen password)")
            print("Public politicshub.in/admin remains separate and read-only.")
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
    args = parser.parse_args()
    if args.serve:
        serve()
        return 0
    return start(reset=args.reset_owner)


if __name__ == "__main__":
    sys.exit(main())
