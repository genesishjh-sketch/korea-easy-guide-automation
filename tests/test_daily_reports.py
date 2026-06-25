from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.reporting.daily_reports import read_daily_success_report


class DailyReportTests(unittest.TestCase):
    def test_read_daily_success_migrates_legacy_validate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            legacy_path = report_dir / "easy_pc_fix_guide-daily-success.json"
            legacy_path.write_text(
                json.dumps({"status": "validated", "mode": "validate", "title": "Validate only"}),
                encoding="utf-8",
            )

            result = read_daily_success_report("easy_pc_fix_guide", report_dir)
            validation_path = report_dir / "easy_pc_fix_guide-daily-validation-success.json"
            validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
            legacy_exists = legacy_path.exists()

        self.assertEqual(result["status"], "not_uploaded")
        self.assertIn("daily-validation-success", result["migrated_legacy_validation_report"])
        self.assertFalse(legacy_exists)
        self.assertEqual(validation_payload["status"], "validated")
        self.assertEqual(validation_payload["migrated_from"], str(legacy_path))

    def test_read_daily_success_keeps_publish_report_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_path = report_dir / "easy_pc_fix_guide-daily-success.json"
            report_path.write_text(
                json.dumps({"status": "published", "mode": "publish", "title": "Published"}),
                encoding="utf-8",
            )

            result = read_daily_success_report("easy_pc_fix_guide", report_dir)
            report_exists = report_path.exists()

        self.assertEqual(result["status"], "published")
        self.assertTrue(report_exists)
        self.assertNotIn("migrated_legacy_validation_report", result)


if __name__ == "__main__":
    unittest.main()
