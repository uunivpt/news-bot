"""Read-only Meta API authentication checks; never prints access tokens or IDs.

Run before expensive Instagram rendering and publishing. An account-specific
block must be resolved through the official Meta app/account permissions flow.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class AuthResult:
    host: str
    passed: bool
    http_status: int | None
    code: int | None
    subcode: int | None
    reason: str
    trace: str = ""


def _numeric(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reason(code: int | None, message: object) -> str:
    detail = str(message or "").lower()
    if "api access blocked" in detail:
        return "meta_api_access_blocked"
    if code == 190:
        return "invalid_expired_or_revoked_token"
    if code in {10, 200} or (code is not None and 200 <= code < 300):
        return "permission_or_app_access_denied"
    if code in {4, 17, 32, 613}:
        return "rate_limited"
    return "api_error"


def check_endpoint(host: str, token: str, version: str) -> AuthResult:
    """Only reads /me; does not mutate Meta app settings or publish anything."""
    name = "instagram" if host == "graph.instagram.com" else "facebook"
    fields = "id,username" if name == "instagram" else "id,name"
    try:
        response = requests.get(
            f"https://{host}/{version}/me",
            headers={"Authorization": "Bearer " + token},
            params={"fields": fields},
            timeout=20,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
    except requests.RequestException:
        return AuthResult(host, False, None, None, None, "network_error")
    if response.ok and isinstance(body, dict) and body.get("id"):
        return AuthResult(host, True, response.status_code, None, None, "authenticated")
    error = body.get("error") if isinstance(body, dict) else {}
    error = error if isinstance(error, dict) else {}
    code = _numeric(error.get("code"))
    subcode = _numeric(error.get("error_subcode"))
    raw_trace = str(error.get("fbtrace_id") or "")
    trace = raw_trace if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw_trace) else ""
    return AuthResult(host, False, response.status_code, code, subcode, _reason(code, error.get("message")), trace)


def diagnostic_status(token: str, version: str, configured_host: str):
    """Return status and safe results, never returning token or account IDs."""
    if not token:
        return "missing_token", []
    hosts = ("graph.instagram.com", "graph.facebook.com")
    results = [check_endpoint(h, token, version) for h in hosts]
    matches = [r for r in results if r.host == configured_host]
    configured = matches[0] if matches else None
    if configured and configured.passed:
        return "configured_host_working", results
    if any(r.passed for r in results):
        return "different_host_working", results
    return "both_hosts_denied", results


def main() -> int:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    version = os.getenv("META_API_VERSION", "").strip() or "v25.0"
    api_base = os.getenv("META_API_BASE_URL", "").strip() or "https://graph.instagram.com"
    configured_host = re.sub(r"^https?://", "", api_base).split("/", 1)[0].lower()
    if configured_host not in {"graph.instagram.com", "graph.facebook.com"}:
        print("META_AUTH: invalid configured Meta API host. Use an official Meta Graph endpoint.")
        return 2
    if not re.fullmatch(r"v[0-9]{1,2}\\.[0-9]", version):
        print("META_AUTH: invalid Meta API version format.")
        return 2
    status, results = diagnostic_status(token, version, configured_host)
    if status == "missing_token":
        print("META_AUTH: META_ACCESS_TOKEN is missing from GitHub Actions secrets.")
        return 2
    for result in results:
        print(
            f"META_AUTH: endpoint={result.host} http={result.http_status or 'network-failure'} "
            f"code={result.code if result.code is not None else '-'} "
            f"subcode={result.subcode if result.subcode is not None else '-'} "
            f"reason={result.reason}"
            + (f" trace={result.trace}" if result.trace else "")
        )
    if status == "configured_host_working":
        print("META_AUTH: configured host authorized for /me. Media publishing permissions still require validation.")
        return 0
    if status == "different_host_working":
        print("META_AUTH: token authenticates on a different Meta Graph API host.")
        print("META_AUTH: verify whether the token uses Instagram Login or Facebook Login;")
        print("META_AUTH: configure META_API_BASE_URL and the matching authorized Instagram user ID.")
        print("META_AUTH: no alternate publishing account was selected automatically.")
        return 2
    if any(r.reason == "meta_api_access_blocked" for r in results):
        print("META_AUTH: Meta returned API access blocked. Check Meta App Dashboard")
        print("META_AUTH: for app restrictions, feature permissions, access review and account status.")
        print("META_AUTH: a GitHub code change cannot lift Meta's platform restriction.")
    else:
        print("META_AUTH: neither supported Graph host accepted this token.")
        print("META_AUTH: verify token validity, approved permissions and Meta app/account status.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
