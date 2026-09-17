"""Visual news cards for politicshub.in Instagram Reels."""
from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

WIDTH, HEIGHT = 1080, 1350
REEL_WIDTH, REEL_HEIGHT = 1080, 1920
OUTPUT_DIR = Path("data/generated_images")
TEMPLATES = ("breaking", "politics", "world", "business", "technology", "science", "general")
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
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
    for size in range(76, 31, -2):
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
        r = requests.get(url, timeout=12, headers={"User-Agent": "politicshub.in/2.0"})
        r.raise_for_status()
        image = Image.open(io.BytesIO(r.content)).convert("RGB")
        if image.width < 300 or image.height < 200:
            return None
        return image
    except Exception:
        return None


def _cover(base: Image.Image, image: Image.Image, box):
    x1, y1, x2, y2 = box
    fitted = ImageOps.fit(image, (x2 - x1, y2 - y1), method=Image.Resampling.LANCZOS)
    base.paste(fitted, (x1, y1))


def _photo_background(image: Image.Image | None) -> Image.Image:
    """Always return a visual background; never a blank white Reel scene."""
    if image is None:
        bg = Image.new("RGB", (REEL_WIDTH, REEL_HEIGHT), (24, 28, 36))
        d = ImageDraw.Draw(bg)
        for x in range(-REEL_HEIGHT, REEL_WIDTH, 120):
            d.line((x, 0, x + REEL_HEIGHT, REEL_HEIGHT), fill=(42, 48, 58), width=3)
        return bg
    return ImageOps.fit(image, (REEL_WIDTH, REEL_HEIGHT), method=Image.Resampling.LANCZOS)


def _gradient_overlay(base: Image.Image, top: int = 0, bottom: int = REEL_HEIGHT, strength: int = 205):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    height = max(1, bottom - top)
    for y in range(max(0, top), min(REEL_HEIGHT, bottom)):
        alpha = int(strength * ((y - top) / height))
        od.line((0, y, REEL_WIDTH, y), fill=(0, 0, 0, alpha))
    base.alpha_composite(overlay)


def _photo_card(image: Image.Image | None) -> Image.Image:
    c = _photo_background(image).convert("RGBA")
    c.alpha_composite(Image.new("RGBA", c.size, (0, 0, 0, 42)))
    return c


def choose_template(title: str, category: str = "general", summary: str = "") -> str:
    text = f"{title} {summary}".lower()
    if category == "politics" or any(k in text for k in ("president", "prime minister", "minister", "election", "government", "parliament")):
        return "politics"
    if category == "world" or any(k in text for k in ("war", "conflict", "missile", "border", "iran", "israel", "ukraine", "russia", "gaza")):
        return "world"
    if category == "business" or any(k in text for k in ("market", "stock", "shares", "gdp", "inflation", "revenue", "economy")):
        return "business"
    if category == "technology" or any(k in text for k in ("iphone", "android", "ai", "chip", "google", "microsoft", "software")):
        return "technology"
    if category == "science" or any(k in text for k in ("nasa", "space", "research", "scientist", "study")):
        return "science"
    if any(k in text for k in ("breaking", "alert", "warning", "emergency")):
        return "breaking"
    return "general"


def generate_graphic(title: str, summary: str = "", category: str = "general", source_name: str = "", image_url: str | None = None, template: str | None = None, output_path: str | Path | None = None) -> Path:
    template = template or choose_template(title, category, summary)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (18, 20, 24, 255))
    image = _download_image(image_url)
    if image:
        _cover(canvas, image, (0, 0, WIDTH, 720))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((45, 45, 360, 112), radius=12, fill=(185, 30, 30))
    d.text((68, 61), template.upper(), font=_font(26, True), fill="white")
    d.text((55, 755), "politicshub.in", font=_font(30, True), fill="white")
    title_font, lines = _fit_title(title, 950, 4)
    y = 815
    for line in lines:
        d.text((55, y), line, font=title_font, fill="white"); y += title_font.size + 8
    if summary:
        body = _font(28)
        y += 14
        for line in _wrap(summary, body, 920)[:4]:
            d.text((55, y), line, font=body, fill=(225, 225, 225)); y += 39
    if source_name:
        d.text((55, HEIGHT - 55), source_name[:70], font=_font(20), fill=(180, 180, 180))
    path = Path(output_path) if output_path else OUTPUT_DIR / f"{abs(hash((title, template))) % 10**12}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(path, format="JPEG", quality=94, optimize=True)
    return path


