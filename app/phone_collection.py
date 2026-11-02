"""Collect the reviewed source configuration into private pending phone news.

The worker is started by the local admin daemon, independently of page reads.
It uses a separate loopback PostgreSQL connection and never approves or
publishes collected news. Existing unique URLs prevent duplicate inserts.
"""
import logging
import os
import threading
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 20 * 60
_lock = threading.Lock()
_worker = None
_stop = None


def run_cycle(dsn):
    from app.collector import collect_once, load_sources
    from app.database import NewsDatabase

    database = NewsDatabase(database_url=dsn, connect_attempts=1,
                            connect_timeout=6, statement_timeout=15000)
    try:
        return collect_once(load_sources(), database)
    finally:
        database.close()


def _loop(dsn, stop):
    while not stop.is_set():
        try:
            added, duplicate = run_cycle(dsn)
            logger.info("Phone source cycle: %d pending records added, %d duplicates", added, duplicate)
        except Exception as error:
            # Never log connection strings, API keys or publisher request URLs.
            logger.warning("Phone source cycle failed: %s", type(error).__name__)
        stop.wait(INTERVAL_SECONDS)


def start_collection_worker():
    """Start one background collector only on the phone's private PostgreSQL."""
    global _worker, _stop
    if os.getenv("POLITICSHUB_LOCAL_ADMIN") != "1" or os.getenv("VERCEL"):
        return False
    dsn = os.getenv("DATABASE_3URL") or os.getenv("DATABASE_URL") or ""
    try:
        parts = urlsplit(dsn)
        if (parts.scheme not in {"postgres", "postgresql"}
                or parts.hostname not in {"127.0.0.1", "localhost"}
                or parts.port not in {None, 5432}
                or parts.path != "/politicshub"):
            return False
    except ValueError:
        return False
    with _lock:
        if _worker is not None and _worker.is_alive():
            return False
        _stop = threading.Event()
        _worker = threading.Thread(target=_loop, args=(dsn, _stop),
                                   name="phone-source-collector", daemon=True)
        _worker.start()
        return True
