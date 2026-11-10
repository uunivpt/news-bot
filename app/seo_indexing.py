"""Canonical URLs and conservative eligibility for search-engine sitemaps.

Source of truth for both Google discovery XML and page-level indexability.
Never put missing/thin/unattributed articles into the discoverable sitemap.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from app.news_numbers import news_number
from app.category_routing import normalize_category

SITE_ORIGIN = "https://www.politicshub.in"
CATEGORIES = {
    "general": "india", "india": "india", "politics": "politics", "world": "world",
    "business": "business", "technology": "technology", "sports": "sports",
    "entertainment": "entertainment", "science": "science", "health": "health", "hindi": "hindi"
}
STATIC_PAGES = (
    "/", "/data/", "/archive/", "/library/", "/exams/", "/about.html", "/contact.html", "/editorial-policy.html",
    "/corrections.html", "/privacy.html", "/cookies.html", "/terms.html",
    "/disclaimer.html", "/newsletter.html", "/topics/", "/data-rights.html",
    "/licenses.html", "/sources.html", "/maharashtra/", "/india/", "/politics/", "/world/", "/hindi/",
    "/guides/election-results.html", "/guides/maharashtra-mlc.html",
    "/guides/government-notifications.html", "/guides/reading-breaking-news.html",
    "/guides/verify-political-claims.html"
)


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:110] or "story"


def canonical_path(row):
    category = normalize_category(row.get("category"), row.get("title"), row.get("bot_summary") or row.get("summary"))
    category = CATEGORIES.get(category, "india")
    return f"/{category}/{news_number(row)}"


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def is_indexable(row, now=None):
    """Require genuine original-source context; exclusion is NOT a fact-check."""
    if not isinstance(row, dict) or row.get("status", "published") != "published":
        return False
    if not row.get("public_source") or str(row.get("source_type") or "").lower() == "telegram":
        return False
    # Automated RSS summaries are useful as a source directory, but they are
    # not automatically unique search articles. Leave them browsable and
    # source-linked; only promote separately curated or explicitly reviewed
    # RSS copy to Google's article discovery surfaces.
    if str(row.get("source_type") or "").lower() == "rss" and not (
        row.get("editorial_value")
        or str(row.get("fact_check_status") or "").lower() == "reviewed"
        or row.get("seo_reviewed") is True
        or row.get("ads_eligible") is True
    ):
        return False
    try:
        if int(row.get("id") or 0) <= 0:
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    url = str(row.get("url") or "").strip()
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
    except ValueError:
        return False
    title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
    lead = re.sub(r"\s+", " ", str(row.get("bot_summary") or row.get("summary") or "")).strip()
    article = str(row.get("bot_article") or row.get("article") or "").strip()
    if not 5 <= len(title.split()) <= 28 or len(title) > 210:
        return False
    if "..." in title or "…" in title or lead.endswith(("...", "…", "read more")):
        return False
    if len(lead) < 80 or len(article) < 300 or len(article.split()) < 45:
        return False
    if re.sub(r"\s+", " ", article).strip().casefold() == lead.casefold():
        # A publisher excerpt repeated as its own article is a reading aid,
        # not a separate full report for the search/news sitemap.
        return False
    published = _date(row.get("published_at_site") or row.get("published_at_iso") or row.get("published_at"))
    if not published:
        return False
    current = now or datetime.now(timezone.utc)
    if published > current + timedelta(minutes=30):
        return False
    return True


def eligible_articles(rows, now=None):
    seen_ids, seen_urls, eligible = set(), set(), []
    for row in rows:
        if not is_indexable(row, now=now):
            continue
        key, url = int(row["id"]), str(row["url"]).strip()
        if key in seen_ids or url in seen_urls:
            continue
        seen_ids.add(key)
        seen_urls.add(url)
        eligible.append(row)
    eligible.sort(key=lambda row: _date(row.get("published_at_site") or row.get("published_at_iso") or row.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return eligible


def news_sitemap_xml(rows, now=None):
    articles = eligible_articles(rows, now=now)
    entries = "".join("<url><loc>" + escape(SITE_ORIGIN + canonical_path(r)) + "</loc></url>" for r in articles)
    return '<?xml version="1.0" encoding="UTF-8"?>' + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + "</urlset>"


def static_sitemap_xml():
    entries = "".join("<url><loc>" + escape(SITE_ORIGIN + url) + "</loc></url>" for url in STATIC_PAGES)
    return '<?xml version="1.0" encoding="UTF-8"?>' + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + "</urlset>"


# Standalone articles need documented source verification before discovery.
# Previously promoted static reports are withheld; their URLs show review notices.
STANDALONE_NEWS = ()


def standalone_sitemap_url_xml():
    return "".join(
        "<url><loc>" + escape(SITE_ORIGIN + story["path"]) + "</loc></url>"
        for story in STANDALONE_NEWS
    )


def _news_language(row):
    """Use actual article language for Google News; do not label Hindi as English."""
    language = str(row.get("language") or "").strip().lower().replace("_", "-").split("-", 1)[0]
    if language in {"en", "hi", "mr"}:
        return language
    if str(row.get("category") or "").lower() == "hindi":
        return "hi"
    title = str(row.get("title") or "")
    source = str(row.get("source_name") or "").lower()
    if re.search(r"[\u0900-\u097f]", title) and ("marathi" in source or "majha" in source or "माझा" in source):
        return "mr"
    return "en"


def google_news_sitemap_xml(rows, now=None):
    """Google News extension. Only articles published in the previous 48 hours.

    The regular news-sitemap.xml remains an archival index; Google News-specific
    metadata expires and is never refreshed merely to promote older content.
    """
    current = now or datetime.now(timezone.utc)
    start = current - timedelta(hours=48)
    candidates = []
    for row in eligible_articles(rows, now=current):
        published = _date(row.get("published_at_iso") or row.get("published_at_site") or row.get("published_at"))
        if published and start <= published <= current + timedelta(minutes=30):
            candidates.append((SITE_ORIGIN + canonical_path(row), str(row["title"]), published, _news_language(row)))
    for story in STANDALONE_NEWS:
        published = _date(story["published_at"])
        if published and start <= published <= current + timedelta(minutes=30):
            candidates.append((SITE_ORIGIN + story["path"], story["title"], published, story["language"]))
    unique, seen = [], set()
    for url, title, published, language in sorted(candidates, key=lambda a: a[2], reverse=True):
        if url not in seen:
            seen.add(url)
            unique.append((url, title, published, language))
    items = []
    for url, title, published, language in unique[:1000]:
        items.append(
            "<url><loc>" + escape(url) + "</loc><news:news>"
            "<news:publication><news:name>PoliticsHub.in</news:name>"
            "<news:language>" + escape(language) + "</news:language></news:publication>"
            "<news:publication_date>" + escape(published.isoformat(timespec="seconds")) + "</news:publication_date>"
            "<news:title>" + escape(title) + "</news:title>"
            "</news:news></url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        + "".join(items) + "</urlset>"
    )

def sitemap_index_xml():
    entries = "".join("<sitemap><loc>" + escape(SITE_ORIGIN + file) + "</loc></sitemap>" for file in ("/static-sitemap.xml", "/news-sitemap.xml", "/google-news.xml"))
    return '<?xml version="1.0" encoding="UTF-8"?>' + '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + "</sitemapindex>"
