"""Visual news cards for politicshub.in Instagram posts/reels."""
from __future__ import annotations

import io
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1080, 1350
REEL_WIDTH, REEL_HEIGHT = 1080, 1920
OUTPUT_DIR = Path("data/generated_images")

# The old /usr/share path exists on standard Linux runners, but not on
# Termux. If the font cannot be found, Pillow's tiny bitmap fallback makes
# the Reel text look microscopic. Search both Linux and Termux locations.
FONT_BOLD_CANDIDATES = (
    os.getenv("POLITICSHUB_FONT_BOLD", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/system/fonts/Roboto-Bold.ttf",
    "/system/product/fonts/Roboto-Bold.ttf",
    # Some Android builds expose only the regular Roboto TTF. It is still
    # a valid TrueType font and is preferable to failing the whole Reel.
    "/system/fonts/Roboto-Regular.ttf",
    "/system/product/fonts/Roboto-Regular.ttf",
)
FONT_REG_CANDIDATES = (
    os.getenv("POLITICSHUB_FONT_REG", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/system/fonts/Roboto-Regular.ttf",
    "/system/product/fonts/Roboto-Regular.ttf",
)

EDITORIAL_PREFIX_RE = re.compile(
    r"^\s*(?:just\s*in|breaking(?:\s+news)?|latest\s+news|latest\s+update|news\s+alert|alert|exclusive)\s*[:\-–—|]+\s*",
    re.I,
)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}", re.I)
# Remove promotional/navigation fragments from generated editorial text.
PROMO_NAV_RE = re.compile(r"\b(?:socials|donate|advertising)\b(?:\s*[|•·/,-]\s*\b(?:socials|donate|advertising)\b)*", re.I)

SOURCE_FRAGMENT_RE = re.compile(
    r"(?:\bsource\s*:\s*|\bvia\s+|\baccording\s+to\s+|\breported\s+by\s+|\bcredit\s*:\s*)[^|•\n]+",
    re.I,
)

RED = "#c91524"
DARK = "#15191f"
MUTED = "#555b63"
LIGHT = "#f5f6f8"
MAP_DOT = "#dfe2e6"
# 64 deterministic composition profiles = 8 base geometries x 8 visual treatments.
PROFILE_FONT_SCALE = tuple(round(0.90 + ((i * 7) % 17) / 100, 2) for i in range(64))
_PROFILE_CROPS = ((.5,.5),(.5,.35),(.65,.5),(.35,.5),(.7,.5),(.5,.7),(.35,.65),(.65,.35))
PROFILE_CROP = tuple(_PROFILE_CROPS[i % len(_PROFILE_CROPS)] for i in range(64))


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
    # Instagram-safe text sanitizer:
    # strip stray glyphs/punctuation that feeds sometimes prepend (for example
    # dotted-circle markers, bullets, slash separators, or invisible marks).
    # Keep normal punctuation inside the actual headline intact.
    value = re.sub(r"^[^\w\s]+", "", value, flags=re.UNICODE)
    value = re.sub(r"^[\s•·▪◦○●◉◌◍\-/|:]+", "", value)
    value = re.sub(
        r"^(?:(?:just\s*in|breaking(?:\s+news)?|latest\s+news|latest\s+update|news\s+alert|alert|exclusive)\s*[:\-–—|/]+\s*)+",
        "",
        value,
        flags=re.I,
    )
    source = re.sub(r"\s+", " ", str(source_name or "")).strip()
    if source:
        value = re.sub(re.escape(source), "", value, flags=re.I)
        value = re.sub(re.escape(source.lstrip("@")), "", value, flags=re.I)
    value = SOURCE_FRAGMENT_RE.sub(" ", value)
    value = PROMO_NAV_RE.sub(" ", value)
    value = HANDLE_RE.sub(" ", value)
    value = EDITORIAL_PREFIX_RE.sub("", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value.strip(" -–—|•:")


def _font(size: int, bold: bool = False):
    candidates = FONT_BOLD_CANDIDATES if bold else FONT_REG_CANDIDATES
    for path in candidates:
        if path:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, TypeError):
                pass

    # Pillow wheels may ship their own DejaVu TTFs. Prefer these because
    # they work inside the Termux Python sandbox without Android filesystem
    # permissions or extra fontconfig packages.
    try:
        pil_fonts = Path(ImageFont.__file__).resolve().parent / "fonts"
        bundled = pil_fonts / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
        return ImageFont.truetype(str(bundled), size)
    except (OSError, TypeError):
        pass

    # Termux package layouts can differ, and some Android/Termux filesystem
    # operations report "Function not implemented" for direct path checks.
    # fontconfig is only an optional final resolver; it is NOT required.
    try:
        import subprocess
        pattern = "DejaVu Sans:style=Bold" if bold else "DejaVu Sans:style=Book"
        resolved = subprocess.check_output(
            ["fc-match", "-f", "%{file}", pattern],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        if resolved:
            return ImageFont.truetype(resolved, size)
    except Exception:
        pass

    raise RuntimeError(
        "No TrueType font available. Pillow DejaVu fonts and Termux fonts were not found."
    )


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


def _fit_title(text: str, max_width: int, max_lines: int = 3, scale: float = 1.0):
    # Keep Reel headlines visibly large on a 1080x1920 canvas. The previous
    # 48px fallback made long headlines look tiny once Instagram displayed the
    # full Reel in the feed.
    high=max(72,int(132*scale)); low=max(60,int(72*scale))
    for size in range(high, low-1, -2):
        font = _font(size, True)
        lines = _wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(max(60,int(72*scale)), True)
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
    politics_w = draw.textbbox((0, 0), "POLITICS", font=politics)[2]
    hub_x = x + politics_w + 10
    draw.text((hub_x, y), "HUB", font=hub, fill=RED)
    hub_w = draw.textbbox((0, 0), "HUB", font=hub)[2]
    line_x = min(hub_x + hub_w + 22, 820)
    draw.line((line_x, y + 19, min(line_x + 150, 1030), y + 19), fill="#20242a", width=3)
    draw.text((x + 2, y + 48), "N E W S    |    A N A L Y S I S    |    F A C T S", font=_font(13, True), fill=DARK)


def _draw_tagline(draw: ImageDraw.ImageDraw) -> None:
    x = 700
    font = _font(19, True)
    draw.text((x, 54), "STAY INFORMED", font=font, fill=DARK)
    draw.text((x, 82), "STAY AHEAD", font=font, fill=DARK)
    draw.rectangle((x, 112, x + 62, 118), fill=RED)


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



def _template_variant(item_key: str | int | None, category: str = "general", template_variant: int | None = None) -> int:
    """Select one of 64 deterministic layouts; DB-backed reservation can override it."""
    try:
        value = int(item_key or 0)
    except (TypeError, ValueError):
        value = abs(hash(str(item_key or "")))
    return (value + sum(ord(ch) for ch in str(category or ""))) % 64


def _draw_footer(d, variant: int) -> None:
    """Keep all branding in an Instagram-safe lower band."""
    if variant % 2 == 0:
        d.rectangle((58, 1740, 1022, 1746), fill=RED)
        d.text((58, 1772), "POLITICSHUB  |  NEWS • ANALYSIS • FACTS", font=_font(18, True), fill=DARK)
    else:
        d.rectangle((58, 1760, 330, 1766), fill=RED)
        d.text((58, 1790), "REAL NEWS. REAL PERSPECTIVE.", font=_font(17, True), fill=DARK)


def _draw_hero(d, canvas, image, box, radius=28):
    if not image:
        return False
    x1, y1, x2, y2 = box
    fitted = ImageOps.fit(image, (x2-x1, y2-y1), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", fitted.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, fitted.width-1, fitted.height-1), radius=radius, fill=255)
    canvas.paste(fitted, (x1, y1), mask)
    d.rounded_rectangle(box, radius=radius, outline="#ffffff", width=5)
    return True


def _draw_headline_block(d, title, summary, source, category, top, variant, font_scale=1.0):
    title = clean_instagram_text(title, source) or "Latest news update"
    summary = clean_instagram_text(summary, source)
    title_font, lines = _fit_title(title, 920, 4, font_scale)
    y = top
    accent_index = (variant + 1) % max(1, len(title.split()))
    words = title.split()
    accent = words[accent_index].strip(".,:;!?()") if words else ""
    for line in lines[:4]:
        x = 58
        for word in line.split():
            clean = word.strip(".,:;!?()")
            bbox = d.textbbox((0, 0), word, font=title_font, stroke_width=1)
            fill = RED if clean == accent else DARK
            d.text((x, y), word, font=title_font, fill=fill, stroke_width=1, stroke_fill=fill)
            x += bbox[2] + max(8, title_font.size // 8)
        y += title_font.size + 8
    if summary:
        summary_font = _font(27)
        for line in _wrap(summary, summary_font, 900)[:3]:
            d.text((60, y + 16), line, font=summary_font, fill=MUTED)
            y += 39
    badge = (category or "news").upper()[:16]
    bf = _font(22, True)
    bw = max(170, d.textbbox((0, 0), badge, font=bf)[2] + 42)
    badge_y = max(150, top - 74)
    d.rounded_rectangle((58, badge_y, 58+bw, badge_y+52), radius=13, fill=RED)
    d.text((79, badge_y+14), badge, font=bf, fill="white")
    if source:
        d.text((60, 1625), f"Source: {clean_instagram_text(source)}", font=_font(19, True), fill=DARK)


def generate_reel_cards(
    title: str,
    summary: str,
    category: str,
    image_url: str | None,
    output_dir: str | Path,
    source_name: str = "",
    item_key: str | int | None = None,
    template_variant: int | None = None,
) -> list[Path]:
    """Create a single clean, Instagram-safe 1080x1920 editorial card.

    Critical content stays inside the central safe zone (roughly y=250..1630).
    The photo, headline, summary and source have independent areas, so text
    never sits on top of the photo. Stories without a usable image do not get
    an empty/black image panel.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    clean_title = clean_instagram_text(title, source_name) or "Latest news update"
    clean_summary = clean_instagram_text(summary, source_name)
    clean_source = clean_instagram_text(source_name)
    image = _download_image(image_url)

    profile = _template_variant(item_key, category, template_variant)
    canvas = Image.new("RGBA", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(canvas)

    # Instagram safe-zone: keep critical information away from the top profile
    # overlay and bottom action/caption controls.
    SAFE_TOP = 250
    SAFE_BOTTOM = 1635

    # Header: compact, flat newsroom branding.
    d.rectangle((0, 0, REEL_WIDTH, 14), fill=RED)
    d.text((58, 92), "POLITICSHUB", font=_font(30, True), fill=DARK)
    d.text((58, 137), "NEWS  /  ANALYSIS  /  FACTS", font=_font(15, True), fill=MUTED)
    d.rectangle((58, 178, 250, 183), fill=RED)

    # Category marker.
    badge = (category or "NEWS").upper()[:18]
    badge_font = _font(20, True)
    badge_w = d.textbbox((0, 0), badge, font=badge_font)[2] + 34
    d.rectangle((58, SAFE_TOP, 58 + badge_w, SAFE_TOP + 44), fill=RED)
    d.text((75, SAFE_TOP + 11), badge, font=badge_font, fill="white")

    # Independent media area. Never allow text to occupy this region.
    media_top = 325
    media_bottom = 820
    if image:
        _draw_hero(d, canvas, image, (58, media_top, 1022, media_bottom), 8)
        headline_top = 885
    else:
        # No placeholder, no black box, no artificial empty panel.
        headline_top = 355

    # Headline: fit to the remaining safe width and keep it completely
    # separate from the image.
    title_font, title_lines = _fit_title(
        clean_title,
        960,
        4,
        min(1.0, PROFILE_FONT_SCALE[profile] + 0.03),
    )
    y = headline_top
    words = clean_title.split()
    accent = words[(profile + 1) % len(words)].strip(".,:;!?()") if words else ""
    for line in title_lines[:4]:
        x = 58
        for word in line.split():
            bbox = d.textbbox((0, 0), word, font=title_font)
            clean = word.strip(".,:;!?()")
            fill = RED if clean == accent else DARK
            d.text((x, y), word, font=title_font, fill=fill)
            x += bbox[2] + max(8, title_font.size // 8)
        y += title_font.size + 8

    # Summary occupies a bounded block so long source text cannot push the
    # footer into Instagram's bottom controls.
    if clean_summary:
        summary_font = _font(25)
        summary_y = y + 16
        summary_lines = _wrap(clean_summary, summary_font, 950)[:4]
        for line in summary_lines:
            if summary_y + summary_font.size > 1450:
                break
            d.text((58, summary_y), line, font=summary_font, fill=MUTED)
            summary_y += 36

    # Editorial divider and source. Both remain above the lower unsafe zone.
    d.rectangle((58, 1510, 1022, 1516), fill="#e1e4e8")
    if clean_source:
        d.text((58, 1550), "SOURCE", font=_font(15, True), fill=RED)
        d.text((58, 1580), clean_source[:90], font=_font(20, True), fill=DARK)

    # Tiny footer is branding only; no news information is placed here.
    d.rectangle((58, 1625, 245, 1631), fill=RED)
    d.text((58, 1650), "REAL NEWS. REAL PERSPECTIVE.", font=_font(15, True), fill=DARK)

    # QA before handing the PNG to the video builder.
    path = out / f"reel_editorial_{profile:02d}.png"
    canvas.convert("RGB").save(path, format="PNG", optimize=True)
    with Image.open(path) as check:
        if check.size != (REEL_WIDTH, REEL_HEIGHT):
            raise RuntimeError(f"Reel card QA failed: expected 1080x1920, got {check.size}")
        if check.mode not in {"RGB", "RGBA"}:
            raise RuntimeError(f"Reel card QA failed: invalid image mode {check.mode}")
    return [path]

