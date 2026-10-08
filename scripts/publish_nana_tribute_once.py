"""One-off, idempotent editorial release for the verified 8 Oct 2026 tribute.

This deliberately uses an original text-only Reel: the social-media video
submitted as creative reference does not provide a redistribution licence.
"""
from datetime import datetime, timezone

from app.database import NewsDatabase
from app.models import NewsItem
from app.advanced_system import ensure_schema as ensure_upgrade_schema

SOURCE_URL = "https://www.reuters.com/business/media-telecom/bollywood-actor-nana-patekar-dies-75-2026-10-08/"
TITLE = "Nana Patekar dies at 75 in Goa, leaving a lasting cinema legacy"
SUMMARY = (
    "Veteran actor Nana Patekar died in Goa on 8 October 2026, aged 75. "
    "Known for Parinda, Krantiveer, Ab Tak Chhappan and the Marathi film "
    "Natsamrat, his performances left a deep mark on Indian cinema."
)
ARTICLE = (
    "Veteran Indian actor Nana Patekar died in Goa on Thursday, 8 October "
    "2026, aged 75. The news was reported by Reuters and the Associated "
    "Press, and tributes followed across the film industry.\n\n"
    "Over a career spanning decades, Patekar became known for his commanding "
    "screen presence and distinctive dialogue delivery. His notable work "
    "included Parinda, Krantiveer and Ab Tak Chhappan, and he also made "
    "a major contribution to Marathi cinema with Natsamrat.\n\n"
    "News reports said he suffered a cardiac arrest in Goa. The loss "
    "prompted tributes from film colleagues and public figures, with "
    "many remembering his versatility and powerful performances.\n\n"
    "This report is based on published coverage by Reuters and the "
    "Associated Press. Source attribution and a link to the original "
    "report appear with the story."
)


def main():
    db = NewsDatabase()
    try:
        ensure_upgrade_schema(db)
        # The original news report URL is the stable idempotency key.
        db.insert(NewsItem(
            source_name="Reuters",
            source_type="editorial_verified",
            title=TITLE,
            url=SOURCE_URL,
            published_at="2026-10-08T06:00:00+05:30",
            summary=SUMMARY,
            category="entertainment",
            image_url=None,
            public_source=True,
            external_id="politicshub-nana-patekar-tribute-20261008",
        ))
        ph = "%s" if db._postgres else "?"
        row = db.conn.execute(
            "SELECT * FROM news_items WHERE normalized_url = " + ph
            + " ORDER BY id DESC LIMIT 1", (SOURCE_URL,)
        ).fetchone()
        if not row:
            raise RuntimeError("Verified tribute item could not be retrieved")
        item_id = int(row["id"])
        status = str(row["instagram_status"] or "")
        fields = dict(
            status="published",
            category="entertainment",
            summary=SUMMARY,
            bot_summary=SUMMARY,
            bot_article=ARTICLE,
            fact_check_status="reviewed",
            fact_check_notes="Reuters and AP reporting verified on 2026-10-08",
            published_at_site=row["published_at_site"] or datetime.now(timezone.utc).isoformat(),
            # Strictly no image on website unless supplied/cleared by source.
            image_url=None,
        )
        if status != "published":
            fields.update(instagram_status="pending", instagram_selected=1,
                          instagram_next_retry_at=None, instagram_error=None)
        db.update(item_id, **fields)
        if status != "published":
            db.set_settings({"instagram_priority_id":str(item_id),
                             "instagram_paused":"false",
                             "instagram_enabled":"true"})
            print(f"Verified Nana Patekar tribute published on site and queued for priority Instagram: {item_id}")
        else:
            print(f"Nana Patekar tribute already published on Instagram: {item_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
