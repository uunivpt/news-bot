"""Publicly fetchable, licensed editorial JPG for the verified Musk–Ambani story.
CC BY-SA 4.0 portrait: The Royal Society / Duncan Hull, Wikimedia Commons.
The graphic is an adaptation; attribution and share-alike terms accompany the post.
"""
from flask import Flask, Response
from app.editorial_poster import render_editorial_poster
from pathlib import Path

app = Flask(__name__)

@app.get("/")
def poster():
    row = {
        "id": "elon-musk-ambani-2026-10-09",
        "title": "Musk targets Ambani over Starlink delay",
        "bot_summary": "Musk alleged anti-competitive interference. India denies favouritism, citing mandatory security and regulatory clearances.",
        "source_name": "X / Reuters",
        "category": "India",
        "published_at": "2026-10-09T23:23:00+05:30",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/e/ed/Elon_Musk_Royal_Society.jpg",
        "image_license": "Creative Commons CC BY-SA 4.0",
        "image_credit": "The Royal Society / Duncan Hull via Wikimedia Commons",
    }
    try:
        target = Path("/tmp/elon_musk_starlink_politicshub_20261009.jpg")
        render_editorial_poster(row, output_path=target)
        return Response(target.read_bytes(), mimetype="image/jpeg", headers={"Cache-Control":"public,max-age=1800,s-maxage=86400"})
    except Exception as exc:
        # Return a clean HTTP error rather than an invalid image.
        app.logger.error("Editorial poster render failed: %s", type(exc).__name__)
        return Response("News graphic temporarily unavailable", status=503, mimetype="text/plain")
