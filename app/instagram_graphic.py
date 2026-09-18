"""Visual news cards for politicshub.in Instagram posts/reels."""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1080, 1350
REEL_WIDTH, REEL_HEIGHT = 1080, 1920
OUTPUT_DIR = Path("data/generated_images")

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

EDITORIAL_PREFIX_RE = re.compile(
    r"^\s*(?:just\s*in|breaking(?:\s+news)?|latest\s+news|latest\s+update|news\s+alert|alert|exclusive)\s*[:\-–—|]+\s*",
    re.I,
)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}", re.I)
SOURCE_FRAGMENT_RE = re.compile(
    r"(?:\bsource\s*:\s*|\bvia\s+|\baccording\s+to\s+|\breported\s+by\s+|\bcredit\s*:\s*)[^|•\n]+",
    re.I,
)

RED = "#c91524"
DARK = "#15191f"
MUTED = "#555b63"
LIGHT = "#f5f6f8"
MAP_DOT = "#dfe2e6"


def _strip_unsupported_symbols(text: str) -> str:
    """Remove emoji/symbol glyphs that DejaVu cannot reliably render.

    The Instagram cards intentionally use typography, not emoji. Unsupported
    emoji otherwise become visible tofu/square boxes in the exported PNG.
    """
    out = []
    for ch in str(text or ""):
        cp = ord(ch)
        category = unicodedata.category(ch)
        # Emoji and symbol glyphs are not part of the editorial card.
        if category == "So" or 0x1F000 <= cp <= 0x1FAFF or cp == 0xFFFD:
            continue
        out.append(ch)
    return "".join(out)


def clean_instagram_text(text: str, source_name: str = "") -> str:
    value = _strip_unsupported_symbols(re.sub(r"\s+", " ", str(text or "")).strip())
    if not value:
        return ""
    source = re.sub(r"\s+", " ", str(source_name or "")).strip()
    if source:
        value = re.sub(re.escape(source), "", value, flags=re.I)
        value = re.sub(re.escape(source.lstrip("@")), "", value, flags=re.I)
    value = SOURCE_FRAGMENT_RE.sub(" ", value)
    value = HANDLE_RE.sub(" ", value)
    value = EDITORIAL_PREFIX_RE.sub("", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value.strip(" -–—|•:")


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
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
    for size in range(72, 31, -2):
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
        response = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "politicshub.in/2.0"},
        )
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        if image.width < 300 or image.height < 200:
            return None
        return image
    except Exception:
        return None


def choose_template(title: str, category: str = "general", summary: str = "") -> str:
    text = f"{title} {summary}".lower()
    if category == "politics" or any(
        k in text for k in ("president", "prime minister", "minister", "election", "government", "parliament")
    ):
        return "politics"
    if category == "world" or any(
        k in text for k in ("war", "conflict", "missile", "border", "iran", "israel", "ukraine", "russia", "gaza")
    ):
        return "world"
    if category == "business" or any(
        k in text for k in ("market", "stock", "shares", "gdp", "inflation", "revenue", "economy")
    ):
        return "business"
    if category == "technology" or any(
        k in text for k in ("iphone", "android", "ai", "chip", "google", "microsoft", "software")
    ):
        return "technology"
    if category == "science" or any(
        k in text for k in ("nasa", "space", "research", "scientist", "study")
    ):
        return "science"
    return "general"


def _draw_world_dots(draw: ImageDraw.ImageDraw) -> None:
    """Subtle deterministic dotted-world background; no external asset required."""
    # Approximate continent masses. Kept deliberately faint so the news photo/text
    # remains the visual focus.
    blobs = [
        (150, 165, 390, 330, 15, 14),   # North America
        (300, 300, 430, 500, 13, 14),   # South America
        (455, 205, 570, 350, 12, 13),   # Europe
        (500, 315, 650, 555, 14, 14),   # Africa
        (590, 190, 830, 365, 13, 13),   # Asia
        (735, 370, 875, 485, 12, 12),   # South/East Asia
        (820, 470, 950, 545, 10, 10),   # Oceania
    ]
    for x1, y1, x2, y2, sx, sy in blobs:
        for y in range(y1, y2, sy):
            for x in range(x1, x2, sx):
                # Elliptical mask gives a soft continent-like silhouette.
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                rx = (x2 - x1) / 2
                ry = (y2 - y1) / 2
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                    r = 3
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=MAP_DOT)


