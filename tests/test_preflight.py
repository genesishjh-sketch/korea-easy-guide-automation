from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage0_preflight


class PreflightTests(unittest.TestCase):
    def test_daily_workflow_safeguards_pass(self) -> None:
        check = stage0_preflight.check_daily_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("runs tests before publishing", check.message)

    def test_validate_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_validate_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("covers source, tests", check.message)

    def test_publication_check_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_publication_check_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("public feed", check.message)

    def test_weekly_report_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_weekly_report_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("Search Console", check.message)

    def test_critical_notifications_are_required(self) -> None:
        check = stage0_preflight.check_critical_notifications()

        self.assertEqual(check.status, "pass")
        self.assertIn("fail loudly", check.message)

    def test_launch_queue_passes_with_seven_topics_from_main_seed_file(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(stage0_preflight, "load_seed_list", return_value=[f"topic {i}" for i in range(8)]), patch.object(
                stage0_preflight, "load_launch_seed_list", return_value=[f"topic {i}" for i in range(7)]
            ):
                check = stage0_preflight.check_launch_queue("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("7 launch topics", check.message)

    def test_launch_queue_fails_when_topic_is_not_in_main_seed_file(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(stage0_preflight, "load_seed_list", return_value=[f"topic {i}" for i in range(7)]), patch.object(
                stage0_preflight,
                "load_launch_seed_list",
                return_value=[*([f"topic {i}" for i in range(6)]), "missing topic"],
            ):
                check = stage0_preflight.check_launch_queue("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("missing topic", check.message)

    def test_public_feed_warns_without_breaking_preflight(self) -> None:
        with patch.object(stage0_preflight, "fetch_public_feed", side_effect=RuntimeError("feed unavailable")):
            check = stage0_preflight.check_public_feed("https://easypcfixguide.blogspot.com")

        self.assertEqual(check.status, "warn")
        self.assertIn("feed unavailable", check.message)

    def test_overall_status_prefers_fail_over_warn(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck("a", "pass", "ok"),
            stage0_preflight.PreflightCheck("b", "warn", "watch"),
            stage0_preflight.PreflightCheck("c", "fail", "broken"),
        ]

        self.assertEqual(stage0_preflight.overall_status(checks), "fail")

    def test_main_exits_nonzero_when_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preflight.json"
            path.write_text(json.dumps({"status": "fail"}), encoding="utf-8")
            with patch.object(stage0_preflight, "run", return_value=path), patch("sys.argv", ["stage0_preflight"]):
                with self.assertRaises(SystemExit) as raised:
                    stage0_preflight.main()

        self.assertEqual(raised.exception.code, 1)

    def test_main_allows_warning_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preflight.json"
            path.write_text(json.dumps({"status": "warn"}), encoding="utf-8")
            with patch.object(stage0_preflight, "run", return_value=path), patch("sys.argv", ["stage0_preflight"]):
                stage0_preflight.main()


if __name__ == "__main__":
    unittest.main()
