"""Bounded public lookup for phone-published articles between deployments.

An immutable publication commit can be opened immediately; mutable lookups
refresh separately so historical articles don't depend on a bundled archive.
"""
from collections import OrderedDict
from pathlib import Path
import re
import threading
import time

from app.public_delivery import read_json_rows, remote_rows

_states = OrderedDict()
_guard = threading.Lock()


def reviewed_rows(public_folder, revision=None, *, full_reviewed=False):
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
        return []
    ref = revision or 'main'
    key = (ref, full_reviewed)
    with _guard:
        if key not in _states:
            _states[key] = ({'until': 0.0, 'payload': []}, threading.Lock())
        state, lock = _states[key]
        _states.move_to_end(key)
        while len(_states) > 24:
            _states.popitem(last=False)
    local = read_json_rows(Path(public_folder or 'public') / 'mobile-reviewed.json') if not revision else []
    file = 'news-data.json' if revision and not full_reviewed else 'mobile-reviewed.json'
    url = 'https://raw.githubusercontent.com/uunivpt/news-bot/' + ref + '/public/' + file
    if not revision:
        url += '?refresh=' + str(int(time.time() // 15))
    rows = remote_rows(state, lock, local, (url,), ttl=300 if revision else 15,
                       max_bytes=5_000_000, allow_empty=True)
    return [dict(row) for row in rows if isinstance(row, dict)
            and row.get('status') == 'published' and row.get('public_source')
            and row.get('title') and str(row.get('url') or '').startswith('https://')]


def reviewed_article(public_folder, item_id, revision=None):
    found = next((row for row in reviewed_rows(public_folder, revision)
                  if str(row.get('id')) == str(item_id)), None)
    if found is None and revision:
        found = next((row for row in reviewed_rows(public_folder, revision, full_reviewed=True)
                      if str(row.get('id')) == str(item_id)), None)
    return found
