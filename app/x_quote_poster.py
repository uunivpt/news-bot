"""Original, source-labelled 4:5 X-post card. Not an X screenshot."""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw
from .editorial_poster import _draw_brand, _font, _sanitize, _wrap, WIDTH, HEIGHT, BLACK, WHITE, GRAY, RED


def _quote(row: dict) -> str:
    summary = _sanitize(row.get("summary") or row.get("bot_summary"))
    match = re.search(r"wrote:\s*[“\"](.+?)[”\"]", summary)
    return (match.group(1) if match else summary)[:230]


def render_x_quote_card(row: dict, output_path: str | Path | None = None):
    if str(row.get("source_type") or "") != "x":
        raise ValueError("X card requires an X-sourced story")
    source = _sanitize(row.get("source_name") or "Original X statement")[:80]
    quote = _quote(row)
    if len(quote) < 16:
        raise ValueError("X card requires a readable source excerpt")
    image = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    d = ImageDraw.Draw(image)
    _draw_brand(d)
    d.rounded_rectangle((55, 189, 1025, 1162), radius=30, fill=(241, 242, 245))
    d.rounded_rectangle((100, 239, 251, 300), radius=7, fill=RED)
    d.text((120, 254), "X POST", font=_font(29), fill=WHITE)
    d.text((101, 329), source, font=_font(32), fill=(24, 26, 30))
    d.line((100, 410, 980, 410), fill=(207, 208, 213), width=3)
    # Fit a quote in a source-shaped card without cropping off any words.
    for size in range(64, 29, -2):
        f = _font(size)
        lines = _wrap(quote, f, 840)
        if len(lines) * (size + 16) <= 515:
            break
    else:
        f = _font(30)
        lines = _wrap(quote, f, 840)[:10]
    top = 456
    for line in lines:
        d.text((106, top), line, font=f, fill=(20, 22, 27))
        top += f.size + 16
    d.line((100, 1085, 980, 1085), fill=(207, 208, 213), width=2)
    d.text((102, 1110), "Attributed statement  •  Read original post for context", font=_font(22, False), fill=(72, 75, 82))
    d.text((60, 1210), "Source: " + source, font=_font(23, False), fill=WHITE)
    d.text((60, 1257), "PoliticsHub.in | Quote image generated from attributed text", font=_font(19, False), fill=GRAY)
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "JPEG", quality=93, optimize=True)
        return path
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=92, optimize=True)
    return stream.getvalue()
