"""Check the latest WDI releases and revisions, preserving good data on failure."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.article_visuals import REGISTRY
from app.economic_data import refresh

if __name__ == '__main__':
    changed, results, errors = refresh(REGISTRY)
    for line in results:
        print(line)
    for line in errors:
        print('ERROR ' + line, file=sys.stderr)
    print('Registry updated.' if changed else 'No changes to publish.')
    raise SystemExit(1 if errors else 0)
