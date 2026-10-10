"""Instagram Reels publishing helper with robust account resolution and diagnostics."""
from __future__ import annotations
import os, time
from functools import lru_cache
from urllib.parse import urlsplit
import requests

def _cfg():
    token=os.getenv("META_ACCESS_TOKEN","").strip(); account=os.getenv("META_INSTAGRAM_ACCOUNT_ID","").strip(); version=os.getenv("META_API_VERSION","").strip() or "v25.0"; host=(os.getenv("META_API_BASE_URL","").strip() or "https://graph.instagram.com").rstrip("/")
    return token,account,version,host

def _safe_url(url):
    parts=urlsplit(url); return f"{parts.scheme}://{parts.netloc}{parts.path}"

class InstagramAccessBlockedError(RuntimeError):
    """A Meta-side API access denial that needs authorization/permissions review."""


class InstagramRateLimitError(RuntimeError):
    def __init__(self, message: str, container_id: str | None = None):
        super().__init__(message)
        self.container_id = container_id

def _raise_meta(r,action):
    if r.ok:return
    try: detail=r.json()
    except Exception: detail=r.text[:2000]
    token=os.getenv("META_ACCESS_TOKEN",""); text=str(detail).replace(token,"[REDACTED]")
    detail_text=str(detail)
    error=detail.get("error") if isinstance(detail,dict) else None
    error=error if isinstance(error,dict) else {}
    if str(error.get("code"))=="200" and "api access blocked" in str(error.get("message") or "").lower():
        trace=str(error.get("fbtrace_id") or "")
        trace=trace if all(ch.isalnum() or ch in "_-" for ch in trace) and len(trace)<=80 else ""
        raise InstagramAccessBlockedError(
            f"Instagram {action}: Meta API access blocked (OAuthException code 200). "
            "Check developer app restrictions, permissions and approved login method."
            + (f" Meta trace: {trace}" if trace else "")
        )
    if r.status_code==429 or '"code": 4' in detail_text or "'code': 4" in detail_text or '"code": 9' in detail_text or "'code': 9" in detail_text or "Rate Limit Exceeded" in detail_text or "Application request limit reached" in detail_text or "Media Publish Limit Exceeded" in detail_text or "maximum number of posts" in detail_text:
        raise InstagramRateLimitError(f"Instagram {action} rate limit reached; retry later.")
    raise RuntimeError(f"Instagram {action} failed ({r.status_code}): {text}")

@lru_cache(maxsize=8)
def _resolve_instagram_user(base,token,configured_account):
    # The ID must belong to the Instagram user represented by this access token.
    if urlsplit(base).hostname == "graph.instagram.com":
        resolved = _resolve_from_token(base,token)
        if configured_account and configured_account != resolved:
            print("Configured Instagram ID is stale; using the token-resolved Instagram account.")
        return resolved
    if configured_account:
        print(f"Using configured Instagram account ID: {configured_account}")
        return configured_account
    return _resolve_from_token(base,token)

def _resolve_from_token(base,token):
    r=requests.get(f"{base}/me",params={"fields":"id,username","access_token":token},timeout=30)
    _raise_meta(r,"token/account lookup")
    data=r.json(); resolved=str(data.get("id","")).strip(); username=str(data.get("username","")).strip()
    if not resolved: raise RuntimeError(f"Instagram token/account lookup returned no user id: {data}")
    print(f"Instagram account resolved: @{username}" if username else f"Instagram user ID resolved: {resolved}")
    return resolved

def _is_missing_object_error(response):
    if response.status_code != 400:
        return False
    try:
        detail=response.json()
    except Exception:
        return False
    error=detail.get("error") if isinstance(detail,dict) else None
    return isinstance(error,dict) and str(error.get("code")) == "100" and str(error.get("error_subcode")) == "33"

def _container_status(base,token,container):
    r=requests.get(
        f"{base}/{container}",
        params={"fields":"id,status_code,status","access_token":token},
        timeout=30,
    )
    _raise_meta(r,"container status check")
    try:
        data=r.json()
    except ValueError:
        raise RuntimeError(
            f"Instagram container status returned non-JSON response "
            f"(HTTP {r.status_code}): {r.text[:2000]}"
        )
    # Keep the complete status payload in Actions logs. Meta's ERROR response
    # can include diagnostic fields depending on API version; never discard them.
    print(f"Instagram container status payload: {data}")
    return data

def _video_preflight(video_url):
    try:
        r=requests.get(video_url,headers={"User-Agent":"news-bot-instagram-publisher/1.0"},stream=True,allow_redirects=True,timeout=45); r.raise_for_status()
        ct=(r.headers.get("content-type") or "").lower(); size=r.headers.get("content-length","unknown")
        print(f"Instagram video preflight: HTTP={r.status_code} type={ct} size={size} final_url={_safe_url(r.url)}")
        r.close()
        if "video/mp4" not in ct: raise RuntimeError(f"Instagram video URL did not return video/mp4; got {ct!r}")
    except requests.RequestException as exc: raise RuntimeError(f"Instagram video URL is not reachable: {exc}") from exc

