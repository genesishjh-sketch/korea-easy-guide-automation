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

    def test_reddit_health_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_reddit_health_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("OAuth", check.message)

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

    def test_reddit_collection_warns_without_oauth_credentials(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.reddit_subreddits = ["WindowsHelp", "Windows11"]
            load_settings.return_value.reddit_user_agent = "easy-pc-fix-guide/0.1"
            load_settings.return_value.reddit_client_id = ""
            load_settings.return_value.reddit_client_secret = ""

            check = stage0_preflight.check_reddit_collection_settings("easy_pc_fix_guide")

        self.assertEqual(check.status, "warn")
        self.assertIn("Public Reddit JSON may return 403", check.message)
        self.assertIn("https://www.reddit.com/prefs/apps", check.message)
        self.assertIn("/settings/secrets/actions", check.message)

    def test_reddit_collection_passes_with_oauth_credentials(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.reddit_subreddits = ["WindowsHelp", "Windows11"]
            load_settings.return_value.reddit_user_agent = "easy-pc-fix-guide/0.1"
            load_settings.return_value.reddit_client_id = "client"
            load_settings.return_value.reddit_client_secret = "secret"

            check = stage0_preflight.check_reddit_collection_settings("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("Reddit OAuth credentials", check.message)

    def test_seed_inventory_passes_when_two_weeks_of_unused_seeds_remain(self) -> None:
        seeds = [f"topic {index}" for index in range(20)]
        with patch.object(stage0_preflight, "load_seed_list", return_value=seeds), patch.object(
            stage0_preflight, "used_keywords", return_value={f"topic {index}" for index in range(6)}
        ):
            check = stage0_preflight.check_seed_inventory("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("14/20", check.message)

    def test_seed_inventory_warns_when_unused_seeds_are_low(self) -> None:
        seeds = [f"topic {index}" for index in range(20)]
        with patch.object(stage0_preflight, "load_seed_list", return_value=seeds), patch.object(
            stage0_preflight, "used_keywords", return_value={f"topic {index}" for index in range(10)}
        ):
            check = stage0_preflight.check_seed_inventory("easy_pc_fix_guide")

        self.assertEqual(check.status, "warn")
        self.assertIn("10/20", check.message)
        self.assertIn("two weeks", check.message)

    def test_seed_inventory_fails_when_no_unused_seeds_remain(self) -> None:
        seeds = [f"topic {index}" for index in range(5)]
        with patch.object(stage0_preflight, "load_seed_list", return_value=seeds), patch.object(
            stage0_preflight, "used_keywords", return_value={f"topic {index}" for index in range(5)}
        ):
            check = stage0_preflight.check_seed_inventory("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("0/5", check.message)
        self.assertIn("before the next unattended publish", check.message)

    def test_zero_cost_image_policy_passes_without_paid_image_envs(self) -> None:
        env = {name: "" for name in stage0_preflight.PAID_IMAGE_ENV_NAMES}
        with patch.dict("os.environ", env):
            check = stage0_preflight.check_zero_cost_image_policy()

        self.assertEqual(check.status, "pass")
        self.assertIn("without paid image API wiring", check.message)

    def test_zero_cost_image_policy_warns_with_local_paid_image_key(self) -> None:
        env = {name: "" for name in stage0_preflight.PAID_IMAGE_ENV_NAMES}
        env["OPENAI_API_KEY"] = "local-test-key"
        with patch.dict("os.environ", env):
            check = stage0_preflight.check_zero_cost_image_policy()

        self.assertEqual(check.status, "warn")
        self.assertIn("OPENAI_API_KEY", check.message)

    def test_zero_cost_image_policy_fails_when_workflow_uses_paid_image_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workflow_dir = root / ".github" / "workflows"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "daily.yml").write_text("env:\n  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n", encoding="utf-8")
            image_dir = root / "src" / "images"
            image_dir.mkdir(parents=True)
            (image_dir / "ai_plan.py").write_text(
                "\n".join(
                    [
                        "codex_generated_no_api",
                        "Do not call paid image APIs in the Python pipeline.",
                        "IMAGE_ASSET_MODE",
                        "manual_jpg",
                        'return "svg"',
                    ]
                ),
                encoding="utf-8",
            )
            env = {name: "" for name in stage0_preflight.PAID_IMAGE_ENV_NAMES}
            with patch.object(stage0_preflight, "ROOT_DIR", root), patch.dict("os.environ", env):
                check = stage0_preflight.check_zero_cost_image_policy()

        self.assertEqual(check.status, "fail")
        self.assertIn("OPENAI_API_KEY", check.message)

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
