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
from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

_lock = threading.Lock()
_pools = {}
_failed_until = {}


class WebConnection(Connection):
    """Apply query limits inside transactions, compatible with PgBouncer.

    Neon rejects statement_timeout in the startup packet. Session SET values
    also do not survive transaction pooling, so each web statement sets LOCAL
    limits in the same transaction as its query. Existing caller transactions
    keep their own commit/rollback boundary.
    """
    @classmethod
    def connect(cls, conninfo='', *, statement_timeout_ms=0, **kwargs):
        connection = super().connect(conninfo, **kwargs)
        connection._web_statement_timeout_ms = max(0, int(statement_timeout_ms))
        return connection

    def _set_local_limits(self):
        super().execute(
            "SELECT set_config('statement_timeout', %s, true), "
            "set_config('lock_timeout', '2000', true)",
            (str(self._web_statement_timeout_ms),), prepare=False)

    def execute(self, query, params=None, *, prepare=None, binary=False):
        if not getattr(self, '_web_statement_timeout_ms', 0):
            return super().execute(query, params, prepare=prepare, binary=binary)
        status = self.info.transaction_status
        if status == TransactionStatus.IDLE:
            with self.transaction():
                self._set_local_limits()
                return super().execute(query, params, prepare=prepare, binary=binary)
        if status == TransactionStatus.INTRANS:
            self._set_local_limits()
        return super().execute(query, params, prepare=prepare, binary=binary)


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
                          application_name='politicshub-web',
                          statement_timeout_ms=int(statement_timeout or 0))
            pool = ConnectionPool(
                database_url, kwargs=kwargs, connection_class=WebConnection,
                name='politicshub-web',
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
