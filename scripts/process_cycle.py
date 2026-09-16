import logging

from app.database import NewsDatabase
from app.factcheck import run_cross_source_check

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def main() -> None:
    db = NewsDatabase()
    try:
        checked = run_cross_source_check(db)
        logging.info("Fact-check precheck complete: checked=%d", checked)
    finally:
        db.close()


if __name__ == "__main__":
    main()
