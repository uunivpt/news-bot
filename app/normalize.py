import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.lower().strip()
    return re.sub(r"\s+", " ", value)


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def fingerprint(url: str, title: str) -> tuple[str, str]:
    url_hash = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
    title_hash = hashlib.sha256(normalize_text(title).encode("utf-8")).hexdigest()
    return url_hash, title_hash
