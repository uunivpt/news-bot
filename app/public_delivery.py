"""Small, bounded primitives for public delivery; no user-specific response cache."""
from collections import OrderedDict
from functools import lru_cache
import json
from pathlib import Path
import threading
import time


class WindowLimiter:
    """Thread-safe per-process abuse guard with a strict memory bound.

    The CDN/WAF must enforce distributed limits across instances. This guard is
    deliberately not presented as a distributed quota or a billing boundary.
    """

    def __init__(self, capacity=8192, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock
        self.buckets = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, limit, window):
        now = self.clock()
        with self.lock:
            bucket = self.buckets.get(key)
            if bucket is None or now - bucket[0] >= window:
                bucket = [now, 0]
                self.buckets[key] = bucket
            self.buckets.move_to_end(key)
            while len(self.buckets) > self.capacity:
                self.buckets.popitem(last=False)
            if bucket[1] >= limit:
                return False
            bucket[1] += 1
            return True

    def clear(self):
        with self.lock:
            self.buckets.clear()

    def __len__(self):
        with self.lock:
            return len(self.buckets)


@lru_cache(maxsize=8)
def _json_at_version(path, modified_ns, size):
    # Version the key by stat, so local snapshot replacement is visible without
    # reparsing a multi-megabyte file for every request.
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, list) else []


def read_json_rows(path):
    try:
        file = Path(path)
        stat = file.stat()
        return _json_at_version(str(file.resolve()), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return []


def remote_rows(cache, lock, fallback, urls, *, ttl, max_bytes, allow_empty=False):
    """One upstream refresh per process; concurrent readers reuse good data."""
    now = time.monotonic()
    if now < cache["until"]:
        return cache["payload"]
    stale = cache["payload"] or fallback
    acquired = lock.acquire(blocking=False)
    if not acquired:
        if stale:
            return stale
        # Cold followers share the first request's result, with a bounded wait.
        acquired = lock.acquire(timeout=8)
        if not acquired:
            return stale
    try:
        if time.monotonic() < cache["until"]:
            return cache["payload"]
        import requests
        for url in urls:
            try:
                response = requests.get(url, timeout=(2, 5), headers={"Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > max_bytes:
                    continue
                incoming = response.json()
                if (isinstance(incoming, list) and (incoming or allow_empty)
                        and all(isinstance(row, dict) and row.get("title") for row in incoming)):
                    cache.update(until=time.monotonic() + ttl, payload=incoming)
                    return incoming
            except (requests.RequestException, ValueError, RuntimeError):
                continue
        # Back off failed upstreams; retain the last good feed for availability.
        cache.update(until=time.monotonic() + 30, payload=stale)
        return stale
    finally:
        lock.release()
