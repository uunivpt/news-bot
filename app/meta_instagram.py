"""Instagram Reels publishing helper."""
from __future__ import annotations
import os, time
import requests


def _cfg():
    token = os.getenv("META_ACCESS_TOKEN", "")
    configured_account = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")
    version = os.getenv("META_API_VERSION", "v25.0")
    host = os.getenv("META_API_BASE_URL", "https://graph.instagram.com").rstrip("/")
    return token, configured_account, version, host


def _raise_meta(r: requests.Response, action: str) -> None:
    if r.ok:
        return
    try:
        detail = r.json()
    except Exception:
        detail = r.text[:1000]
    raise RuntimeError(f"Instagram {action} failed ({r.status_code}): {detail}")


def _resolve_instagram_user(base: str, token: str, configured_account: str) -> str:
    r = requests.get(
        f"{base}/me",
        params={"fields": "id,username", "access_token": token},
        timeout=30,
    )
    _raise_meta(r, "token/account lookup")
    data = r.json()
    resolved = str(data.get("id", "")).strip()
    username = str(data.get("username", "")).strip()
    if not resolved:
        raise RuntimeError(f"Instagram token/account lookup returned no user id: {data}")
    if configured_account and configured_account != resolved:
        print("Instagram account ID mismatch: using the Instagram user ID returned by this token.")
    if username:
        print(f"Instagram account resolved: @{username}")
    print(f"Instagram user ID resolved successfully: {resolved}")
    return resolved


def publish_reel(video_url: str, caption: str) -> dict:
    token, configured_account, version, host = _cfg()
    if not token:
        raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN.")
    if not video_url.startswith(("https://", "http://")):
        raise ValueError("Instagram requires a publicly reachable video URL.")

    base = f"{host}/{version}"
    account = _resolve_instagram_user(base, token, configured_account)

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
    print(f"Instagram media container created: {container}")

    # Ask Meta for the detailed processing error fields. The old code only
    # requested status_code/status, which hid the actual reason for ERROR.
    for attempt in range(36):
        s = requests.get(
            f"{base}/{container}",
            params={
                "fields": "id,status_code,status,error_message,error_type,error_subcode",
                "access_token": token,
            },
            timeout=30,
        )
        _raise_meta(s, "container status check")
        data = s.json()
        print(f"Instagram container check {attempt + 1}: {data}")
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
