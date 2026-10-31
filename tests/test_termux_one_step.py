import unittest
from unittest.mock import patch

from scripts.termux_one_step import COMBINED, ORIGINAL, configure_scheduler
from scripts import mobile_pipeline_cycle


class OneStepSchedulerTests(unittest.TestCase):
    def test_only_target_sync_is_replaced(self):
        source = 'repo = home / "politicshub-live-upload"\n' + ORIGINAL + '\nother_line=1\n'
        updated = configure_scheduler(source)
        self.assertIn(COMBINED, updated)
        self.assertNotIn(ORIGINAL, updated)
        self.assertIn("other_line=1", updated)

    def test_repeated_install_is_idempotent(self):
        source = 'repo = home / "politicshub-live-upload"\n' + ORIGINAL
        updated = configure_scheduler(source)
        self.assertEqual(configure_scheduler(updated), updated)

    def test_unknown_scheduler_is_not_modified(self):
        with self.assertRaises(ValueError):
            configure_scheduler("print('custom scheduler')")


class PipelineCycleTests(unittest.TestCase):
    @patch.object(mobile_pipeline_cycle, "run_local", return_value=True)
    @patch.object(mobile_pipeline_cycle.STATE.__class__, "read_text",
                  side_effect=FileNotFoundError)
    @patch.object(mobile_pipeline_cycle.STATE.__class__, "write_text")
    @patch("time.time", return_value=1800000000)
    def test_draft_preparation_then_approved_only_sync(self, clock, write, read, run):
        with patch.object(mobile_pipeline_cycle, "STATE",
                          mobile_pipeline_cycle.STATE):
            with patch.object(mobile_pipeline_cycle.STATE.__class__, "replace"):
                result = mobile_pipeline_cycle.cycle()
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("mobile_prepare_drafts.py", run.call_args_list[0].args[0][1])
        self.assertIn("mobile_sync_upload.py", run.call_args_list[1].args[0][1])
        self.assertIn("--push", run.call_args_list[1].args[0])

    @patch.object(mobile_pipeline_cycle, "run_local", return_value=False)
    @patch.object(mobile_pipeline_cycle.STATE.__class__, "read_text", return_value="1800000000")
    @patch("time.time", return_value=1800000001)
    def test_sync_error_fails_closed(self, clock, read, run):
        self.assertEqual(mobile_pipeline_cycle.cycle(), 1)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
