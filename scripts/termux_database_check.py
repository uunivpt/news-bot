"""Check the real phone database without touching news or login records.

Default: local read-only health/durability report using the existing worker
credential file. --verify-write performs a reversible probe in a separate table
and reads it from a fresh connection. --backup creates an atomic pg_dump archive.
The latter options prompt for the local PostgreSQL admin password; it is never
printed or saved. Run this on the Termux phone, not against a cloud database.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DATABASE = "politicshub"
WORKER_FILE = HOME / ".politicshub-worker.pgpass"
BACKUPS = HOME / ".local/share/politicshub/backups"
PROBE = "ph_runtime_persistence_probe"


def connect_args(admin=False, password=None):
    return dict(dbname=DATABASE, user="postgres" if admin else "politicshub_collector",
                host="127.0.0.1", port=5432, sslmode="disable", connect_timeout=8,
                **({"password": password} if admin else {"passfile": str(WORKER_FILE)}))


def read_health(connect, args):
    """Read committed state from this exact PostgreSQL connection, not a JSON feed."""
    with connect(**args) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        settings = {}
        for name in ("fsync", "full_page_writes", "synchronous_commit"):
            settings[name] = str(conn.execute("SHOW " + name).fetchone()[0])
        identity = conn.execute(
            "SELECT current_database(), pg_is_in_recovery(), pg_database_size(current_database())"
        ).fetchone()
        counts = conn.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE status='pending'),
            COUNT(*) FILTER (WHERE status='published'), MAX(collected_at) FROM news_items""").fetchone()
    return dict(database=identity[0], read_replica=identity[1], database_bytes=identity[2],
                news_records=counts[0], pending=counts[1], published=counts[2],
                last_collected_at=counts[3], durability=settings)


def verify_persistence(connect, args):
    """Commit a synthetic marker, reconnect/read it, then delete only that marker."""
    marker = str(uuid.uuid4())
    with connect(**args) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ph_runtime_persistence_probe
            (probe_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL)""")
        conn.execute("INSERT INTO ph_runtime_persistence_probe VALUES (%s, NOW())", (marker,))
    try:
        # A fresh connection cannot see an uncommitted insert. This verifies
        # application commit behavior, not survival of a future device failure.
        with connect(**args) as conn:
            result = conn.execute("SELECT probe_id FROM ph_runtime_persistence_probe WHERE probe_id=%s",
                                  (marker,)).fetchone()
        if not result or result[0] != marker:
            raise RuntimeError("Committed marker missing from a fresh connection")
    finally:
        with connect(**args) as conn:
            conn.execute("DELETE FROM ph_runtime_persistence_probe WHERE probe_id=%s", (marker,))
    return True


def backup_database(password, directory=BACKUPS):
    """Archive atomically; a failed dump never appears as a successful backup."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / ("politicshub-" + stamp + "-" + uuid.uuid4().hex[:8] + ".dump")
    fd, temporary = tempfile.mkstemp(prefix=".incomplete-", dir=directory)
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    try:
        with os.fdopen(fd, "wb") as stream:
            subprocess.run(["pg_dump", "--host=127.0.0.1", "--port=5432", "--username=postgres",
                            "--dbname=" + DATABASE, "--format=custom", "--no-password"],
                           env=env, stdout=stream, stderr=subprocess.PIPE, check=True, timeout=180)
            stream.flush()
            os.fsync(stream.fileno())
        if Path(temporary).stat().st_size == 0:
            raise RuntimeError("Database backup was empty")
        # Confirm that pg_restore can read the custom archive's manifest.
        subprocess.run(["pg_restore", "--list", temporary], stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, check=True, timeout=30)
        Path(temporary).replace(destination)
        return destination
    finally:
        env.pop("PGPASSWORD", None)
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-write", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_3URL"):
        raise SystemExit("STOP: Unset remote DATABASE_URL/DATABASE_3URL first")
    import psycopg
    admin = args.verify_write or args.backup
    if not admin and (not WORKER_FILE.is_file() or WORKER_FILE.is_symlink()
                      or WORKER_FILE.stat().st_mode & 0o077):
        raise SystemExit("STOP: Local worker pgpass missing or permissions are not 0600")
    password = getpass.getpass("Local PostgreSQL postgres password (hidden): ") if admin else None
    if admin and not password:
        raise SystemExit("STOP: No local PostgreSQL password entered")
    connection = connect_args(admin, password)
    report = read_health(psycopg.connect, connection)
    report["phone_home_free_bytes"] = shutil.disk_usage(HOME).free
    if args.verify_write:
        report["committed_write_readback"] = verify_persistence(psycopg.connect, connection)
    if args.backup:
        report["backup"] = str(backup_database(password))
    print(json.dumps(report, indent=2, default=str))
    settings = report["durability"]
    if report["read_replica"] or settings["fsync"] != "on" or settings["full_page_writes"] != "on" or settings["synchronous_commit"] == "off":
        print("CHECK FAILED: PostgreSQL is read-only or has reduced durability settings")
        return 1
    print("LOCAL DATABASE CHECK PASSED; news and owner records were not modified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Database errors may contain connection details. Print only the type.
        print("LOCAL DATABASE CHECK FAILED:", type(exc).__name__)
        sys.exit(1)
