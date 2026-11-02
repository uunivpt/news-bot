import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import termux_admin_update as updater

REF = 'b' * 40


class PhoneUpdateTests(unittest.TestCase):
    def test_branch_or_repository_mismatch_stops_without_source_changes(self):
        with patch.object(updater, 'git', return_value='feature'):
            with self.assertRaisesRegex(RuntimeError, 'main'):
                updater.validate_checkout(Path('/tmp/phone'))
        with patch.object(updater, 'git', side_effect=['main', 'https://github.com/else/other.git']):
            with self.assertRaisesRegex(RuntimeError, 'repository'):
                updater.validate_checkout(Path('/tmp/phone'))

    def test_requires_immutable_revision_before_running_git(self):
        with patch.object(updater, 'git') as git:
            with self.assertRaises(ValueError): updater.apply_release('/tmp/phone', 'main')
        git.assert_not_called()

    def test_backups_precede_stash_and_fast_forward_and_restart_preserves_owner(self):
        operations = []
        def git(directory, *args, **kwargs):
            operations.append(('git', args))
            if args[0] == 'rev-parse': return REF
            if args[0] == 'status': return ' M app/database.py'
            if args[0] == 'show': return 'print("synthetic checker")'
            if args[0] == 'config': return 'true'
            return ''
        def run(command, **kwargs):
            operations.append(('run', command))
            return MagicMock(returncode=0)
        with patch.object(updater, 'validate_checkout'), patch.object(updater, 'git', side_effect=git), \
             patch.object(updater.subprocess, 'run', side_effect=run):
            self.assertEqual(updater.apply_release('/tmp/phone', REF, True), 0)
        backup = next(i for i, x in enumerate(operations) if x[0]=='run' and '--backup' in x[1])
        stash = next(i for i, x in enumerate(operations) if x[0]=='git' and x[1][0]=='stash')
        merge = next(i for i, x in enumerate(operations) if x[0]=='git' and x[1][0]=='merge')
        self.assertLess(backup, stash); self.assertLess(stash, merge)
        self.assertIn('--ff-only', operations[merge][1])
        self.assertTrue(any(x[0]=='git' and x[1][:2]==('sparse-checkout','add') for x in operations))
        self.assertIn('--restart', operations[-1][1])
        self.assertNotIn('--reset-owner', str(operations))
        self.assertNotIn('--hard', str(operations))

    def test_failed_backup_never_stashes_or_updates_source(self):
        import subprocess
        def git(directory, *args, **kwargs):
            if args[0] == 'rev-parse': return REF
            if args[0] == 'status': return ' M app/database.py'
            return ''
        with patch.object(updater, 'validate_checkout'), patch.object(updater, 'git', side_effect=git) as commands, \
             patch.object(updater.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'check')):
            with self.assertRaises(subprocess.CalledProcessError): updater.apply_release('/tmp/phone', REF, True)
        self.assertFalse(any(call.args[1] in ('merge','stash') for call in commands.call_args_list))
