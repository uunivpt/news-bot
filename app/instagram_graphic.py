"""Template-based Instagram news graphic generator.

No AI image model is required. The module selects a layout from a small set of
news templates, downloads an optional source image, and renders a 4:5 PNG.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


WIDTH, HEIGHT = 1080, 1350
OUTPUT_DIR = Path("data/generated_images")

TEMPLATES = (
    "breaking",
    "map_world",
    "person",
    "data",
    "collage",
    "alert",
    "politics",
    "technology",
    "science",
    "general",
)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False):
    candidates = FONT_CANDIDATES if bold else list(reversed(FONT_CANDIDATES))
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _wrap(text: str, font, max_width: int) -> list[str]:
    words = re.split(r"\s+", (text or "").strip())
    lines: list[str] = []
    current = ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        candidate = f"{current} {word}".strip()
        if dummy.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_title(text: str, max_width: int, max_lines: int = 4):
    for size in range(64, 31, -2):
        font = _font(size, True)
        lines = _wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(32, True)
    lines = _wrap(text, font, max_width)[:max_lines]
    return font, lines


def _download_image(url: str | None) -> Image.Image | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        response = requests.get(url, timeout=10, headers={"User-Agent": "NewsDesk/1.0"})
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        return image
    except Exception:
        return None


def _cover(base: Image.Image, image: Image.Image, box: tuple[int, int, int, int]):
    x1, y1, x2, y2 = box
    fitted = ImageOps.fit(image, (x2 - x1, y2 - y1), method=Image.Resampling.LANCZOS)
    base.paste(fitted, (x1, y1))


def choose_template(title: str, category: str = "general", summary: str = "") -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("map", "border", "troops", "missile", "war", "conflict", "iran", "israel", "ukraine", "russia")):
        return "map_world"
    if any(k in text for k in ("president", "prime minister", "minister", "leader", "election", "government", "parliament")) or category == "politics":
        return "politics"
    if any(k in text for k in ("market", "stock", "shares", "gdp", "inflation", "percent", "%", "revenue", "economy")) or category == "business":
        return "data"
    if category == "technology" or any(k in text for k in ("iphone", "android", "ai", "chip", "google", "microsoft", "software")):
        return "technology"
    if category == "science" or any(k in text for k in ("nasa", "space", "research", "scientist", "study")):
        return "science"
    if any(k in text for k in ("breaking", "alert", "warning", "emergency")):
        return "alert"
    return "breaking" if title else "general"


def _draw_text(draw, title: str, summary: str, source: str):
    title_font, lines = _fit_title(title, 930)
    y = 70
    draw.text((75, y), "NEWS DESK", font=_font(28, True), fill=(20, 20, 20))
    y += 65
    for line in lines:
        draw.text((75, y), line, font=title_font, fill=(10, 10, 10))
        y += title_font.size + 8
    if summary:
        body_font = _font(32)
        body_lines = _wrap(summary, body_font, 900)[:5]
        y += 18
        for line in body_lines:
            draw.text((75, y), line, font=body_font, fill=(55, 55, 55))
            y += 42
    draw.text((75, HEIGHT - 65), source[:80], font=_font(22), fill=(100, 100, 100))


def generate_graphic(
    title: str,
    summary: str = "",
    category: str = "general",
    source_name: str = "",
    image_url: str | None = None,
    template: str | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Render one Instagram-ready 4:5 graphic and return its local path."""
    template = template or choose_template(title, category, summary)
    if template not in TEMPLATES:
        template = "general"

    canvas = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(canvas)
    image = _download_image(image_url)

    if template in {"breaking", "general", "alert", "politics", "technology", "science", "data", "map_world"} and image:
        _cover(canvas, image, (45, 45, 1035, 650))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((45, 45, 1035, 650), outline=(25, 25, 25), width=3)
        _draw_text(draw, title, summary, source_name)
    elif template == "collage" and image:
        _cover(canvas, image, (45, 45, 1035, 820))
        draw = ImageDraw.Draw(canvas)
        _draw_text(draw, title, summary, source_name)
    else:
        _draw_text(draw, title, summary, source_name)

    # Small template label helps distinguish the generated card internally.
    draw.text((WIDTH - 260, HEIGHT - 65), template.upper(), font=_font(18, True), fill=(140, 140, 140))

    path = Path(output_path) if output_path else OUTPUT_DIR / f"{abs(hash((title, template))) % 10**12}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=True)
    return path