def _clean_facts(summary: str, title: str) -> list[str]:
    raw = re.sub(r"\s+", " ", summary or "").strip()
    title_clean = re.sub(r"\s+", " ", title or "").strip()
    if raw.lower().startswith(title_clean.lower()):
        raw = raw[len(title_clean):].lstrip(" :–—-|\n")
    parts = [p.strip(" •-\t") for p in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9])", raw) if p.strip()]
    return parts[:4] if parts else ["Latest update is being tracked by politicshub.in."]


def _draw_safe_text(d, text: str, font, x: int, y: int, max_width: int, max_lines: int = 4):
    lines = _wrap(text, font, max_width)[:max_lines]
    for line in lines:
        d.text((x, y), line, font=font, fill="white", stroke_width=1, stroke_fill=(0, 0, 0)); y += font.size + 9
    return y


def generate_reel_cards(title: str, summary: str, category: str, image_url: str | None, output_dir: str | Path) -> list[Path]:
    """Create three dynamic photo-led, information-first 9:16 scenes."""
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    image = _download_image(image_url)
    template = choose_template(title, category, summary)
    facts = _clean_facts(summary, title)
    cards: list[Path] = []

    # 1) Hero: full news photo, safe headline area and category badge.
    c = _photo_card(image); d = ImageDraw.Draw(c)
    _gradient_overlay(c, 650, REEL_HEIGHT, 235); d = ImageDraw.Draw(c)
    d.rounded_rectangle((55, 70, 330, 140), radius=16, fill=(185, 30, 30, 235))
    d.text((80, 87), ("BREAKING" if template == "breaking" else category.upper())[:15], font=_font(27, True), fill="white")
    f, lines = _fit_title(title, 930, 4)
    y = 1170
    for line in lines:
        d.text((55, y), line, font=f, fill="white", stroke_width=2, stroke_fill=(0, 0, 0)); y += f.size + 10
    d.text((55, 1800), "politicshub.in", font=_font(32, True), fill="white")
    p = out / "01_hero.png"; c.convert("RGB").save(p, format="PNG", optimize=True); cards.append(p)

    # 2) Facts: photo remains visible, with a dark editorial information panel.
    c = _photo_card(image).filter(ImageFilter.GaussianBlur(radius=1.2)).convert("RGBA")
    shade = Image.new("RGBA", c.size, (0, 0, 0, 115)); c.alpha_composite(shade)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle((45, 70, 445, 145), radius=16, fill=(15, 15, 18, 225))
    d.text((72, 88), "WHAT WE KNOW", font=_font(28, True), fill="white")
    y = 230; body = _font(38)
    for fact in facts:
        wrapped = _wrap(fact, body, 835)[:3]
        d.ellipse((60, y + 14, 80, y + 34), fill=(230, 50, 50))
        for part in wrapped:
            d.text((108, y), part, font=body, fill="white", stroke_width=1, stroke_fill=(0, 0, 0)); y += 52
        y += 28
        if y > 1640: break
    d.text((55, 1810), "politicshub.in", font=_font(30, True), fill="white")
    p = out / "02_facts.png"; c.convert("RGB").save(p, format="PNG", optimize=True); cards.append(p)

    # 3) Context: photo-led closing with one useful context line, not a blank brand card.
    c = _photo_card(image); d = ImageDraw.Draw(c)
    _gradient_overlay(c, 700, REEL_HEIGHT, 225); d = ImageDraw.Draw(c)
    d.rounded_rectangle((55, 1120, 395, 1190), radius=14, fill=(185, 30, 30, 225))
    d.text((78, 1138), "LATEST UPDATE", font=_font(27, True), fill="white")
    cf = _font(43, True)
    _draw_safe_text(d, facts[0], cf, 55, 1250, 910, 4)
    d.text((55, 1795), "politicshub.in  •  News & Updates", font=_font(29, True), fill="white")
    p = out / "03_context.png"; c.convert("RGB").save(p, format="PNG", optimize=True); cards.append(p)
    return cards
