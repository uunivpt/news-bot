"""Safe inline Markdown formatting for human-readable news text.

Never interpret raw HTML from a story as markup. Render just **bold** spans,
after HTML escaping, so user-supplied text cannot inject elements or links.
"""
from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*((?!\s)[^\n*]*?\S)\*\*")


def render_inline_markdown(value: object) -> str:
    """Escape all text, then allow matched **nonempty text** as <strong>."""
    escaped = html.escape(str(value or ""))
    return _BOLD.sub(lambda match: "<strong>" + match.group(1) + "</strong>", escaped)
