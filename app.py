"""Vercel Flask entrypoint.

The application implementation remains in api/index.py. This root entrypoint
lets Vercel's zero-configuration Flask detection bind the existing Flask app.

The repository also contains an `app/` Python package. Because this file is
named `app.py`, Python can otherwise resolve `app` to this module instead
of the package, breaking imports such as `app.article_fetcher`. Exposing the
package directory through `__path__` preserves the existing import layout
without deleting or moving any application files.
"""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent / "app")]

from api.index import app

__all__ = ["app"]
