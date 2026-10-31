import argparse
import logging
import time

from app.collector import collect_once, load_sources
from app.database import NewsDatabase, DatabaseUnavailable
from app.phase_system import ensure_schema, run as agent_run


def main() -> int | None:
    parser = argparse.ArgumentParser(description="Phase 1 news collector")
    parser.add_argument("--once", action="store_true", help="collect once and exit")
    parser.add_argument("--interval", type=int, default=300, help="polling interval in seconds")
    parser.add_argument("--config", default="config/sources.json")
    parser.add_argument("--db", default="data/news.db")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    config = load_sources(args.config)
    try:
        db = NewsDatabase(args.db)
    except DatabaseUnavailable as exc:
        # A provider quota block is an operational outage, not a broken news source.
        # Exit 78 enables GitHub Actions to publish the attributed RSS snapshot.
        if "quota exhausted" in str(exc).lower():
            logging.error("%s", exc)
            return 78
        raise
    ensure_schema(db)

    try:
        while True:
            with agent_run(db, "manager", "orchestrate_collection"):
                added, skipped = collect_once(config, db)
            logging.info("Cycle complete: added=%d skipped=%d total=%d", added, skipped, db.count())
            if args.once:
                break
            time.sleep(max(10, args.interval))
    except KeyboardInterrupt:
        logging.info("Collector stopped")
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
