"""Official Meta Instagram API publishing for Reels.

Supports the Instagram API with Instagram Login (graph.instagram.com) by default.
Set META_API_BASE_URL if a different approved Graph API host is required.
"""
from __future__ import annotations
import os, time
import requests


def _cfg():
    token = os.getenv("META_ACCESS_TOKEN", "")
    account = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")
    version = os.getenv("META_API_VERSION", "v25.0")
    host = os.getenv("META_API_BASE_URL", "https://graph.instagram.com").rstrip("/")
    return token, account, version, host


def _raise_meta(r: requests.Response, action: str) -> None:
    if r.ok:
        return
    try:
        detail = r.json()
    except Exception:
        detail = r.text[:1000]
    raise RuntimeError(f"Instagram {action} failed ({r.status_code}): {detail}")


def publish_reel(video_url: str, caption: str) -> dict:
    token, account, version, host = _cfg()
    if not token or not account:
        raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN and META_INSTAGRAM_ACCOUNT_ID.")
    if not video_url.startswith(("https://", "http://")):
        raise ValueError("Instagram requires a publicly reachable video URL.")

    base = f"{host}/{version}"
    r = requests.post(
        f"{base}/{account}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token,
        },
        timeout=60,
    )
    _raise_meta(r, "media container creation")
    container = r.json().get("id")
    if not container:
        raise RuntimeError(f"Instagram did not return a creation container id: {r.json()}")

    for _ in range(36):
        s = requests.get(
            f"{base}/{container}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        _raise_meta(s, "container status check")
        data = s.json()
        if data.get("status_code") == "FINISHED":
            break
        if data.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram container failed: {data}")
        time.sleep(5)
    else:
        raise TimeoutError("Instagram media container did not finish in time")

    p = requests.post(
        f"{base}/{account}/media_publish",
        data={"creation_id": container, "access_token": token},
        timeout=60,
    )
    _raise_meta(p, "media publish")
    return p.json()