def publish_reel(video_url,caption):
    token,configured_account,version,host=_cfg()
    if not token: raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN.")
    if not video_url.startswith(("https://","http://")): raise ValueError("Instagram requires a publicly reachable video URL.")
    _video_preflight(video_url); base=f"{host}/{version}"; account=_resolve_instagram_user(base,token,configured_account)
    media_data={"media_type":"REELS","video_url":video_url,"caption":caption,"thumb_offset":"8200","access_token":token}
    r=requests.post(f"{base}/{account}/media",data=media_data,timeout=60)
    # Recover once when a stale/wrong configured account ID is rejected by Meta.
    if configured_account and _is_missing_object_error(r):
        resolved=_resolve_from_token(base,token)
        if resolved != configured_account:
            print(f"Configured Instagram account ID is invalid for this token; retrying with token-resolved ID {resolved}")
            account=resolved
            r=requests.post(f"{base}/{account}/media",data=media_data,timeout=60)
    _raise_meta(r,"media container creation")
    creation=r.json(); container=creation.get("id")
    if not container: raise RuntimeError(f"Instagram did not return a creation container id: {creation}")
    print(f"Instagram media container created: {container}")
    last={}
    for attempt in range(24):
        data=_container_status(base,token,container); last=data; code=str(data.get("status_code") or "").upper(); status=str(data.get("status") or "").upper()
        print(f"Instagram container check {attempt+1}: status_code={code}, status={status}")
        if code in {"FINISHED","PUBLISHED"} or status in {"FINISHED","PUBLISHED"}: break
        if code=="ERROR" or status=="ERROR": raise RuntimeError(f"Instagram media container ERROR: container={container}; status={data}")
        time.sleep(min(15, 8 + attempt))
    else: raise TimeoutError(f"Instagram media container timeout: container={container}; last_status={last}")
    return _publish_existing_container(base, token, account, container)

def _publish_existing_container(base, token, account, container):
    """Publish an already-created container without rendering/uploading again."""
    p=requests.post(
        f"{base}/{account}/media_publish",
        data={"creation_id":container,"access_token":token},
        timeout=60,
    )
    try:
        _raise_meta(p,"media publish")
    except InstagramRateLimitError as exc:
        raise InstagramRateLimitError(str(exc), container_id=container) from exc
    result=p.json()
    if isinstance(result,dict): result["container_id"]=container
    print(f"Instagram media published successfully: {result}")
    return result

def publish_existing_container(container):
    """Retry media_publish for a finished container after a transient publish-limit error."""
    token,configured_account,version,host=_cfg()
    if not token: raise RuntimeError("Instagram is not configured. Add META_ACCESS_TOKEN.")
    if not container: raise ValueError("Instagram container id is required")
    base=f"{host}/{version}"
    account=_resolve_instagram_user(base,token,configured_account)
    last={}
    for attempt in range(12):
        data=_container_status(base,token,container); last=data
        code=str(data.get("status_code") or "").upper(); status=str(data.get("status") or "").upper()
        print(f"Instagram existing-container check {attempt+1}: status_code={code}, status={status}")
        if code in {"FINISHED","PUBLISHED"} or status in {"FINISHED","PUBLISHED"}:
            return _publish_existing_container(base,token,account,container)
        if code=="ERROR" or status=="ERROR":
            raise RuntimeError(f"Instagram media container ERROR: container={container}; status={data}")
        time.sleep(min(15,8+attempt))
    raise TimeoutError(f"Instagram existing container timeout: container={container}; last_status={last}")

def publish_photo(image_url: str, caption: str) -> dict:
    """Publish a single 4:5 editorial photo on a connected Instagram account."""
    token,configured,version,host=_cfg()
    if not token:
        raise RuntimeError("Instagram access token is missing")
    if not image_url.startswith("https://"):
        raise ValueError("Instagram photo must have an HTTPS URL")
    base=f"{host}/{version}"
    account=_resolve_instagram_user(base,token,configured)
    response=requests.post(
        f"{base}/{account}/media",
        data={"image_url":image_url,"caption":caption,"access_token":token},
        timeout=60,
    )
    _raise_meta(response,"editorial image container creation")
    container=str(response.json().get("id") or "")
    if not container:
        raise RuntimeError("Meta returned no Instagram image container id")
    for attempt in range(12):
        result=_container_status(base,token,container)
        status=str(result.get("status_code") or "").upper()
        if status in {"FINISHED","PUBLISHED"}:
            break
        if status=="ERROR":
            raise RuntimeError("Meta rejected editorial image container")
        time.sleep(min(8+attempt,15))
    else:
        raise TimeoutError("Instagram photo container processing timed out")
    return _publish_existing_container(base,token,account,container)
