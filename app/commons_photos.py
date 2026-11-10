"""Conservative Wikimedia Commons file-photo enrichment for named news subjects.

No image generation, publisher scraping, guessed event photography or license bypass.
A Wikipedia article's pageimage is only an *illustrative file photo*, never a
photo of the event being reported. Refuse uncertain identity/license metadata.
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit

from app.source_http import fetch_source, public_http_url

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "app/data/commons-photo-cache.json"
SNAPSHOT = ROOT / "public/news-data.json"

# Exact, distinctive named subjects, with a known encyclopedia identity.
# Never match a broad desk/location label such as "India", "news" or "Delhi".
TOPICS = (
    ("Supreme Court of India", "Supreme Court of India"),
    ("Supreme Court", "Supreme Court of India"),
    ("White House", "White House"),
    ("Narendra Modi", "Narendra Modi"),
    ("PM Modi", "Narendra Modi"),
    ("Rahul Gandhi", "Rahul Gandhi"),
    ("Donald Trump", "Donald Trump"),
    ("Elon Musk", "Elon Musk"),
    ("Vladimir Putin", "Vladimir Putin"),
    ("Volodymyr Zelenskyy", "Volodymyr Zelenskyy"),
    ("Pawan Kalyan", "Pawan Kalyan"),
    ("Uddhav Thackeray", "Uddhav Thackeray"),
    ("Amit Shah", "Amit Shah"),
    ("Rashtrapati Bhavan", "Rashtrapati Bhavan"),
    ("Parliament House, New Delhi", "Parliament House, New Delhi"),
    ("United Nations headquarters", "Headquarters of the United Nations"),
    ("Nvidia", "Nvidia"),
    ("NVIDIA", "Nvidia"),
    ("Jensen Huang", "Jensen Huang"),
    ("Delhi air pollution", "Air pollution in Delhi"),
    ("Delhi AQI", "Air pollution in Delhi"),
)

LICENSES = {
    "cc0": ("cc0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "public domain": ("pdm", "https://creativecommons.org/publicdomain/mark/1.0/"),
    "cc by 4.0": ("cc-by-4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "cc by-sa 4.0": ("cc-by-sa-4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
}


def topic_for(title):
    text = str(title or "")
    matched = set()
    for term, subject in TOPICS:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I):
            matched.add(subject)
    return next(iter(matched)) if len(matched) == 1 else None


def valid_photo(photo):
    if not isinstance(photo, dict):
        return False
    url = str(photo.get("image_url") or "")
    try:
        parsed = urlsplit(url)
        page = urlsplit(str(photo.get("image_source_url") or ""))
        lic = urlsplit(str(photo.get("image_license_url") or ""))
        if parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
            return False
        if not parsed.path.startswith("/wikipedia/commons/") or parsed.query or parsed.fragment:
            return False
        if not re.search(r"\.(?:jpe?g|png|webp)$", parsed.path, re.I):
            return False
        if re.search(r"(?:logo|favicon|avatar|icon|emblem|flag|coat.of.arms|placeholder|diagram)", parsed.path, re.I):
            return False
        if page.scheme != "https" or page.hostname != "commons.wikimedia.org" or not page.path.startswith("/wiki/File:"):
            return False
        if (lic.scheme, lic.hostname) != ("https", "creativecommons.org"):
            return False
    except ValueError:
        return False
    if photo.get("image_source") != "wikimedia-commons":
        return False
    allowed = {license for license, _ in LICENSES.values()}
    if str(photo.get("image_license") or "") not in allowed:
        return False
    if not str(photo.get("image_credit") or "").strip() or len(str(photo.get("image_credit"))) > 220:
        return False
    return public_http_url(url)


def _json_query(host, params, transport):
    endpoint = "https://" + host + "/w/api.php?" + urlencode({**params, "action": "query", "format": "json", "formatversion": "2"})
    response = transport(endpoint, timeout=8, max_bytes=300_000)
    return json.loads(response.content)


def lookup_photo(subject, *, transport=fetch_source):
    """Resolve exactly one subject's encyclopedia page image and its license."""
    if subject not in {value for _, value in TOPICS}:
        return None
    first = _json_query("en.wikipedia.org", {"prop": "pageimages", "piprop": "name", "titles": subject}, transport)
    pages = first.get("query", {}).get("pages", [])
    if len(pages) != 1 or pages[0].get("missing") or not pages[0].get("pageimage"):
        return None
    filename = str(pages[0]["pageimage"])
    if not re.search(r"\.(?:jpe?g|png|webp)$", filename, re.I) or re.search(
        r"(?:logo|favicon|avatar|icon|emblem|flag|coat.of.arms|placeholder|diagram)", filename, re.I
    ):
        return None
    second = _json_query(
        "commons.wikimedia.org",
        {"prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1200", "titles": "File:" + filename},
        transport,
    )
    files = second.get("query", {}).get("pages", [])
    if len(files) != 1 or not files[0].get("imageinfo"):
        return None
    info = files[0]["imageinfo"][0]
    if int(info.get("width") or 0) < 800 or int(info.get("height") or 0) < 380:
        return None
    aspect = int(info["width"]) / int(info["height"])
    if not 0.5 <= aspect <= 3.5:
        return None
    fields = info.get("extmetadata") or {}
    license_name = BeautifulSoup(str((fields.get("LicenseShortName") or {}).get("value") or ""), "html.parser").get_text(" ", strip=True).lower()
    normalized = LICENSES.get(re.sub(r"\s+", " ", license_name))
    if not normalized:
        return None
    artist = BeautifulSoup(str((fields.get("Artist") or {}).get("value") or ""), "html.parser").get_text(" ", strip=True)
    if not artist or artist.casefold() in {"unknown", "anonymous"}:
        if normalized[0] not in {"cc0", "pdm"}:
            return None
        artist = "Wikimedia Commons public-domain archive"
    artist = " ".join(artist.split())[:220]
    result = {
        "image_url": info.get("thumburl") or info.get("url") or "",
        "image_source": "wikimedia-commons",
        "image_credit": artist,
        "image_license": normalized[0],
        "image_license_url": normalized[1],
        "image_source_url": info.get("descriptionurl") or "",
    }
    return result if valid_photo(result) else None