def _draw_logo(draw: ImageDraw.ImageDraw) -> None:
    x, y = 62, 55
    politics = _font(35, True)
    hub = _font(35, True)
    draw.text((x, y), "POLITICS", font=politics, fill=DARK)
    pw = draw.textbbox((x, y), "POLITICS", font=politics)[2]
    draw.text((pw + 7, y), "HUB", font=hub, fill=RED)
    end = draw.textbbox((pw + 7, y), "HUB", font=hub)[2]
    draw.line((end + 22, y + 19, end + 210, y + 19), fill="#20242a", width=3)
    draw.text((x + 2, y + 48), "N E W S    |    A N A L Y S I S    |    F A C T S", font=_font(13, True), fill=DARK)


def _draw_tagline(draw: ImageDraw.ImageDraw) -> None:
    x = 760
    draw.text((x, 54), "STAY INFORMED", font=_font(22, True), fill=DARK)
    draw.text((x, 84), "STAY AHEAD", font=_font(22, True), fill=DARK)
    draw.rectangle((x, 124, x + 68, 130), fill=RED)


def _highlight_title(draw: ImageDraw.ImageDraw, title: str, font, x: int, y: int, max_width: int) -> int:
    """Render a clean headline with one deterministic red emphasis word."""
    words = title.split()
    highlight = None
    priority = (
        "America's", "America", "India", "India's", "Russia", "Ukraine",
        "Israel", "Iran", "China", "Trump", "Modi", "White", "House",
        "Europe", "NATO", "UN", "UK", "US"
    )
    for p in priority:
        for i, word in enumerate(words):
            if word.strip(".,:;!?()") == p:
                highlight = i
                break
        if highlight is not None:
            break
    if highlight is None and len(words) >= 3:
        highlight = 1

    lines = _wrap(title, font, max_width)
    line_no = 0
    cursor_y = y
    remaining = words[:]
    for line in lines:
        line_words = line.split()
        cursor_x = x
        for word in line_words:
            clean = word.strip(".,:;!?()")
            bbox = draw.textbbox((0, 0), word, font=font)
            fill = RED if highlight is not None and clean == words[highlight].strip(".,:;!?()") else DARK
            draw.text((cursor_x, cursor_y), word, font=font, fill=fill)
            cursor_x += bbox[2] + max(9, font.size // 7)
        cursor_y += font.size + 9
        line_no += 1
    return cursor_y


def generate_graphic(
    title: str,
    summary: str = "",
    category: str = "general",
    source_name: str = "",
    image_url: str | None = None,
    template: str | None = None,
    output_path: str | Path | None = None,
) -> Path:
    template = template or choose_template(title, category, summary)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), "white")
    image = _download_image(image_url)
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, WIDTH, 12), fill=RED)
    _draw_logo(d)
    _draw_tagline(d)
    if image:
        fitted = ImageOps.fit(image, (980, 590), method=Image.Resampling.LANCZOS)
        canvas.paste(fitted, (50, 180))
    else:
        d.rectangle((50, 180, 1030, 770), fill="#eceff2")
    d.rounded_rectangle((50, 180, 1030, 770), radius=28, outline="white", width=5)
    d.rounded_rectangle((55, 795, 300, 855), radius=15, fill=RED)
    d.text((78, 810), template.upper(), font=_font(25, True), fill="white")
    font, lines = _fit_title(clean_instagram_text(title, source_name), 930, 4)
    y = 880
    for line in lines:
        d.text((55, y), line, font=font, fill=DARK)
        y += font.size + 8
    if summary:
        body = _font(25)
        for line in _wrap(clean_instagram_text(summary, source_name), body, 930)[:5]:
            d.text((55, y + 12), line, font=body, fill=MUTED)
            y += 37
    if source_name:
        d.text((55, HEIGHT - 45), f"Source: {clean_instagram_text(source_name)}", font=_font(19, True), fill=DARK)
    path = Path(output_path) if output_path else OUTPUT_DIR / f"{abs(hash((title, template))) % 10**12}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(path, format="JPEG", quality=94, optimize=True)
    return path


