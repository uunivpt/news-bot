"""PoliticsHub's default premium 4:5 Instagram editorial poster.

No stock/photo placeholder is fabricated. A licensed source image is used only
when the upstream image-acquisition step has recorded its licence/credit.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1080, 1350
BLACK = (8, 9, 11)
WHITE = (246, 246, 246)
GRAY = (166, 169, 173)
RED = (255, 45, 45)
OUTPUT = Path("data/editorial_posters")


def _font(size: int, bold: bool = True):
    stems = ["DejaVuSansCondensed-Bold", "DejaVuSans-Bold"] if bold else ["DejaVuSans", "DejaVuSansCondensed"]
    for stem in stems:
        for root in ("/usr/share/fonts/truetype/dejavu", "/usr/local/share/fonts", "/data/data/com.termux/files/usr/share/fonts"):
            path = Path(root) / (stem + ".ttf")
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                pass
    raise RuntimeError("Editorial poster requires a readable TrueType font")


def _sanitize(value: object) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    text = re.sub(r"[\u0000-\u001f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _wrap(text: str, font, width: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    words = text.split()
    lines, line = [], ""
    for word in words:
        proposal = (line + " " + word).strip()
        if not line or d.textbbox((0, 0), proposal, font=font)[2] <= width:
            line = proposal
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_title(title: str, max_width: int, max_height: int):
    for size in range(98, 47, -2):
        font = _font(size)
        lines = _wrap(title, font, max_width)
        if len(lines) <= 5 and len(lines) * (size + 11) <= max_height and all(
            ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), line, font=font)[2] <= max_width
            for line in lines
        ):
            return font, lines
    raise ValueError("Headline too long for a readable editorial graphic")


def _source_image(row: dict):
    # A remotely hosted article image does not automatically confer republication rights.
    licence = _sanitize(row.get("image_license")).lower()
    credit = _sanitize(row.get("image_credit"))
    if not credit or not licence or licence in {"unknown", "none"}:
        return None
    if not any(term in licence for term in ("creative commons", "cc-by", "cc0", "public domain", "pexels", "pixabay", "unsplash")):
        return None
    candidate = _sanitize(row.get("image_local_path") or row.get("image_url"))
    if not candidate:
        return None
    try:
        if candidate.startswith("https://"):
            response = requests.get(candidate, timeout=10, headers={"User-Agent": "PoliticsHub-Editorial/1.0"})
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                return None
            image = Image.open(io.BytesIO(response.content))
        else:
            image = Image.open(candidate)
        image = ImageOps.exif_transpose(image).convert("RGB")
        return image if image.width >= 350 and image.height >= 250 else None
    except (OSError, requests.RequestException, ValueError):
        return None


def _date(value: object) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        return dt.strftime("%d %b %Y").upper()
    except (ValueError, TypeError):
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y").upper()


def _draw_brand(d: ImageDraw.ImageDraw):
    d.rounded_rectangle((55, 53, 121, 122), radius=8, fill=WHITE)
    d.text((66, 64), "PH", font=_font(34), fill=BLACK)
    d.text((142, 52), "POLITICSHUB.IN", font=_font(41), fill=WHITE)
    d.text((145, 101), "WHAT MATTERS, CLEARLY.", font=_font(15), fill=GRAY)
    d.line((55, 144, 1025, 144), fill=(65, 66, 69), width=2)


def render_editorial_poster(row: dict, output_path: str | Path | None = None) -> Path:
    title = _sanitize(row.get("title") or row.get("headline"))
    summary = _sanitize(row.get("bot_summary") or row.get("summary"))
    source = _sanitize(row.get("source_name") or row.get("source") or "Original report")
    category = _sanitize(row.get("category") or "India").upper()
    if len(title.split()) < 4 or len(summary) < 55:
        raise ValueError("Editorial poster blocked: incomplete headline or source summary")
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    d = ImageDraw.Draw(canvas)
    _draw_brand(d)

    photo = _source_image(row)
    if photo:
        photo = ImageOps.fit(photo, (970, 600), method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))
        photo = ImageOps.grayscale(photo).convert("RGB")
        photo = photo.point(lambda x: int(x * 0.86))
        canvas.paste(photo, (55, 174))
        d = ImageDraw.Draw(canvas)
        # Dark gradient protects headlines over bright pictures.
        overlay = Image.new("RGBA", (970, 600), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(600):
            strength = 5 + int(205 * (y / 599) ** 2.1)
            od.line((0, y, 970, y), fill=(0, 0, 0, strength))
        canvas.paste(Image.alpha_composite(canvas.crop((55, 174, 1025, 774)).convert("RGBA"), overlay).convert("RGB"), (55, 174))
        d = ImageDraw.Draw(canvas)
    else:
        # Intentional magazine-style typographic treatment; never invent a news photo.
        for offset in range(0, 740, 36):
            d.line((55 + offset, 200, 55, 200 + offset), fill=(36, 39, 43), width=2)
        d.text((100, 250), "PH", font=_font(365), fill=(35, 38, 43))
        d.rectangle((55, 706, 1025, 712), fill=(74, 75, 78))
        d.rectangle((55, 706, 300, 712), fill=RED)

    d.rounded_rectangle((55, 740, 245, 794), radius=5, fill=RED)
    badge = category[:14]
    size = 26
    while size >= 15 and d.textbbox((0, 0), badge, font=_font(size))[2] > 155:
        size -= 1
    d.text((71, 752), badge, font=_font(size), fill=WHITE)
    d.text((265, 752), _date(row.get("published_at") or row.get("date")), font=_font(22), fill=WHITE)
    d.line((55, 813, 1025, 813), fill=(68, 68, 71), width=2)

    title_font, lines = _fit_title(title.upper(), 955, 305)
    top = 842
    accent = len(lines) - 1
    for i, line in enumerate(lines):
        d.text((55, top + i * (title_font.size + 11)), line, font=title_font, fill=RED if i == accent and len(lines) > 1 else WHITE)
    description_y = min(1171, top + len(lines) * (title_font.size + 11) + 22)
    summary_font = _font(24, False)
    for index, line in enumerate(_wrap(summary, summary_font, 940)[:3]):
        yy = description_y + index * 32
        if yy + 25 > 1244:
            break
        d.text((57, yy), line, font=summary_font, fill=GRAY)

    d.line((55, 1272, 1025, 1272), fill=(92, 92, 96), width=2)
    label = "SOURCE  " + source[:65]
    d.text((55, 1292), label, font=_font(18), fill=GRAY)
    d.text((750, 1292), "POLITICSHUB.IN", font=_font(18), fill=WHITE)
    identifier = _sanitize(row.get("id") or title)
    name = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:18] + ".jpg"
    path = Path(output_path) if output_path else OUTPUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "JPEG", quality=94, optimize=True)
    return path


def editorial_caption(row: dict) -> str:
    """A substantial multi-paragraph sourced news article, not a thin teaser."""
    title = _sanitize(row.get("title") or row.get("headline"))
    summary = _sanitize(row.get("bot_summary") or row.get("summary"))
    raw_article = str(row.get("bot_article") or "").strip()
    paragraphs = [
        _sanitize(p) for p in re.split(r"\n\s*\n", raw_article)
        if _sanitize(p)
    ]
    source = _sanitize(row.get("source_name") or row.get("source") or "Original report")
    url = _sanitize(row.get("url"))
    category = _sanitize(row.get("category") or "india").lower()
    # Remove duplicate introduction if the bot already starts with the lead.
    if paragraphs and paragraphs[0] == summary:
        paragraphs.pop(0)
    body = summary + ("\n\n" + "\n\n".join(paragraphs) if paragraphs else "")
    out = title + "\n\n" + body + "\n\nSource: " + source
    if url.startswith("https://"):
        out += "\nOriginal report: " + url
    licence = _sanitize(row.get("image_license"))
    credit = _sanitize(row.get("image_credit"))
    if credit and licence and licence.lower() != "unknown":
        out += "\nVisual credit: " + credit + " (" + licence + ")"
    hashtag = "#PoliticsHub #IndiaNews #" + re.sub(r"[^A-Za-z]", "", category.title()) + "News"
    return out[:max(0, 2200 - len(hashtag))].rstrip() + "\n\n" + hashtag
