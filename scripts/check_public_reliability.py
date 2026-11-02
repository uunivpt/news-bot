"""Read-only public reliability smoke check (no database or admin credentials).

A GitHub scheduled job uses this to ensure public delivery, article pages and
read-only gateway diagnostics stay observable without coupling uptime to Termux.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://www.politicshub.in"
PRIVATE_FIELDS = {"password_hash", "admin_token", "fact_check_notes", "approved_at",
                  "external_id", "url_hash", "title_hash", "csrf_token"}


def read(path: str, *, timeout: int = 15):
    request = Request(BASE + path, headers={"User-Agent": "PoliticsHub-Public-Health/1",
                                           "Accept": "application/json,text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1_000_000).decode("utf-8")
    except HTTPError as response:
        return response.code, response.read(100_000).decode("utf-8", "replace")


def check(fetch=read):
    issues = []
    health_status, health_text = fetch("/api/health")
    try:
        health = json.loads(health_text)
    except ValueError:
        health = {}
    if health_status != 200 or not health.get("ok") or not health.get("stories"):
        issues.append("Public health is not serving a usable news feed")
    else:
        print("Public feed healthy; records reported:", health["stories"])

    status, feed_text = fetch("/api/news?limit=30")
    try:
        feed = json.loads(feed_text)
    except ValueError:
        feed = None
    if status != 200 or not isinstance(feed, list) or not feed:
        issues.append("News list endpoint is unavailable or empty")
        feed = []
    else:
        for row in feed:
            if not isinstance(row, dict) or not row.get("title") or not row.get("id"):
                issues.append("Public news list contains an invalid record")
                break
            if row.get("status", "published") != "published" or PRIVATE_FIELDS.intersection(row):
                issues.append("Public news list exposed a nonpublished or private record")
                break
        print("Public news list HTTP 200; inspected:", len(feed))

    politics_status, politics_text = fetch("/api/news?category=politics&limit=50")
    try:
        politics = json.loads(politics_text)
    except ValueError:
        politics = None
    if politics_status != 200 or not isinstance(politics, list):
        issues.append("Politics desk endpoint must return a valid list (even if empty)")
    else:
        print("Politics desk records:", len(politics))

    html_status, page = fetch("/politics/")
    if html_status != 200 or "Politics news" not in page:
        issues.append("Politics page is unavailable")
    elif politics:
        match = re.search(r'href="/politics/">Politics<small>(\d+)</small>', page)
        if not match or int(match.group(1)) < 1:
            issues.append("Politics navigation counter does not represent published stories")

    if feed:
        article_status, article_text = fetch("/api/news/" + str(feed[0]["id"]))
        try:
            article = json.loads(article_text)
        except ValueError:
            article = {}
        if article_status != 200 or article.get("id") != feed[0]["id"]:
            issues.append("Published article detail endpoint is inconsistent")

    # Phone access requires an owner login. Treat its availability as a separate
    # diagnostic, not a prerequisite for the independent GitHub public feed.
    try:
        gateway_status, gateway_text = fetch("/api/admin/me")
        gateway = json.loads(gateway_text)
        if isinstance(gateway, dict) and gateway_status in (200, 401, 403):
            print("Unauthenticated admin gateway answered; no privileged access tested")
        else:
            print("::warning::Admin/phone gateway could not be validated anonymously")
    except (ValueError, URLError, TimeoutError):
        print("::warning::Admin/phone gateway unavailable; check authenticated owner flow")

    for issue in issues:
        print("::error::" + issue)
    return not issues


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
