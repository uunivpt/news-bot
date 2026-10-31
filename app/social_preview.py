"""High-contrast PNG link previews for PoliticsHub.in (1200x630)."""
from __future__ import annotations
import io
import re
import os
import time
from pathlib import Path
from urllib.request import urlopen
from PIL import Image, ImageDraw, ImageFont

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/"
    "ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf"
)
_FONT_DOWNLOAD_FAILED_AT = 0.0


def _devanagari_font_path():
    """Use the bundled OFL font on Vercel, with system and cold-start fallbacks."""
    global _FONT_DOWNLOAD_FAILED_AT
    candidates = (
        Path(__file__).resolve().parent / "fonts/NotoSansDevanagari.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf"),
        Path("/tmp/politicshub-NotoSansDevanagari.ttf"),
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 100_000:
                return str(candidate)
        except OSError:
            continue
    # A read-only Vercel deployment can still cache the font under /tmp.
    # Avoid an external request on every share if the font CDN is down.
    if time.monotonic() - _FONT_DOWNLOAD_FAILED_AT < 300:
        return None
    target = candidates[-1]
    temporary = target.with_name(target.name + "." + str(os.getpid()) + ".tmp")
    try:
        with urlopen(_FONT_URL, timeout=5) as response:
            payload = response.read(850_001)
        if not 100_000 < len(payload) < 850_000 or payload[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
            raise ValueError("Invalid Devanagari font download")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
        return str(target)
    except (OSError, ValueError):
        _FONT_DOWNLOAD_FAILED_AT = time.monotonic()
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _font(size: int, bold: bool = False, sample: str = ""):
    if _DEVANAGARI.search(sample):
        path = _devanagari_font_path()
        if path:
            try:
                face = ImageFont.truetype(path, size)
                # Google Fonts distributes a variable Width/Weight font.
                try:
                    axes = face.get_variation_axes()
                    values = [axis["default"] for axis in axes]
                    for index, axis in enumerate(axes):
                        if axis["name"] == b"Weight":
                            values[index] = 700 if bold else 400
                    face.set_variation_by_axes(values)
                except (AttributeError, OSError, ValueError):
                    pass
                return face
            except (OSError, ValueError):
                pass
    paths = (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf") if bold else
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _safe_preview_title(title: str) -> str:
    """Never render empty-square characters when Devanagari fonts are unavailable."""
    if not _DEVANAGARI.search(title) or _devanagari_font_path():
        return title
    latin = re.sub(r"[\u0900-\u097F]+", " ", title)
    latin = re.sub(r"\s+", " ", latin).strip(" -:;,")
    return (latin + " — Read the full story") if len(latin) >= 8 else "Marathi news — Read the full story"


def _canvas():
    image = Image.new("RGB", (1200, 630), (8, 10, 13))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 9), fill=(255, 45, 45))
    for x in (844, 924, 1004, 1084, 1164):
        draw.line((x, 0, x - 228, 629), fill=(24, 27, 32), width=2)
    draw.rounded_rectangle((72, 67, 170, 165), radius=16, fill=(255, 45, 45))
    draw.text((89, 84), "PH", font=_font(48, True), fill=(255, 255, 255))
    title_font = _font(53, True)
    draw.text((190, 76), "Politics", font=title_font, fill=(253, 253, 253))
    hub_x = 190 + int(draw.textlength("Politics", font=title_font)) + 6
    draw.text((hub_x, 76), "Hub", font=title_font, fill=(170, 176, 185))
    draw.text((194, 139), "INDEPENDENT NEWSROOM", font=_font(16, True), fill=(167, 172, 180))
    draw.rectangle((72, 544, 1128, 546), fill=(54, 58, 65))
    draw.text((73, 568), "POLITICSHUB.IN", font=_font(22, True), fill=(234, 237, 241))
    draw.text((900, 568), "INDIA  |  WORLD  |  POLITICS", font=_font(16, True), fill=(150, 155, 160))
    return image, draw

def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()

def render_home():
    image, draw = _canvas()
    draw.text((70, 250), "WHAT MATTERS,", font=_font(83, True), fill=(252, 252, 252))
    draw.text((70, 355), "CLEARLY.", font=_font(105, True), fill=(255, 45, 45))
    draw.text((73, 493), "Source-linked reports. Clear perspective.", font=_font(23), fill=(174, 181, 190))
    return _png(image)

def _lines(draw, title, face, max_width=1050):
    lines, current = [], ""
    for word in title.split():
        next_line = (current + " " + word).strip()
        if draw.textlength(next_line, font=face) <= max_width or not current:
            current = next_line
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def render_story(title: str, category: str = "News"):
    image, draw = _canvas()
    category_label = "NEWS  /  " + str(category).upper()[:30]
    if _DEVANAGARI.search(category_label) and not _devanagari_font_path():
        category_label = "NEWS"
    draw.text((73, 212), category_label, font=_font(23, True, category_label), fill=(255, 75, 75))
    title = _safe_preview_title(re.sub(r"\s+", " ", str(title or "Latest PoliticsHub report")).strip())
    for size in (67, 60, 53, 46, 40):
        face = _font(size, True, title)
        lines = _lines(draw, title, face)
        if len(lines) <= 3:
            break
    if len(lines) > 3:
        lines = lines[:3]
        while len(lines[-1]) > 2 and draw.textlength(lines[-1] + "...", font=face) > 1050:
            lines[-1] = lines[-1][:-1].rstrip()
        lines[-1] += "..."
    height = min(size + 19, 86)
    for index, line in enumerate(lines):
        draw.text((70, 263 + index * height), line, font=face, fill=(250, 250, 250))
    return _png(image)
