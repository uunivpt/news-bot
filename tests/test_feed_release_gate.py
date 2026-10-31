from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.feed_release_gate import decide_release, prepare_release


NOW = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)


def state(channel, committed):
    return {"version": 1, "channel": channel, "last_commit_at": committed.isoformat()}


class FeedReleaseDecisionTests(unittest.TestCase):
    def test_unchanged_feed_never_opens_a_deployment(self):
        self.assertFalse(decide_release("news", False, None, NOW).publish)

    def test_cooldown_has_an_exact_hour_boundary(self):
        previous = state("news", NOW)
        self.assertFalse(decide_release("news", True, previous, NOW + timedelta(minutes=59, seconds=59)).publish)
        self.assertTrue(decide_release("news", True, previous, NOW + timedelta(hours=1)).publish)

    def test_both_english_workflows_share_one_gate_and_hindi_is_independent(self):
        previous = state("news", NOW)
        self.assertFalse(decide_release("news", True, previous, NOW + timedelta(minutes=30)).publish)
        self.assertTrue(decide_release("hindi", True, None, NOW + timedelta(minutes=30)).publish)

    def test_repeated_collector_and_recovery_runs_cap_data_commits_at_48_per_day(self):
        states = {"news": None, "hindi": None}
        counts = {"news": 0, "hindi": 0}
        for minute in range(24 * 60):
            at = NOW + timedelta(minutes=minute)
            channels = []
            if minute % 30 == 0:
                channels.append("news")
            if minute % 180 == 0:
                channels.append("news")  # Recovery and collector can both run.
            if minute % 60 == 0:
                channels.append("hindi")
            for channel in channels:
                if decide_release(channel, True, states[channel], at).publish:
                    counts[channel] += 1
                    states[channel] = state(channel, at)
        self.assertEqual(counts, {"news": 24, "hindi": 24})

    def test_corrupt_mismatched_and_future_state_cannot_reset_the_budget(self):
        invalid = [[], {}, {"version": 2, "channel": "news"}, state("hindi", NOW),
                   {"version": 1, "channel": "news", "last_commit_at": "bad"},
                   {"version": 1, "channel": "news", "last_commit_at": "2026-10-31T06:00:00"},
                   state("news", NOW + timedelta(hours=1))]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decide_release("news", True, value, NOW)


class FeedReleaseRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Feed gate fixture")
        self.git("config", "user.email", "fixture@example.org")
        (self.root / "public").mkdir()
        (self.root / "public/news-data.json").write_text("[]\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial fixture")
        self.path = self.root / ".github/feed-release-state/news.json"

    def git(self, *arguments):
        subprocess.run(["git", *arguments], cwd=self.root, check=True, capture_output=True)

    def change(self):
        (self.root / "public/news-data.json").write_text('[{"id": 1}]\n')

    def test_no_change_and_dry_run_never_create_release_state(self):
        self.assertFalse(prepare_release("news", self.root, NOW).publish)
        self.assertFalse(self.path.exists())
        self.change()
        self.assertTrue(prepare_release("news", self.root, NOW, dry_run=True).publish)
        self.assertFalse(self.path.exists())

    def test_real_change_records_state_and_holds_following_changes(self):
        self.change()
        self.assertTrue(prepare_release("news", self.root, NOW).publish)
        expected = self.path.read_text()
        self.assertEqual(json.loads(expected)["last_commit_at"], NOW.isoformat())
        self.assertFalse(prepare_release("news", self.root, NOW + timedelta(minutes=30)).publish)
        self.assertEqual(self.path.read_text(), expected)

    def test_staged_feed_changes_are_still_detected(self):
        self.change()
        self.git("add", "public/news-data.json")
        self.assertTrue(prepare_release("news", self.root, NOW).publish)

    def test_untracked_feed_is_detected_and_unrelated_code_is_ignored(self):
        (self.root / "readme.txt").write_text("A code-only change")
        self.assertFalse(prepare_release("news", self.root, NOW).publish)
        (self.root / "public/hindi-news.json").write_text('[{"id": 2}]\n')
        self.assertTrue(prepare_release("hindi", self.root, NOW).publish)

    def test_cli_writes_the_step_output_that_controls_the_publish_step(self):
        self.change()
        script = Path(__file__).resolve().parents[1] / "scripts/feed_release_gate.py"
        output = self.root / "step-output"
        summary = self.root / "step-summary"
        environment = dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary))
        command = [sys.executable, str(script), "--channel", "news"]
        subprocess.run(command + ["--dry-run"], cwd=self.root, env=environment, check=True, capture_output=True)
        self.assertFalse(output.exists())
        subprocess.run(command, cwd=self.root, env=environment, check=True, capture_output=True)
        self.assertEqual(output.read_text(), "publish=true\n")
        self.assertTrue(self.path.exists())
        subprocess.run(command, cwd=self.root, env=environment, check=True, capture_output=True)
        self.assertEqual(output.read_text(), "publish=true\npublish=false\n")
        self.assertIn("next eligible", summary.read_text())


if __name__ == "__main__":
    unittest.main()
