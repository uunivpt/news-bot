"""Bound PostgreSQL connections and waiting requests in each web worker.

Neon's pooled (-pooler) endpoint remains the shared, cross-instance pool. This
small client pool reduces handshakes and puts backpressure on a single worker.
Collectors and migrations deliberately keep their direct connection lifecycle.
"""
import atexit
import os
import threading
import time

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_lock = threading.Lock()
_pools = {}
_failed_until = {}


def _reconnect_failed(key):
    with _lock:
        _failed_until[key] = time.monotonic() + 30


def get_pool(database_url, connect_timeout=3, statement_timeout=5000):
    key = (os.getpid(), database_url, connect_timeout, statement_timeout)
    with _lock:
        if time.monotonic() < _failed_until.get(key, 0):
            from app.database import DatabaseUnavailable
            raise DatabaseUnavailable('Database connection temporarily unavailable')
        pool = _pools.get(key)
        if pool is None:
            kwargs = dict(autocommit=True, row_factory=dict_row,
                          connect_timeout=connect_timeout, prepare_threshold=None,
                          application_name='politicshub-web')
            if statement_timeout:
                kwargs['options'] = f'-c statement_timeout={int(statement_timeout)} -c lock_timeout=2000'
            pool = ConnectionPool(
                database_url, kwargs=kwargs, name='politicshub-web',
                min_size=0, max_size=4, max_waiting=16, timeout=2,
                max_idle=30, max_lifetime=300, reconnect_timeout=5,
                check=ConnectionPool.check_connection, open=False,
                reconnect_failed=lambda pool: _reconnect_failed(key),
            )
            pool.open()
            _pools[key] = pool
        return pool


def close_pools():
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
        _failed_until.clear()
    for pool in pools:
        pool.close()


atexit.register(close_pools)
