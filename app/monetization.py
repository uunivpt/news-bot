"""Conservative advertising eligibility, separate from search discovery.

An editor's confirmation is a prerequisite, not a policy-compliance certificate.
Bind it to the reviewed copy so editing/reprocessing cannot reuse an old review.
"""
import hashlib
import json
import re

from app.seo_indexing import is_indexable


def review_fingerprint(row):
    copy = [str(row.get(key) or "").strip() for key in ("title", "url", "source_name", "category", "image_url", "image_license", "image_credit")]
    copy += [str(row.get("bot_summary") or row.get("summary") or "").strip(),
             str(row.get("bot_article") or row.get("article") or row.get("body") or "").strip()]
    return hashlib.sha256(json.dumps(copy, ensure_ascii=False).encode()).hexdigest()


def has_distinct_body(row):
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    lead = normalize(row.get("bot_summary") or row.get("summary"))
    body = normalize(row.get("bot_article") or row.get("article") or row.get("body"))
    # A lead repeated as the article, even under extractive section labels,
    # provides no additional article content. Length is not an originality test.
    remainder = body.replace(lead, "") if lead else ""
    remainder = re.sub(r"\b(?:what happened|key details|what is known|context|what comes next|additional details):", "", remainder)
    return bool(lead and len(body) >= 600 and len(remainder.strip()) >= 100)


def is_monetizable(row):
    if str(row.get("fact_check_status") or "").lower() != "reviewed" or not row.get("approved_at"):
        return False
    if not is_indexable(row) or not has_distinct_body(row):
        return False
    if row.get("image_url") and (str(row.get("image_license") or "").lower() not in
                                {"cc0", "pdm", "rights-owned", "licensed"}
                                or not str(row.get("image_credit") or "").strip()):
        # A publisher image URL by itself is not permission to republish it.
        return False
    notes = str(row.get("fact_check_notes") or "")
    return ("Originality and added value confirmed." in notes
            and "Evidence: https://" in notes
            and "Notes: " in notes
            and "Content SHA256: " + review_fingerprint(row) + "." in notes)
