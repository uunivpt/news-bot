"""Shared cleanup for source-derived news text."""
import re
import unicodedata

EDITORIAL_PREFIX_RE = re.compile(
    r"^\s*(?:just\s*in|breaking(?:\s+news)?|latest\s+news|latest\s+update|news\s+alert|alert|exclusive)\s*[:\-–—|]+\s*",
    re.I,
)

HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}", re.I)

PROMO_NAV_RE = re.compile(r"\b(?:socials|donate|advertising)\b(?:\s*[|•·/,-]\s*\b(?:socials|donate|advertising)\b)*", re.I)

SOURCE_FRAGMENT_RE = re.compile(
    r"(?:\bsource\s*:\s*|\bvia\s+|\baccording\s+to\s+|\breported\s+by\s+|\bcredit\s*:\s*)[^|•\n]+",
    re.I,
)

def _strip_unsupported_symbols(text: str) -> str:
    """Remove emoji/symbol glyphs that DejaVu cannot reliably render.

    The news cards intentionally use typography, not emoji. Unsupported
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

def clean_news_text(text: str, source_name: str = "") -> str:
    value = _strip_unsupported_symbols(re.sub(r"\s+", " ", str(text or "")).strip())
    if not value:
        return ""
    # Source text sanitizer:
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
