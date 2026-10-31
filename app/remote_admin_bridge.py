"""Same-origin HTTPS gateway for PoliticsHub's phone-owned Admin Room.

Only enables if BOTH POLITICSHUB_ADMIN_BRIDGE_URL and
POLITICSHUB_ADMIN_BRIDGE_SECRET are configured on Vercel. The Termux
origin must use the same secret, and must be reached through an HTTPS
outbound tunnel. No PostgreSQL port is published and no public database
or password verifier is moved into Vercel.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from flask import Response, jsonify, request

_SECRET_NAME = "POLITICSHUB_ADMIN_BRIDGE_SECRET"
_URL_NAME = "POLITICSHUB_ADMIN_BRIDGE_URL"
_NOUNCE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
_STORY = re.compile(r"^/api/news/[0-9]+/(?:edit|process|approve|reject|publish)$")
_REVIEW = re.compile(r"^/api/admin/(?:story/[0-9]+|(?:me|login|logout|workspace|stories|activity|settings|training))$")
_REPLAY_LOCK = threading.Lock()
_REPLAY = {}
_MAX_BODY = 1024 * 1024


def is_private_endpoint(path: str) -> bool:
    if path.startswith("/api/admin/"):
        return bool(_REVIEW.fullmatch(path))
    return bool(_STORY.fullmatch(path) or path == "/api/fact-check")


def bridge_config():
    url = os.getenv(_URL_NAME, "").strip()
    secret = os.getenv(_SECRET_NAME, "")
    if not url and not secret:
        return None
    if not url or len(secret) < 32:
        raise ValueError("Remote admin HTTPS origin/secret not fully configured")
    value = urlsplit(url)
    host = (value.hostname or "").lower()
    # URL must be a fixed, externally provisioned tunnel endpoint, not a
    # client-controlled URL, private network, HTTP service or arbitrary port.
    domains = (".trycloudflare.com", ".ts.net", ".politicshub.in")
    if (value.scheme != "https" or not host.endswith(domains) or
        host in {"politicshub.in", "www.politicshub.in"} or
        value.port not in (None, 443) or
        value.username or value.password or value.path not in ("", "/") or
        value.query or value.fragment):
        raise ValueError("Unsafe remote admin tunnel origin")
    return ("https://" + host, secret)


def signature(secret, timestamp: str, nonce: str, method: str, path: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    data = "\n".join((timestamp, nonce, method.upper(), path, digest)).encode()
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


def bridge_headers(secret: str, method: str, path: str, payload: bytes, when=None, nonce=None):
    when = str(int(time.time()) if when is None else when)
    nonce = nonce or secrets.token_urlsafe(25)
    return {
        "X-PH-Bridge-Time": when,
        "X-PH-Bridge-Nonce": nonce,
        "X-PH-Bridge-Signature": signature(secret, when, nonce, method, path, payload),
    }


def verify_phone_bridge(request_obj, secret: str, now=None) -> bool:
    """Authenticate Vercel->Termux requests, including the original payload."""
    timestamp = request_obj.headers.get("X-PH-Bridge-Time", "")
    nonce = request_obj.headers.get("X-PH-Bridge-Nonce", "")
    supplied = request_obj.headers.get("X-PH-Bridge-Signature", "")
    if not (timestamp.isdigit() and _NOUNCE.fullmatch(nonce) and
            re.fullmatch(r"[a-f0-9]{64}", supplied)):
        return False
    now = int(time.time()) if now is None else int(now)
    if abs(now - int(timestamp)) > 75:
        return False
    path = request_obj.full_path.rstrip("?")
    expected = signature(secret, timestamp, nonce, request_obj.method,
                         path, request_obj.get_data(cache=True))
    if not hmac.compare_digest(expected, supplied):
        return False
    with _REPLAY_LOCK:
        for key, expiry in tuple(_REPLAY.items()):
            if expiry < now:
                del _REPLAY[key]
        if nonce in _REPLAY:
            return False
        _REPLAY[nonce] = now + 90
    return True


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def proxy_public_admin():
    """Route ONLY authenticated-admin API paths to the remote phone origin."""
    if not is_private_endpoint(request.path):
        return None
    try:
        config = bridge_config()
    except ValueError:
        return jsonify({"error": "Remote admin bridge configuration incomplete",
                        "code": "admin_bridge_not_ready"}), 503
    if config is None:
        return None  # Existing read-only recovery mode remains safe.
    base_url, secret = config
    if request.method not in {"GET", "POST"}:
        return jsonify({"error": "Unsupported admin method"}), 405
    if request.method == "POST":
        # Cross-site requests can never invoke privileged browser mutations.
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != "https://" + request.host:
            return jsonify({"error": "Cross-origin admin request blocked"}), 403
    payload = request.get_data(cache=True)
    if len(payload) > _MAX_BODY:
        return jsonify({"error": "Admin request too large"}), 413
    path = request.full_path.rstrip("?")
    headers = bridge_headers(secret, request.method, path, payload)
    for field in ("Cookie", "Content-Type", "X-CSRF-Token", "If-Match"):
        value = request.headers.get(field)
        if value:
            headers[field] = value
    # On the phone, CSRF/same-origin checks use the local loopback origin.
    if request.method == "POST":
        headers["Origin"] = "http://127.0.0.1:8765"
    headers["User-Agent"] = "PoliticsHub-Private-Admin-Gateway/1"
    url = base_url + path
    try:
        opener = build_opener(_NoRedirect)
        response = opener.open(Request(url, data=payload if request.method == "POST" else None,
                                       method=request.method, headers=headers), timeout=12)
    except HTTPError as exc:
        response = exc
    except (URLError, TimeoutError, OSError):
        return jsonify({"error": "Phone admin is offline or tunnel unavailable",
                        "code": "phone_admin_offline"}), 503
    try:
        content = response.read(3 * 1024 * 1024 + 1)
        if len(content) > 3 * 1024 * 1024:
            return jsonify({"error": "Admin response too large"}), 502
        result = Response(content, status=response.status)
        result.headers["Content-Type"] = response.headers.get("Content-Type", "application/json")
        for cookie in response.headers.get_all("Set-Cookie", []):
            # Forward only the phone admin session, never any unrelated token.
            if cookie.startswith("politicshub_phone_admin="):
                result.headers.add("Set-Cookie", cookie)
        result.headers["Cache-Control"] = "private, no-store"
        result.headers["Vary"] = "Cookie"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result
    finally:
        response.close()
