"""Build or check the homepage CSS bundle without render-blocking font imports.

Run after editing site.css, editorial.css or polish.css:
    python scripts/build_home_css.py
CI uses --check and never rewrites the committed bundle.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ASSETS = Path(__file__).resolve().parents[1] / 'public' / 'assets'
SOURCES = ('site.css', 'editorial.css', 'polish.css')
OUTPUT = 'home-critical.css'
HEADER = '/* Homepage critical styles — generated from site.css, editorial.css and polish.css in cascade order. Keep source files intact for other routes. */\n'


def render_bundle(assets: Path) -> str:
    parts = []
    for name in SOURCES:
        text = (assets / name).read_text(encoding='utf-8')
        lines = text.splitlines(keepends=True)
        # Keep the existing homepage behavior: its font stylesheet loads
        # separately, so the source's one-line Google Fonts import stays out.
        if name == 'site.css' and lines and lines[0].startswith("@import url('https://fonts.googleapis.com/") and lines[0].rstrip().endswith("');"):
            text = ''.join(lines[1:])
        if re.search(r'^\s*@import\b', text, flags=re.MULTILINE):
            raise ValueError(f'{name}: unsupported @import; review homepage loading before bundling')
        parts.append(text)
    return HEADER + parts[0] + ''.join('\n/* ' + name + ' */\n' + text for name, text in zip(SOURCES[1:], parts[1:]))


def build_bundle(assets: Path, *, check: bool = False) -> bool:
    expected = render_bundle(assets).encode('utf-8')
    output = assets / OUTPUT
    current = output.read_bytes() if output.exists() else None
    if check:
        return current == expected
    if current != expected:
        output.write_bytes(expected)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail on drift without changing files')
    args = parser.parse_args(argv)
    try:
        matches = build_bundle(ASSETS, check=args.check)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if not matches:
        print('home-critical.css is out of date; run python scripts/build_home_css.py', file=sys.stderr)
        return 1
    print('Homepage CSS bundle matches sources.' if args.check else 'Homepage CSS bundle is up to date.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