def _cache_is_recent(entry, now):
    try:
        checked = datetime.fromisoformat(entry["checked_at"])
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return now - checked.astimezone(timezone.utc) < timedelta(days=21)
    except (KeyError, TypeError, ValueError):
        return False


def enrich(rows, cache, *, lookup=lookup_photo, max_lookup=4, now=None):
    """Add media only to exact subject matches. Never replace approved story art."""
    now = now or datetime.now(timezone.utc)
    stored = dict(cache or {})
    output = []
    matched = 0
    queried = 0
    for raw in rows:
        row = dict(raw)
        subject = topic_for(row.get("title"))
        # Preserve valid photos explicitly supplied by and licensed to the editor.
        if row.get("image_source") == "article-source" and row.get("image_url"):
            output.append(row)
            continue
        if row.get("image_source") == "wikimedia-commons":
            for key in ("image_url", "image_source", "image_credit", "image_license", "image_source_url", "image_license_url"):
                row.pop(key, None)
        if subject:
            entry = stored.get(subject)
            if not isinstance(entry, dict) or not _cache_is_recent(entry, now):
                if queried < max_lookup:
                    queried += 1
                    try:
                        photo = lookup(subject)
                    except Exception:
                        # Connectivity errors are retried next run; do not poison cache.
                        photo = None
                    else:
                        entry = {"checked_at": now.isoformat(), "photo": photo if valid_photo(photo) else None}
                        stored[subject] = entry
            if isinstance(entry, dict) and _cache_is_recent(entry, now) and valid_photo(entry.get("photo")):
                row.update(entry["photo"])
                matched += 1
        output.append(row)
    return output, stored, matched, queried


@lru_cache(maxsize=1)
def snapshot_photo_index():
    """Read only locally deployed, preapproved Commons metadata by exact source URL."""
    try:
        rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(rows, list):
        return {}
    return {str(row["url"]): {k: row[k] for k in (
        "image_url", "image_source", "image_credit", "image_license", "image_source_url", "image_license_url"
    ) if k in row} for row in rows if isinstance(row, dict) and row.get("url") and valid_photo(row)}


def snapshot_photo_for_url(url):
    return snapshot_photo_index().get(str(url or ""))
