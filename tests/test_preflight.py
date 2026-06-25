from __future__ import annotations

from contextlib import ExitStack
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

    def test_reddit_health_report_persistence_passes(self) -> None:
        check = stage0_preflight.check_reddit_health_report_persistence()

        self.assertEqual(check.status, "pass")
        self.assertIn("embedded human-readable summary", check.message)

    def test_publication_check_report_persistence_passes(self) -> None:
        check = stage0_preflight.check_publication_check_report_persistence()

        self.assertEqual(check.status, "pass")
        self.assertIn("public feed verification fails", check.message)

    def test_seed_file_fails_on_blank_topic_seed(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings, patch.object(
            stage0_preflight, "load_seed_list", return_value=["wifi button missing windows 11", " "]
        ):
            load_settings.return_value.content_domain = "windows_help"
            check = stage0_preflight.check_seed_file("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("blank topic seed", check.message)

    def test_seed_file_fails_on_duplicate_topic_seed(self) -> None:
        seeds = ["wifi button missing windows 11", "WiFi button missing windows 11", "printer offline windows 11"]
        with patch.object(stage0_preflight, "load_settings") as load_settings, patch.object(
            stage0_preflight, "load_seed_list", return_value=seeds
        ):
            load_settings.return_value.content_domain = "windows_help"
            check = stage0_preflight.check_seed_file("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("Duplicate topic seeds", check.message)
        self.assertIn("wifi button missing windows 11", check.message.lower())

    def test_seed_file_fails_on_weak_windows_topic_seed(self) -> None:
        seeds = ["windows error", *[f"printer offline windows 11 model {i}" for i in range(29)]]
        with patch.object(stage0_preflight, "load_settings") as load_settings, patch.object(
            stage0_preflight, "load_seed_list", return_value=seeds
        ):
            load_settings.return_value.content_domain = "windows_help"
            check = stage0_preflight.check_seed_file("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("Weak Windows topic seeds", check.message)
        self.assertIn("specific error codes", check.message)

    def test_seed_file_allows_specific_windows_topic_seed(self) -> None:
        seeds = [f"windows update error 0x8007000{i}" for i in range(30)]
        with patch.object(stage0_preflight, "load_settings") as load_settings, patch.object(
            stage0_preflight, "load_seed_list", return_value=seeds
        ):
            load_settings.return_value.content_domain = "windows_help"
            check = stage0_preflight.check_seed_file("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("30 topic seeds found", check.message)

    def test_all_seed_quality_fails_on_generic_or_weak_windows_topic(self) -> None:
        seeds = ["windows problem", "wifi button missing windows 11"]
        with patch.object(stage0_preflight, "load_settings") as load_settings, patch.object(
            stage0_preflight, "load_seed_list", return_value=seeds
        ):
            load_settings.return_value.content_domain = "windows_help"
            check = stage0_preflight.check_all_seed_quality("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("Long-term seed quality failed", check.message)
        self.assertIn("windows problem", check.message)

    def test_current_easy_pc_seed_file_passes_long_term_quality_sweep(self) -> None:
        check = stage0_preflight.check_all_seed_quality("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("long-term topics", check.message)

    def test_critical_notifications_are_required(self) -> None:
        check = stage0_preflight.check_critical_notifications()

        self.assertEqual(check.status, "pass")
        self.assertIn("fail loudly", check.message)

    def test_launch_queue_passes_with_seven_topics_from_main_seed_file(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(stage0_preflight, "load_seed_list", return_value=[f"topic {i}" for i in range(8)]), patch.object(
                stage0_preflight, "load_launch_seed_list", return_value=[f"topic {i}" for i in range(7)]
            ), patch.object(stage0_preflight, "used_keywords", return_value=set()):
                check = stage0_preflight.check_launch_queue("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("7/7 launch topics remain unused", check.message)

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

    def test_launch_queue_warns_when_unused_launch_topics_are_low(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(stage0_preflight, "load_seed_list", return_value=[f"topic {i}" for i in range(8)]), patch.object(
                stage0_preflight, "load_launch_seed_list", return_value=[f"topic {i}" for i in range(7)]
            ), patch.object(stage0_preflight, "used_keywords", return_value={f"topic {i}" for i in range(5)}):
                check = stage0_preflight.check_launch_queue("easy_pc_fix_guide")

        self.assertEqual(check.status, "warn")
        self.assertIn("2/7 launch topics remain unused", check.message)
        self.assertIn("guided launch sequence", check.message)

    def test_launch_queue_warns_when_unused_launch_topics_are_empty(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(stage0_preflight, "load_seed_list", return_value=[f"topic {i}" for i in range(8)]), patch.object(
                stage0_preflight, "load_launch_seed_list", return_value=[f"topic {i}" for i in range(7)]
            ), patch.object(stage0_preflight, "used_keywords", return_value={f"topic {i}" for i in range(7)}):
                check = stage0_preflight.check_launch_queue("easy_pc_fix_guide")

        self.assertEqual(check.status, "warn")
        self.assertIn("0/7 launch topics remain unused", check.message)
        self.assertIn("long-term seed list", check.message)

    def test_launch_queue_quality_passes_for_current_queue(self) -> None:
        check = stage0_preflight.check_launch_queue_quality("easy_pc_fix_guide")

        self.assertEqual(check.status, "pass")
        self.assertIn("launch topics have specific categories", check.message)
        self.assertIn("Microsoft sources", check.message)

    def test_launch_queue_quality_fails_on_generic_or_weak_sources(self) -> None:
        with patch.object(stage0_preflight, "load_settings") as load_settings:
            load_settings.return_value.content_domain = "windows_help"
            with patch.object(
                stage0_preflight,
                "load_seed_list",
                return_value=["windows problem", *[f"wifi keeps disconnecting windows 11 variant {i}" for i in range(7)]],
            ), patch.object(
                stage0_preflight,
                "load_launch_seed_list",
                return_value=["windows problem", *[f"wifi keeps disconnecting windows 11 variant {i}" for i in range(6)]],
            ):
                check = stage0_preflight.check_launch_queue_quality("easy_pc_fix_guide")

        self.assertEqual(check.status, "fail")
        self.assertIn("windows problem", check.message)
        self.assertIn("generic_computer_help_category", check.message)

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

    def test_setup_actions_classify_reddit_oauth_as_cadence_blocker(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck("reddit_collection", "warn", "Reddit OAuth credentials are missing."),
            stage0_preflight.PreflightCheck("telegram", "pass", "Telegram notifications are configured."),
        ]

        actions = stage0_preflight.build_setup_actions(checks)
        readiness = stage0_preflight.build_readiness_summary(checks, actions)

        self.assertEqual(actions[0]["name"], "reddit_oauth")
        self.assertEqual(actions[0]["owner"], "user")
        self.assertFalse(actions[0]["blocks_unattended_publish"])
        self.assertTrue(actions[0]["blocks_cadence_increase"])
        self.assertIn("REDDIT_CLIENT_ID", actions[0]["next_step"])
        self.assertTrue(readiness["ready_for_unattended_publish"])
        self.assertFalse(readiness["ready_for_cadence_increase"])
        self.assertEqual(readiness["required_user_action_count"], 1)

    def test_setup_actions_classify_telegram_failure_as_unattended_blocker(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck("telegram", "fail", "Telegram provider is enabled but bot token is missing."),
        ]

        actions = stage0_preflight.build_setup_actions(checks)
        readiness = stage0_preflight.build_readiness_summary(checks, actions)

        self.assertEqual(actions[0]["name"], "posting_bot")
        self.assertTrue(actions[0]["blocks_unattended_publish"])
        self.assertFalse(actions[0]["blocks_cadence_increase"])
        self.assertFalse(readiness["ready_for_unattended_publish"])
        self.assertTrue(readiness["ready_for_cadence_increase"])
        self.assertEqual(readiness["failed_checks"], ["telegram"])

    def test_setup_actions_classify_low_seed_inventory_as_cadence_blocker(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck(
                "seed_inventory",
                "warn",
                "10/20 exact-match topic seeds remain unused. Add at least two weeks of fresh topic seeds soon.",
            ),
        ]

        actions = stage0_preflight.build_setup_actions(checks)
        readiness = stage0_preflight.build_readiness_summary(checks, actions)

        self.assertEqual(actions[0]["name"], "seed_inventory")
        self.assertEqual(actions[0]["label"], "Windows topic seed 재고")
        self.assertEqual(actions[0]["owner"], "automation")
        self.assertFalse(actions[0]["blocks_unattended_publish"])
        self.assertTrue(actions[0]["blocks_cadence_increase"])
        self.assertIn("최소 14개", actions[0]["next_step"])
        self.assertTrue(readiness["ready_for_unattended_publish"])
        self.assertFalse(readiness["ready_for_cadence_increase"])

    def test_setup_actions_classify_empty_seed_inventory_as_publish_blocker(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck(
                "seed_inventory",
                "fail",
                "0/5 exact-match topic seeds remain unused. Add fresh Windows topic seeds before the next unattended publish.",
            ),
        ]

        actions = stage0_preflight.build_setup_actions(checks)
        readiness = stage0_preflight.build_readiness_summary(checks, actions)

        self.assertTrue(actions[0]["blocks_unattended_publish"])
        self.assertTrue(actions[0]["blocks_cadence_increase"])
        self.assertEqual(actions[0]["urgency"], "before_unattended_publish")
        self.assertFalse(readiness["ready_for_unattended_publish"])
        self.assertFalse(readiness["ready_for_cadence_increase"])

    def test_run_writes_readiness_and_setup_actions(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck("reddit_collection", "warn", "Reddit OAuth credentials are missing."),
            stage0_preflight.PreflightCheck("telegram", "pass", "Telegram notifications are configured."),
        ]

        pass_check_names = [
            "check_site_settings",
            "check_seed_file",
            "check_seed_inventory",
            "check_all_seed_quality",
            "check_launch_queue",
            "check_launch_queue_quality",
            "check_zero_cost_image_policy",
            "check_daily_workflow",
            "check_validate_workflow",
            "check_publication_check_workflow",
            "check_weekly_report_workflow",
            "check_cadence_alert_workflow",
            "check_reddit_health_workflow",
            "check_reddit_health_report_persistence",
            "check_publication_check_report_persistence",
            "check_critical_notifications",
            "check_public_feed",
            "check_local_google_files",
            "check_reporting_google_files",
            "check_telegram_settings",
        ]

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            stack.enter_context(patch.object(stage0_preflight, "ROOT_DIR", Path(tmpdir)))
            load_settings = stack.enter_context(patch.object(stage0_preflight, "load_settings"))
            stack.enter_context(patch.object(stage0_preflight, "check_python_runtime", return_value=checks[1]))
            stack.enter_context(patch.object(stage0_preflight, "check_reddit_collection_settings", return_value=checks[0]))
            for name in pass_check_names:
                stack.enter_context(patch.object(stage0_preflight, name, return_value=checks[1]))

            settings = load_settings.return_value
            settings.site_key = "easy_pc_fix_guide"
            settings.site_name = "Easy PC Fix Guide"
            settings.site_url = "https://easypcfixguide.blogspot.com"
            settings.google_oauth_client_secret_file = ""
            settings.google_oauth_token_file = ""
            settings.notification_provider = "telegram"
            settings.telegram_bot_token = "token"
            settings.telegram_chat_id = "chat"

            path = stage0_preflight.run("easy_pc_fix_guide")
            payload = json.loads(path.read_text(encoding="utf-8"))
            markdown = (path.parent / "easy_pc_fix_guide-preflight.md").read_text(encoding="utf-8")

        self.assertIn("readiness", payload)
        self.assertIn("setup_actions", payload)
        self.assertFalse(payload["readiness"]["ready_for_cadence_increase"])
        self.assertEqual(payload["setup_actions"][0]["name"], "reddit_oauth")
        self.assertIn("user_action_checklist", payload["setup_actions"][0])
        self.assertIn("reddit_data_access_request_guide", payload["setup_actions"][0])
        self.assertIn("앱 타입은 반드시 script를 선택하세요.", "\n".join(payload["setup_actions"][0]["user_action_checklist"]))
        self.assertIn("read-only topic research", "\n".join(payload["setup_actions"][0]["reddit_data_access_request_guide"]))
        self.assertIn("# Preflight Report: Easy PC Fix Guide", markdown)
        self.assertIn("무인 발행 준비: 예", markdown)
        self.assertIn("발행량 증량 준비: 아니오", markdown)
        self.assertIn("Reddit OAuth 연결", markdown)
        self.assertIn("REDDIT_CLIENT_ID", markdown)
        self.assertIn("reddit_data_access_request", markdown)
        self.assertIn("Data Access Request 입력 가이드", markdown)
        self.assertIn("사용자가 직접 할 일", markdown)
        self.assertIn("Easy PC Fix Reddit OAuth Health workflow를 Run workflow로 실행하세요.", markdown)
        self.assertIn("## 전체 점검", markdown)

    def test_preflight_markdown_summarizes_no_action_state(self) -> None:
        result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "site_url": "https://easypcfixguide.blogspot.com",
            "status": "pass",
            "readiness": {
                "ready_for_unattended_publish": True,
                "ready_for_cadence_increase": True,
                "required_user_action_count": 0,
            },
            "setup_actions": [],
            "checks": [{"name": "site_settings", "status": "pass", "message": "configured"}],
        }

        markdown = stage0_preflight.build_preflight_markdown(result)

        self.assertIn("전체 상태: 통과", markdown)
        self.assertIn("추가 조치 없음", markdown)
        self.assertIn("통과 `site_settings`: configured", markdown)

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
