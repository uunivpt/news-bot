"""Template-based graphics for politicshub.in news posts and reels."""
from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1080, 1350
REEL_WIDTH, REEL_HEIGHT = 1080, 1920
OUTPUT_DIR = Path("data/generated_images")
TEMPLATES = ("breaking", "map_world", "person", "data", "collage", "alert", "politics", "technology", "science", "general")
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False):
    for path in FONT_CANDIDATES:
        if bold != path.endswith("Bold.ttf"):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.truetype(FONT_CANDIDATES[-1], size)
    except OSError:
        return ImageFont.load_default()


def _wrap(text: str, font, max_width: int) -> list[str]:
    words = re.split(r"\s+", (text or "").strip())
    lines, current = [], ""
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
    for size in range(68, 31, -2):
        font = _font(size, True)
        lines = _wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(32, True)
    return font, _wrap(text, font, max_width)[:max_lines]


def _download_image(url: str | None) -> Image.Image | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        r = requests.get(url, timeout=10, headers={"User-Agent": "politicshub.in/1.0"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _cover(base: Image.Image, image: Image.Image, box):
    x1, y1, x2, y2 = box
    fitted = ImageOps.fit(image, (x2 - x1, y2 - y1), method=Image.Resampling.LANCZOS)
    base.paste(fitted, (x1, y1))


def choose_template(title: str, category: str = "general", summary: str = "") -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("map", "border", "troops", "missile", "war", "conflict", "iran", "israel", "ukraine", "russia")):
        return "map_world"
    if category == "politics" or any(k in text for k in ("president", "prime minister", "minister", "leader", "election", "government", "parliament")):
        return "politics"
    if category == "business" or any(k in text for k in ("market", "stock", "shares", "gdp", "inflation", "percent", "%", "revenue", "economy")):
        return "data"
    if category == "technology" or any(k in text for k in ("iphone", "android", "ai", "chip", "google", "microsoft", "software")):
        return "technology"
    if category == "science" or any(k in text for k in ("nasa", "space", "research", "scientist", "study")):
        return "science"
    if any(k in text for k in ("breaking", "alert", "warning", "emergency")):
        return "alert"
    return "breaking" if title else "general"


def generate_graphic(title: str, summary: str = "", category: str = "general", source_name: str = "", image_url: str | None = None, template: str | None = None, output_path: str | Path | None = None) -> Path:
    template = template or choose_template(title, category, summary)
    if template not in TEMPLATES:
        template = "general"
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(canvas)
    image = _download_image(image_url)
    if image:
        _cover(canvas, image, (45, 45, 1035, 650))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((45, 45, 1035, 650), outline=(25, 25, 25), width=3)
    draw.text((75, 700), "politicshub.in", font=_font(28, True), fill=(20, 20, 20))
    title_font, lines = _fit_title(title, 930)
    y = 765
    for line in lines:
        draw.text((75, y), line, font=title_font, fill=(10, 10, 10))
        y += title_font.size + 8
    if summary:
        body_font = _font(31)
        y += 15
        for line in _wrap(summary, body_font, 900)[:5]:
            draw.text((75, y), line, font=body_font, fill=(55, 55, 55))
            y += 41
    if source_name:
        draw.text((75, HEIGHT - 65), source_name[:80], font=_font(20), fill=(100, 100, 100))
    path = Path(output_path) if output_path else OUTPUT_DIR / f"{abs(hash((title, template))) % 10**12}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=True)
    return path


def generate_reel_cards(title: str, summary: str, category: str, image_url: str | None, output_dir: str | Path) -> list[Path]:
    """Create three information-dense 9:16 cards; no source name/link is rendered."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    image = _download_image(image_url)
    facts = _wrap(summary or "Latest update from politicshub.in.", _font(38), 900)[:10]
    title_font, title_lines = _fit_title(title, 900, 5)
    cards: list[Path] = []

    # Card 1: headline + visual
    c = Image.new("RGB", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(c)
    if image:
        _cover(c, image, (40, 40, 1040, 950))
    d.text((55, 1000), "politicshub.in", font=_font(34, True), fill=(20, 20, 20))
    y = 1080
    for line in title_lines:
        d.text((55, y), line, font=title_font, fill=(8, 8, 8))
        y += title_font.size + 8
    p = out / "01_headline.png"; c.save(p, format="PNG", optimize=True); cards.append(p)

    # Card 2: key information
    c = Image.new("RGB", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(c)
    d.text((55, 90), "KEY UPDATE", font=_font(34, True), fill=(20, 20, 20))
    y = 190
    for line in facts:
        d.ellipse((60, y + 12, 78, y + 30), fill=(20, 20, 20))
        wrapped = _wrap(line, _font(38), 850)
        for part in wrapped:
            d.text((105, y), part, font=_font(38), fill=(35, 35, 35)); y += 52
        y += 26
        if y > 1700: break
    d.text((55, 1810), "politicshub.in", font=_font(30, True), fill=(20, 20, 20))
    p = out / "02_key_update.png"; c.save(p, format="PNG", optimize=True); cards.append(p)

    # Card 3: clean closing/brand card
    c = Image.new("RGB", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(c)
    d.text((55, 720), "STAY UPDATED", font=_font(62, True), fill=(10, 10, 10))
    d.text((55, 830), "politicshub.in", font=_font(70, True), fill=(20, 20, 20))
    d.text((55, 950), "News • Politics • World • Business • Technology", font=_font(28), fill=(70, 70, 70))
    p = out / "03_brand.png"; c.save(p, format="PNG", optimize=True); cards.append(p)
    return cards
