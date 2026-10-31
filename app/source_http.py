"""Bounded HTTP reads for untrusted news links and configured source feeds.

Keep the runtime's proxy and CA configuration. Validate every redirect before
requesting it; never automatically follow a link into private address space.
"""
from dataclasses import dataclass
from ipaddress import ip_address
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests


class UnsafeSourceURL(ValueError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    url: str
    content: bytes
    content_type: str


def _public_address(value):
    address = ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not getattr(address, "is_site_local", False))


def public_http_url(value, allowed_hosts=None):
    """Syntactic/public-host check without DNS or network requests."""
    try:
        value = str(value or "").strip()
        if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value:
            return False
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None:
            return False
        if parts.port not in {None, 80 if parts.scheme == "http" else 443}:
            return False
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if allowed_hosts is not None:
            allowed = [str(item).lower().rstrip(".") for item in allowed_hosts if item]
            if not any(host == item or host.endswith("." + item) for item in allowed):
                return False
        try:
            return _public_address(host)
        except ValueError:
            return ("." in host and bool(re.fullmatch(r"[a-z0-9.-]+", host))
                    and not host.endswith((".localhost", ".local", ".localdomain", ".internal", ".invalid", ".test")))
    except (TypeError, ValueError, UnicodeError):
        return False


def _validate_destination(url, allowed_hosts):
    if not public_http_url(url, allowed_hosts):
        raise UnsafeSourceURL("Source URL must identify a permitted public HTTP(S) host")
    parts = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not _public_address(item[4][0]) for item in addresses):
            raise UnsafeSourceURL("Source hostname resolves to a non-public address")
    except (OSError, ValueError) as exc:
        if isinstance(exc, UnsafeSourceURL):
            raise
        raise UnsafeSourceURL("Source hostname could not be validated") from exc


def fetch_source(url, *, headers=None, timeout=12, max_bytes=2_000_000, allowed_hosts=None):
    deadline = time.monotonic() + min(max(float(timeout), 1), 30)
    current = str(url or "").strip()
    visited = set()
    for hop in range(5):
        _validate_destination(current, allowed_hosts)
        if current in visited:
            raise UnsafeSourceURL("Source redirect loop")
        visited.add(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Source request deadline exceeded")
        response = requests.get(current, headers=headers, timeout=remaining, stream=True, allow_redirects=False)
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location or hop == 4:
                    raise UnsafeSourceURL("Source redirect limit exceeded or location missing")
                target = urljoin(current, location)
                if urlsplit(current).scheme == "https" and urlsplit(target).scheme != "https":
                    raise UnsafeSourceURL("Source redirect must retain HTTPS")
                current = target
                continue
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Source returned an unexpected response status")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > max_bytes:
                raise ValueError("Source response exceeds the size limit")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if time.monotonic() > deadline:
                    raise requests.Timeout("Source request deadline exceeded")
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Source response exceeds the size limit")
                chunks.append(chunk)
            return SourceDocument(current, b"".join(chunks), response.headers.get("Content-Type", "").lower())
        finally:
            response.close()
    raise UnsafeSourceURL("Source redirect limit exceeded")
