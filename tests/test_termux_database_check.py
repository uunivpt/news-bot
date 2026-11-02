import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.termux_database_check import backup_database, connect_args, read_health, verify_persistence


class TermuxPersistenceTests(unittest.TestCase):
    def test_credentials_are_explicitly_phone_local(self):
        args = connect_args()
        self.assertEqual(args['host'], '127.0.0.1')
        self.assertEqual(args['dbname'], 'politicshub')
        self.assertNotIn('password', args)
        self.assertEqual(connect_args(True, 'private')['password'], 'private')

    def test_probe_commits_then_reconnects_and_cleans_only_its_marker(self):
        calls = []
        stored = {}
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): calls.append('transaction closed')
            def execute(self, sql, values=()):
                calls.append(sql)
                if sql.startswith('INSERT'): stored['id'] = values[0]
                if sql.startswith('SELECT'): return MagicMock(fetchone=lambda: (stored['id'],))
                if sql.startswith('DELETE'): stored.pop('id')
        connect = MagicMock(side_effect=lambda **kwargs: Connection())
        self.assertTrue(verify_persistence(connect, connect_args(True, 'secret')))
        self.assertEqual(connect.call_count, 3)
        self.assertEqual(stored, {})
        self.assertLess(calls.index('transaction closed'), next(i for i,s in enumerate(calls) if s.startswith('SELECT')))
        self.assertTrue(all('news_items' not in sql and 'admin_users' not in sql for sql in calls))

    def test_failed_readback_is_reported_and_marker_cleanup_attempted(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        connect = MagicMock()
        connect.return_value.__enter__.return_value = conn
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            verify_persistence(connect, connect_args(True, 'secret'))
        self.assertTrue(any(x.args[0].startswith('DELETE') for x in conn.execute.call_args_list))

    def test_failed_dump_never_becomes_a_successful_backup(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'pg_dump')):
            with self.assertRaises(subprocess.CalledProcessError):
                backup_database('private', tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_backup_is_private_checked_and_renamed_atomically(self):
        def run(cmd, **kwargs):
            if cmd[0]=='pg_dump': kwargs['stdout'].write(b'PGDMP fixture')
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.run', side_effect=run) as execute:
            result = backup_database('never-printed-password', tmp)
            self.assertEqual(result.read_bytes(), b'PGDMP fixture')
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)
            self.assertEqual(execute.call_args_list[1].args[0][:2], ['pg_restore','--list'])
            self.assertNotIn('never-printed-password', execute.call_args_list[0].args[0])
            self.assertNotIn('PGPASSWORD', os.environ)
