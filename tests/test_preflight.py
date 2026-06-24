from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage0_preflight


class PreflightTests(unittest.TestCase):
    def test_python_runtime_passes_on_supported_version(self) -> None:
        with patch.object(stage0_preflight.sys, "version_info") as version_info:
            version_info.major = 3
            version_info.minor = 11
            version_info.micro = 9
            check = stage0_preflight.check_python_runtime()

        self.assertEqual(check.status, "pass")
        self.assertIn("Python 3.11.9", check.message)

    def test_python_runtime_warns_below_actions_version(self) -> None:
        with patch.object(stage0_preflight.sys, "version_info") as version_info:
            version_info.major = 3
            version_info.minor = 9
            version_info.micro = 6
            check = stage0_preflight.check_python_runtime()

        self.assertEqual(check.status, "warn")
        self.assertIn("use Python 3.11", check.message)

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

    def test_cadence_alert_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_cadence_alert_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("2026-07-22", check.message)

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

    def test_reporting_google_files_warn_when_reporting_tokens_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_path = Path(tmpdir) / "client_secret.json"
            secret_path.write_text("{}", encoding="utf-8")
            token_path = Path(tmpdir) / "google_token.json"

            check = stage0_preflight.check_reporting_google_files(str(secret_path), str(token_path))

        self.assertEqual(check.status, "warn")
        self.assertIn("GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON", check.message)
        self.assertIn("GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON", check.message)

    def test_reporting_google_files_pass_when_reporting_tokens_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_path = Path(tmpdir) / "client_secret.json"
            token_path = Path(tmpdir) / "google_token.json"
            search_console_path = Path(tmpdir) / "google_token.search-console.json"
            analytics_path = Path(tmpdir) / "google_token.analytics.json"
            for path in [secret_path, search_console_path, analytics_path]:
                path.write_text("{}", encoding="utf-8")

            check = stage0_preflight.check_reporting_google_files(str(secret_path), str(token_path))

        self.assertEqual(check.status, "pass")
        self.assertIn("Search Console and GA4", check.message)

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
