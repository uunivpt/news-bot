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


def _fit_title(text: str, max_width: int, max_lines: int = 3):
    # Keep Reel headlines visibly large on a 1080x1920 canvas. The previous
    # 48px fallback made long headlines look tiny once Instagram displayed the
    # full Reel in the feed.
    for size in range(132, 71, -2):
        font = _font(size, True)
        lines = _wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(72, True)
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


def generate_reel_cards(
    title: str,
    summary: str,
    category: str,
    image_url: str | None,
    output_dir: str | Path,
    source_name: str = "",
) -> list[Path]:
    """Generate the supplied PoliticsHub 9:16 editorial layout.

    Layout:
      masthead -> faint world map -> fixed hero image panel -> category ->
      large bold headline -> short summary -> source -> footer branding.
    The layout is intentionally fixed so long/short source images cannot
    move the headline into the Instagram UI-safe area.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    clean_title = clean_instagram_text(title, source_name) or "Latest news update"
    clean_summary = clean_instagram_text(summary, source_name)
    clean_source = clean_instagram_text(source_name) or "PoliticsHub"
    image = _download_image(image_url)

    canvas = Image.new("RGBA", (REEL_WIDTH, REEL_HEIGHT), "white")
    d = ImageDraw.Draw(canvas)

    # --- Header / supplied visual identity ---
    d.polygon([(0, 0), (72, 0), (0, 225)], fill=RED)
    d.polygon([(REEL_WIDTH, 0), (REEL_WIDTH - 18, 0), (REEL_WIDTH, 265)], fill="#eceef1")
    _draw_logo(d)
    _draw_tagline(d)
    _draw_world_dots(d)

    # Small right-side vertical topic list from the reference.
    topic_font = _font(14, True)
    for i, label in enumerate(("POLITICS", "ECONOMY", "GLOBAL", "UPDATES")):
        d.text((930, 150 + i * 27), label, font=topic_font, fill="#cfd2d6")

    # --- Optional hero image panel ---
    # No image means no image section, placeholder, or reserved empty frame.
    if image:
        frame = (50, 315, 1030, 800)
        d.rounded_rectangle(frame, radius=28, fill="#172038", outline="#ffffff", width=6)
        inner = (62, 327, 1018, 788)
        fitted = ImageOps.fit(
            image,
            (inner[2] - inner[0], inner[3] - inner[1]),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        mask = Image.new("L", fitted.size, 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle(
            (0, 0, fitted.width - 1, fitted.height - 1),
            radius=20,
            fill=255,
        )
        canvas.paste(fitted, (inner[0], inner[1]), mask)
        d.rounded_rectangle(frame, radius=28, outline="#ffffff", width=6)

    # --- Category ---
    # Without an image, move the news block upward into the visual center.
    badge_y = 845 if image else 735
    category_label = (category or "news").upper()[:15]
    badge_font = _font(25, True)
    badge_w = max(190, d.textbbox((0, 0), category_label, font=badge_font)[2] + 56)
    d.rounded_rectangle(
        (58, badge_y, 58 + badge_w, badge_y + 64),
        radius=15,
        fill=RED,
    )
    d.text((84, badge_y + 17), category_label, font=badge_font, fill="white")

    # --- Main headline ---
    # Use the largest size that fits into four lines. The regular Android
    # Roboto fallback is given a small stroke so it remains visually bold.
    title_font, title_lines = _fit_title(clean_title, 930, 4)
    headline_y = 940 if image else 830
    words = clean_title.split()
    highlight_word = None
    priority = (
        "America's", "America", "India", "India's", "Russia", "Ukraine",
        "Israel", "Iran", "China", "Trump", "Modi", "White", "House",
        "Europe", "NATO", "UN", "UK", "US",
    )
    for candidate in priority:
        for word in words:
            if word.strip(".,:;!?()") == candidate:
                highlight_word = candidate
                break
        if highlight_word:
            break
    if highlight_word is None and len(words) >= 3:
        highlight_word = words[1].strip(".,:;!?()")

    # Re-wrap using the exact font selected above and draw each word so the
    # selected emphasis word stays red without changing line geometry.
    title_lines = _wrap(clean_title, title_font, 930)[:4]
    y = headline_y
    for line in title_lines:
        x = 58
        for word in line.split():
            clean_word = word.strip(".,:;!?()")
            bbox = d.textbbox((0, 0), word, font=title_font, stroke_width=2)
            fill = RED if highlight_word and clean_word == highlight_word else DARK
            d.text(
                (x, y),
                word,
                font=title_font,
                fill=fill,
                stroke_width=2,
                stroke_fill=fill,
            )
            x += bbox[2] + max(8, title_font.size // 8)
        y += title_font.size + 8

    # --- Summary ---
    summary_end = y
    if clean_summary:
        summary_text = clean_summary
        if summary_text.casefold().startswith(clean_title.casefold()):
            summary_text = summary_text[len(clean_title):].lstrip(" :–—|/-")
        summary_text = re.sub(
            r"^(?:(?:just\s*in|breaking(?:\s+news)?|latest\s+news|latest\s+update|news\s+alert|alert|exclusive)\s*[:\-–—|/]+\s*)+",
            "",
            summary_text,
            flags=re.I,
        ).strip(" -–—|/:")
        if summary_text:
            summary_font = _font(28)
            summary_y = y + 22
            summary_lines = _wrap(summary_text, summary_font, 900)[:3]
            for line in summary_lines:
                d.text((62, summary_y), line, font=summary_font, fill="#454b53")
                summary_y += 39
            summary_end = summary_y

    # --- Source / footer ---
    # Keep this safely above the bottom Instagram controls.
    footer_y = 1615
    d.rectangle((62, footer_y, 122, footer_y + 6), fill=RED)
    d.text(
        (62, footer_y + 26),
        f"Source: {clean_source}",
        font=_font(20, True),
        fill=DARK,
    )

    # Reference-style bottom band.
    band_y = 1760
    d.polygon([(0, band_y), (700, band_y), (585, REEL_HEIGHT), (0, REEL_HEIGHT)], fill=RED)
    d.polygon([(700, band_y), (REEL_WIDTH, band_y), (REEL_WIDTH, REEL_HEIGHT), (585, REEL_HEIGHT)], fill="#151b2b")
    d.text((60, band_y + 40), "R E A L  N E W S", font=_font(18, True), fill="white")
    d.text((60, band_y + 68), "R E A L  P E R S P E C T I V E", font=_font(16, True), fill="white")
    d.rectangle((60, band_y + 108, 110, band_y + 113), fill="white")

    follow = _font(16, True)
    d.text((770, band_y + 38), "FOLLOW", font=follow, fill="white")
    d.text((770, band_y + 68), "FOR MORE", font=follow, fill="white")

    path = out / "01_editorial.png"
    canvas.convert("RGB").save(path, format="PNG", optimize=True)
    return [path]