def generate_reel_cards(
    title: str,
    summary: str,
    category: str,
    image_url: str | None,
    output_dir: str | Path,
    source_name: str = "",
) -> list[Path]:
    """PoliticsHub's new clean editorial 9:16 Instagram template.

    Matches the supplied reference: white newsroom page, PoliticsHub masthead,
    right-side tagline, faint world map, framed photo, red category badge,
    bold black/red headline, compact summary and source attribution.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    clean_title = clean_instagram_text(title, source_name) or "Latest news update"
    clean_summary = clean_instagram_text(summary, source_name)
    clean_source = clean_instagram_text(source_name) or "PoliticsHub"
    image = _download_image(image_url)

    canvas = Image.new("RGBA", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(canvas)

    # Editorial side accents and top masthead.
    d.polygon([(0, 0), (70, 0), (0, 220)], fill=RED)
    d.polygon([(REEL_WIDTH, 0), (REEL_WIDTH - 28, 0), (REEL_WIDTH, 270)], fill="#e5e7eb")
    d.polygon([(REEL_WIDTH, 1450), (REEL_WIDTH, 1920), (930, 1920)], fill="#f0f1f3")
    d.polygon([(0, 1620), (0, 1920), (65, 1920)], fill="#f0f1f3")

    _draw_logo(d)
    _draw_tagline(d)

    # Faint world map sits behind the hero card.
    _draw_world_dots(d)

    # Hero image with the same large rounded editorial frame.
    frame = (42, 365, 1038, 850)
    d.rounded_rectangle(frame, radius=28, fill="#eef0f3", outline="#ffffff", width=5)
    if image:
        fitted = ImageOps.fit(image, (1000, 455), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (1000, 455), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, 999, 454), radius=23, fill=255)
        canvas.paste(fitted, (40, 375), mask)
    else:
        d.rounded_rectangle((55, 378, 1025, 837), radius=22, fill="#e7e9ec")
        d.text((330, 570), "POLITICSHUB", font=_font(50, True), fill="#9aa0a8")

    # Category badge.
    category_label = (category or "news").upper()[:15]
    badge_w = max(190, d.textbbox((0, 0), category_label, font=_font(25, True))[2] + 56)
    d.rounded_rectangle((58, 885, 58 + badge_w, 950), radius=15, fill=RED)
    d.text((84, 903), category_label, font=_font(25, True), fill="white")

    # Main headline.
    title_font, _ = _fit_title(clean_title, 930, 4)
    headline_y = 980
    headline_end = _highlight_title(
        d,
        clean_title,
        title_font,
        58,
        headline_y,
        930,
    )

    # Compact summary below headline.
    if clean_summary:
        summary_font = _font(25)
        summary_y = min(headline_end + 18, 1450)
        summary_lines = _wrap(clean_summary, summary_font, 930)[:6]
        for line in summary_lines:
            d.text((60, summary_y), line, font=summary_font, fill="#454b53")
            summary_y += 38
        if len(_wrap(clean_summary, summary_font, 930)) > 6:
            d.text((60, summary_y - 4), "...", font=_font(28, True), fill=MUTED)

    # Editorial footer.
    d.rectangle((60, 1660, 125, 1666), fill=RED)
    d.text(
        (60, 1710),
        f"Source: {clean_source}",
        font=_font(24, True),
        fill=DARK,
    )
    d.text((60, 1760), "politicshub.in", font=_font(24, True), fill=DARK)

    # Keep the exact 1080x1920 PNG used by the existing Reel pipeline.
    path = out / "01_editorial.png"
    canvas.convert("RGB").save(path, format="PNG", optimize=True)
    return [path]
