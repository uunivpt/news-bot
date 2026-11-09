"""Pooled web connections must not send unsupported startup parameters."""
import unittest
from unittest.mock import patch

from app import web_database_pool as pool_module


class PooledStartupTests(unittest.TestCase):
    def tearDown(self):
        pool_module.close_pools()

    def test_pooler_gets_transaction_scoped_limits_instead_of_startup_options(self):
        with patch.object(pool_module, 'ConnectionPool') as factory:
            pool_module.get_pool('postgresql://fixture.invalid/example', 3, 5000)
        kwargs = factory.call_args.kwargs
        self.assertNotIn('options', kwargs['kwargs'])
        self.assertEqual(kwargs['connection_class'], pool_module.WebConnection)
        self.assertEqual(kwargs['kwargs']['statement_timeout_ms'], 5000)
        self.assertEqual(kwargs['max_size'], 4)
        self.assertEqual(kwargs['max_waiting'], 16)
        self.assertEqual(kwargs['timeout'], 2)

    def test_custom_timeout_argument_is_not_forwarded_to_libpq(self):
        with patch('psycopg.Connection.connect') as connect:
            connection = pool_module.WebConnection.connect(
                'postgresql://fixture.invalid/example', statement_timeout_ms=50,
                autocommit=True)
        self.assertNotIn('statement_timeout_ms', connect.call_args.kwargs)
        self.assertNotIn('options', connect.call_args.kwargs)
        self.assertEqual(connection._web_statement_timeout_ms, 50)
