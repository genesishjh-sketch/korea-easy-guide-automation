from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_weekly_report


class WeeklyPipelineTests(unittest.TestCase):
    def test_weekly_failure_report_is_written_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(stage3_weekly_report, "ROOT_DIR", Path(tmpdir)), patch(
                "src.pipeline.stage3_weekly_report.WeeklyReporter"
            ) as reporter:
                reporter.return_value.generate.side_effect = RuntimeError("weekly failed")

                with self.assertRaises(RuntimeError):
                    stage3_weekly_report.run("easy_pc_fix_guide")

            report_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-weekly-failure.json"
            self.assertTrue(report_path.exists())
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertIn("weekly failed", payload["error"])


if __name__ == "__main__":
    unittest.main()
