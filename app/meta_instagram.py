"""Instagram Reels publishing helper with safe diagnostics."""
from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

import requests


def _cfg():
    token = os.getenv("META_ACCESS_TOKEN", "")
    configured_account = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")
    version = os.getenv("META_API_VERSION", "v25.0")
    host = os.getenv("META_API_BASE_URL", "https://graph.instagram.com").rstrip("/")
    return token, configured_account, version, host


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _raise_meta(r: requests.Response, action: str) -> None:
    if r.ok:
        return
    try:
        detail = r.json()
    except Exception:
        detail = r.text[:1500]
    text = str(detail).replace(os.getenv("META_ACCESS_TOKEN", ""), "[REDACTED]")
    raise RuntimeError(f"Instagram {action} failed ({r.status_code}): {text}")


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


def _container_status(base: str, token: str, container: str) -> dict:
    r = requests.get(
        f"{base}/{container}",
        params={"fields": "id,status_code,status", "access_token": token},
        timeout=30,
    )
    _raise_meta(r, "container status check")
    data = r.json()
    print(f"Instagram container HTTP {r.status_code}: {data}")
    return data


def _video_preflight(video_url: str) -> None:
    """Verify the exact public URL Meta is expected to fetch."""
    try:
        r = requests.get(
            video_url,
            headers={"User-Agent": "news-bot-instagram-publisher/1.0"},
            stream=True,
            allow_redirects=True,
            timeout=45,
        )
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()
        content_length = r.headers.get("content-length", "unknown")
        accept_ranges = r.headers.get("accept-ranges", "unknown")
        content_range = r.headers.get("content-range", "unknown")
        print(
            "Instagram video preflight: "
            f"HTTP={r.status_code} type={content_type} size={content_length} "
            f"accept-ranges={accept_ranges} content-range={content_range} "
            f"final_url={_safe_url(r.url)}"
        )
        r.close()
        if "video/mp4" not in content_type:
            raise RuntimeError(f"Instagram video URL did not return video/mp4; got {content_type!r}")
    except requests.RequestException as exc:
        raise RuntimeError(f"Instagram video URL is not reachable: {exc}") from exc


def publish_reel(video_url: str, caption: str) -> dict:
    token, configured_account, version, host = _cfg()
    if not token:
        raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN.")
    if not video_url.startswith(("https://", "http://")):
        raise ValueError("Instagram requires a publicly reachable video URL.")

    _video_preflight(video_url)
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
    creation_response = r.json()
    container = creation_response.get("id")
    if not container:
        raise RuntimeError(f"Instagram did not return a creation container id: {creation_response}")
    print(f"Instagram media container created: {container}")

    last_status = {}
    for attempt in range(48):
        data = _container_status(base, token, container)
        last_status = data
        print(
            f"Instagram container check {attempt + 1}: "
            f"status_code={data.get('status_code')}, status={data.get('status')}"
        )
        if data.get("status_code") == "FINISHED":
            break
        if data.get("status_code") == "ERROR":
            raise RuntimeError(
                "Instagram media container entered ERROR. "
                f"container={container}; status_response={data}; "
                f"video_url={_safe_url(video_url)}. "
                "No publish request was sent after the container failed."
            )
        time.sleep(5)
    else:
        raise TimeoutError(
            "Instagram media container did not finish in time. "
            f"container={container}; last_status={last_status}"
        )

    p = requests.post(
        f"{base}/{account}/media_publish",
        data={"creation_id": container, "access_token": token},
        timeout=60,
    )
    _raise_meta(p, "media publish")
    result = p.json()
    if isinstance(result, dict):
        result["container_id"] = container
    print(f"Instagram media published successfully: {result}")
    return result
