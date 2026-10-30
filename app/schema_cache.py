"""Run idempotent component schema setup once per database and process."""
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
import threading

_ready = OrderedDict()
_lock = threading.RLock()


@contextmanager
def schema_once(database, namespace):
    identity = getattr(database, 'database_url', None)
    if not isinstance(identity, str) or not identity:
        path = getattr(database, 'path', None)
        if isinstance(path, (str, Path)):
            file = Path(path)
            identity = ('sqlite', str(file.resolve()), file.stat().st_ino)
        else:
            # Lightweight test adapters and in-memory databases retain their
            # existing setup semantics; never identify them by a reused object ID.
            yield True
            return
    key = (identity, namespace)
    with _lock:
        if key in _ready:
            _ready.move_to_end(key)
            yield False
            return
        yield True  # Exceptions leave the namespace unmarked so it can recover.
        _ready[key] = True
        while len(_ready) > 256:
            _ready.popitem(last=False)
