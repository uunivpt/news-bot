"""Refresh the private phone editorial review queue; never publish news."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.termux_one_step import REPORT, inspect_local_database


def main():
    report = inspect_local_database()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT.with_suffix(".tmp")
    tmp.write_text(report, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(REPORT)
    REPORT.chmod(0o600)
    print("PRIVATE REVIEW QUEUE UPDATED:", REPORT)
    print("NO APPROVALS OR PUBLICATIONS MADE")


if __name__ == "__main__":
    main()
