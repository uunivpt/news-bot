"""Vercel Flask entrypoint.

The application implementation remains in api/index.py; this root entrypoint
lets Vercel's zero-configuration Flask detection bind the existing Flask app.
"""
from api.index import app

__all__ = ["app"]
