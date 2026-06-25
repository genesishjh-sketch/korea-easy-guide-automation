from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_weekly_report


class WeeklyPipelineTests(unittest.TestCase):
    def test_weekly_success_removes_stale_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "reports"
            report_dir.mkdir()
            stale_failure_path = report_dir / "easy_pc_fix_guide-weekly-failure.json"
            stale_failure_path.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            weekly_markdown_path = root / "weekly.md"
            weekly_markdown_path.write_text("# Weekly report", encoding="utf-8")

            with patch.object(stage3_weekly_report, "ROOT_DIR", root), patch(
                "src.pipeline.stage3_weekly_report.WeeklyReporter"
            ) as reporter, patch("src.pipeline.stage3_weekly_report.NotificationClient") as notifier:
                reporter.return_value.generate.return_value = weekly_markdown_path

                result_path = stage3_weekly_report.run("easy_pc_fix_guide")

                notifier.return_value.send_required.assert_called_once_with("# Weekly report")
                stale_failure_removed = not stale_failure_path.exists()

        self.assertEqual(result_path, weekly_markdown_path)
        self.assertTrue(stale_failure_removed)

    def test_weekly_failure_report_is_written_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(stage3_weekly_report, "ROOT_DIR", Path(tmpdir)), patch(
                "src.pipeline.stage3_weekly_report.WeeklyReporter"
            ) as reporter, patch("src.pipeline.stage3_weekly_report.NotificationClient") as notifier:
                reporter.return_value.generate.side_effect = RuntimeError("weekly failed")

                with self.assertRaises(RuntimeError):
                    stage3_weekly_report.run("easy_pc_fix_guide")

            report_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-weekly-failure.json"
            self.assertTrue(report_path.exists())
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertIn("weekly failed", payload["error"])
        notifier.return_value.send_required.assert_called_once()
        message = notifier.return_value.send_required.call_args.args[0]
        self.assertIn("[Posting Bot] 주간 리포트 실패", message)
        self.assertIn("weekly failed", message)
        self.assertIn("Easy PC Fix Weekly Report", message)

    def test_weekly_notification_failure_is_reported_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            weekly_markdown_path = root / "weekly.md"
            weekly_markdown_path.write_text("# Weekly report", encoding="utf-8")

            with patch.object(stage3_weekly_report, "ROOT_DIR", root), patch(
                "src.pipeline.stage3_weekly_report.WeeklyReporter"
            ) as reporter, patch("src.pipeline.stage3_weekly_report.NotificationClient") as notifier:
                reporter.return_value.generate.return_value = weekly_markdown_path
                notifier.return_value.send_required.side_effect = RuntimeError("telegram failed")

                with self.assertRaises(RuntimeError):
                    stage3_weekly_report.run("easy_pc_fix_guide")

            report_path = root / "reports" / "easy_pc_fix_guide-weekly-failure.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertIn("telegram failed", payload["error"])

    def test_weekly_failure_message_classifies_reporting_auth_failures(self) -> None:
        message = stage3_weekly_report.build_weekly_failure_message(
            "easy_pc_fix_guide",
            RuntimeError("Search Console OAuth credentials expired"),
        )

        self.assertIn("[Posting Bot] 주간 리포트 실패", message)
        self.assertIn("Google 보고서 권한 문제", message)
        self.assertIn("Search Console/GA4 OAuth 토큰", message)

    def test_weekly_failure_message_classifies_telegram_failures(self) -> None:
        message = stage3_weekly_report.build_weekly_failure_message(
            "easy_pc_fix_guide",
            RuntimeError("telegram failed"),
        )

        self.assertIn("텔레그램 전송 문제", message)
        self.assertIn("TELEGRAM_BOT_TOKEN", message)


if __name__ == "__main__":
    unittest.main()
