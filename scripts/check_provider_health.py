"""Read-only recovery check for the existing production providers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg
from app.database import database_url_from_environment


def check_database() -> bool:
    url = database_url_from_environment()
    if not url:
        print("DATABASE_HEALTH: DATABASE_3URL is missing from GitHub Actions secrets.")
        return False
    try:
        options = {"connect_timeout": 8}
        if "sslmode=" not in url.lower():
            options["sslmode"] = "require"
        with psycopg.connect(url, **options) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                row = connection.execute("SELECT 1 AS connection_ok").fetchone()
        if not row or row[0] != 1:
            print("DATABASE_HEALTH: connection check returned no result.")
            return False
    except psycopg.Error as exc:
        detail = str(exc).lower()
        if "quota" in detail:
            print("DATABASE_HEALTH: provider quota exhausted. Check the existing Neon project's billing and data-transfer allowance.")
        elif "password authentication failed" in detail:
            print("DATABASE_HEALTH: credentials rejected. Verify DATABASE_3URL in Actions and Vercel production.")
        else:
            print("DATABASE_HEALTH: connection unavailable. Check the existing provider's endpoint status.")
        return False
    print("DATABASE_HEALTH: connected; read-only SELECT 1 passed.")
    return True


def main() -> int:
    database_ok = check_database()
    print(f"PROVIDER_HEALTH: database={'ready' if database_ok else 'blocked'}")
    return 0 if database_ok else 1


if __name__ == "__main__":
    sys.exit(main())
