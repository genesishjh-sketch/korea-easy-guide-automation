from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from src.config import load_settings
from src.pipeline import stage0_reddit_health


class RedditHealthTests(unittest.TestCase):
    def test_reports_missing_credentials(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="",
            reddit_client_secret="",
            reddit_user_agent="easy-pc-fix-guide/0.1",
        )

        result = stage0_reddit_health.check_reddit_oauth(settings, "wifi button missing windows 11")

        self.assertEqual(result["status"], "missing_credentials")
        self.assertEqual(result["collection_status"], "missing_credentials")
        self.assertEqual(result["health_score"], 0)
        self.assertTrue(result["blocks_cadence_increase"])
        self.assertIn("REDDIT_CLIENT_ID", result["action_required"])
        self.assertIn("GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요.", result["remediation_steps"])
        self.assertEqual(result["setup_links"]["reddit_apps_url"], "https://www.reddit.com/prefs/apps")
        self.assertIn("/settings/secrets/actions", result["setup_links"]["github_actions_secrets_url"])
        self.assertEqual(result["setup_links"]["recommended_redirect_uri"], "http://localhost:8080")
        self.assertIn("앱 타입: script", result["setup_links"]["reddit_app_field_guide"])
        self.assertIn(
            "REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret",
            result["setup_links"]["github_secret_mapping"],
        )
        self.assertIn("user_action_checklist", result["setup_links"])
        self.assertTrue(
            any("Easy PC Fix Reddit OAuth Health" in step for step in result["setup_links"]["user_action_checklist"])
        )

    def test_reports_oauth_connected_with_sample_titles(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_user_agent="easy-pc-fix-guide/0.1",
            reddit_subreddits=["WindowsHelp"],
        )
        fake_submission = types.SimpleNamespace(
            title="Wi-Fi button disappeared after a Windows update",
            permalink="/r/WindowsHelp/comments/abc/test/",
            score=12,
            num_comments=7,
        )

        with patch.dict("sys.modules", {"praw": fake_praw_module([fake_submission])}):
            result = stage0_reddit_health.check_reddit_oauth(settings, "wifi button missing windows 11")

        self.assertEqual(result["status"], "oauth_connected")
        self.assertEqual(result["collection_status"], "stable_oauth")
        self.assertEqual(result["health_score"], 100)
        self.assertFalse(result["blocks_cadence_increase"])
        self.assertEqual(result["oauth_signal_count"], 1)
        self.assertEqual(result["sample_titles"], ["Wi-Fi button disappeared after a Windows update"])
        self.assertEqual(result["samples"][0]["subreddit"], "WindowsHelp")
        self.assertEqual(result["tested_subreddits"], ["WindowsHelp"])
        self.assertEqual(result["matched_subreddits"], ["WindowsHelp"])
        self.assertEqual(result["first_successful_subreddit"], "WindowsHelp")
        self.assertEqual(result["per_subreddit_counts"], {"WindowsHelp": 1})

    def test_oauth_health_checks_all_configured_subreddits(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_user_agent="easy-pc-fix-guide/0.1",
            reddit_subreddits=["WindowsHelp", "Windows11", "pchelp"],
        )
        submissions_by_subreddit = {
            "WindowsHelp": [
                types.SimpleNamespace(
                    title="Wi-Fi button disappeared after update",
                    permalink="/r/WindowsHelp/comments/abc/test/",
                    score=12,
                    num_comments=7,
                )
            ],
            "Windows11": [],
            "pchelp": [
                types.SimpleNamespace(
                    title="Bluetooth missing after sleep on Windows 11",
                    permalink="/r/pchelp/comments/def/test/",
                    score=5,
                    num_comments=3,
                )
            ],
        }

        with patch.dict("sys.modules", {"praw": fake_praw_module_by_subreddit(submissions_by_subreddit)}):
            result = stage0_reddit_health.check_reddit_oauth(settings, "wifi button missing windows 11")

        self.assertEqual(result["status"], "oauth_connected")
        self.assertEqual(result["oauth_signal_count"], 2)
        self.assertEqual(result["tested_subreddits"], ["WindowsHelp", "Windows11", "pchelp"])
        self.assertEqual(result["matched_subreddits"], ["WindowsHelp", "pchelp"])
        self.assertEqual(result["first_successful_subreddit"], "WindowsHelp")
        self.assertEqual(result["per_subreddit_counts"], {"WindowsHelp": 1, "Windows11": 0, "pchelp": 1})

    def test_oauth_connected_no_results_reports_tested_subreddits(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_user_agent="easy-pc-fix-guide/0.1",
            reddit_subreddits=["WindowsHelp", "Windows11"],
        )

        with patch.dict("sys.modules", {"praw": fake_praw_module([])}):
            result = stage0_reddit_health.check_reddit_oauth(settings, "rare windows error")

        self.assertEqual(result["status"], "oauth_connected_no_results")
        self.assertEqual(result["tested_subreddits"], ["WindowsHelp", "Windows11"])
        self.assertEqual(result["per_subreddit_counts"], {"WindowsHelp": 0, "Windows11": 0})
        self.assertEqual(result["matched_subreddits"], [])

    def test_fallback_queries_find_signal_when_primary_query_has_no_results(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_user_agent="easy-pc-fix-guide/0.1",
            reddit_subreddits=["WindowsHelp"],
        )
        fake_submission = types.SimpleNamespace(
            title="Windows Update error after restart",
            permalink="/r/WindowsHelp/comments/update/test/",
            score=8,
            num_comments=4,
        )

        with patch.dict("sys.modules", {"praw": fake_praw_module_by_query({"windows update error": [fake_submission]})}):
            result = stage0_reddit_health.check_reddit_oauth_with_fallback_queries(
                settings,
                "rare made up windows error",
            )

        self.assertEqual(result["status"], "oauth_connected")
        self.assertEqual(result["query"], "windows update error")
        self.assertEqual(result["query_attempt_count"], 3)
        self.assertEqual(
            [attempt["query"] for attempt in result["query_attempts"]],
            ["rare made up windows error", "wifi button missing windows 11", "windows update error"],
        )
        self.assertEqual(result["oauth_signal_count"], 1)

    def test_fallback_queries_report_all_attempts_when_no_results(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_user_agent="easy-pc-fix-guide/0.1",
            reddit_subreddits=["WindowsHelp"],
        )

        with patch.dict("sys.modules", {"praw": fake_praw_module_by_query({})}):
            result = stage0_reddit_health.check_reddit_oauth_with_fallback_queries(settings, "rare windows error")

        self.assertEqual(result["status"], "oauth_connected_no_results")
        self.assertGreater(result["query_attempt_count"], 1)
        self.assertEqual(result["query_attempts"][0]["query"], "rare windows error")
        self.assertIn("대표 Windows 검색어", result["action_required"])

    def test_run_writes_report_and_can_notify(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="",
            reddit_client_secret="",
            notification_provider="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage0_reddit_health, "ROOT_DIR", Path(tmpdir)), patch.object(
            stage0_reddit_health, "load_settings", return_value=settings
        ), patch.object(stage0_reddit_health, "NotificationClient") as notifier:
            path = stage0_reddit_health.run("easy_pc_fix_guide", query="wifi button missing windows 11", notify=True)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "missing_credentials")
        self.assertIn("# Reddit OAuth Health: Easy PC Fix Guide", payload["human_summary_markdown"])
        notifier.return_value.send_required.assert_called_once()
        message = notifier.return_value.send_required.call_args.args[0]
        self.assertIn("Reddit OAuth 상태 점검", message)
        self.assertIn("상태 점수: 0/100", message)
        self.assertIn("발행량 증량 차단: 예", message)
        self.assertIn("테스트한 subreddit: 없음", message)
        self.assertIn("신호 발견 subreddit: 없음", message)
        self.assertIn("다음 조치:", message)
        self.assertIn("GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요.", message)
        self.assertIn("설정 링크:", message)
        self.assertIn("https://www.reddit.com/prefs/apps", message)
        self.assertIn("https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions", message)
        self.assertIn("Redirect URI: http://localhost:8080", message)
        self.assertIn("Reddit 앱 입력값:", message)
        self.assertIn("client secret: Reddit 앱 상세 화면의 secret 값을 REDDIT_CLIENT_SECRET에 저장하세요.", message)
        self.assertIn("GitHub에 넣을 값:", message)
        self.assertIn("사용자가 직접 해야 할 일:", message)
        self.assertIn("앱 타입은 반드시 script를 선택하세요.", message)
        self.assertIn("Easy PC Fix Reddit OAuth Health workflow를 Run workflow로 실행하세요.", message)
        self.assertIn("검색어 재시도 기록:", message)

    def test_run_persists_reports_before_notification_failure(self) -> None:
        settings = replace(
            load_settings("easy_pc_fix_guide"),
            reddit_client_id="",
            reddit_client_secret="",
            notification_provider="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage0_reddit_health, "ROOT_DIR", Path(tmpdir)), patch.object(
            stage0_reddit_health, "load_settings", return_value=settings
        ), patch.object(stage0_reddit_health, "NotificationClient") as notifier:
            notifier.return_value.send_required.side_effect = RuntimeError("telegram failed")

            with self.assertRaises(RuntimeError):
                stage0_reddit_health.run("easy_pc_fix_guide", query="wifi button missing windows 11", notify=True)

            json_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-reddit-health.json"
            markdown_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-reddit-health.md"
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "missing_credentials")
        self.assertIn("# Reddit OAuth Health: Easy PC Fix Guide", payload["human_summary_markdown"])
        self.assertIn("# Reddit OAuth Health: Easy PC Fix Guide", markdown)
        self.assertIn("GitHub Actions secrets", markdown)
        self.assertIn("REDDIT_CLIENT_ID", markdown)

    def test_console_summary_includes_action_without_secret_values(self) -> None:
        result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "status": "missing_credentials",
            "query": "wifi button missing windows 11",
            "oauth_signal_count": 0,
            "action_required": "REDDIT_CLIENT_ID와 REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
            "remediation_steps": ["GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요."],
            "setup_links": {
                "reddit_apps_url": "https://www.reddit.com/prefs/apps",
                "github_actions_secrets_url": "https://github.com/example/repo/settings/secrets/actions",
            },
            "tested_subreddits": ["WindowsHelp"],
            "matched_subreddits": [],
            "sample_titles": [],
        }

        summary = stage0_reddit_health.build_console_summary(result)
        payload = json.loads(summary)

        self.assertEqual(payload["status"], "missing_credentials")
        self.assertEqual(payload["collection_status"], "missing_credentials")
        self.assertEqual(payload["health_score"], 0)
        self.assertTrue(payload["blocks_cadence_increase"])
        self.assertIn("REDDIT_CLIENT_ID", payload["action_required"])
        self.assertEqual(payload["setup_links"]["reddit_apps_url"], "https://www.reddit.com/prefs/apps")
        self.assertEqual(payload["tested_subreddits"], ["WindowsHelp"])
        self.assertEqual(payload["matched_subreddits"], [])
        self.assertIn("query_attempts", payload)
        self.assertNotIn("super-secret-token", summary)

    def test_metadata_marks_oauth_no_results_as_connected_but_not_ready(self) -> None:
        metadata = stage0_reddit_health.reddit_health_metadata("oauth_connected_no_results")

        self.assertEqual(metadata["collection_status"], "oauth_no_results")
        self.assertEqual(metadata["health_score"], 70)
        self.assertTrue(metadata["blocks_cadence_increase"])

    def test_markdown_report_summarizes_connected_state(self) -> None:
        markdown = stage0_reddit_health.build_markdown_report(
            {
                "site": "easy_pc_fix_guide",
                "site_name": "Easy PC Fix Guide",
                "status": "oauth_connected",
                "status_label": "Reddit OAuth 수집 안정",
                "query": "wifi button missing windows 11",
                "oauth_signal_count": 2,
                "health_score": 100,
                "blocks_cadence_increase": False,
                "tested_subreddits": ["WindowsHelp"],
                "matched_subreddits": ["WindowsHelp"],
                "action_required": "없음",
                "sample_titles": ["Wi-Fi button disappeared after update"],
            }
        )

        self.assertIn("Status: oauth_connected", markdown)
        self.assertIn("Health score: 100/100", markdown)
        self.assertIn("Blocks cadence increase: no", markdown)
        self.assertIn("Wi-Fi button disappeared after update", markdown)


def fake_praw_module(submissions: list) -> object:
    class FakeSubreddit:
        def search(self, query: str, sort: str, limit: int):
            return submissions[:limit]

    class FakeReddit:
        def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
            self.client_id = client_id
            self.client_secret = client_secret
            self.user_agent = user_agent

        def subreddit(self, name: str) -> FakeSubreddit:
            return FakeSubreddit()

    return types.SimpleNamespace(Reddit=FakeReddit)


def fake_praw_module_by_query(submissions_by_query: dict[str, list]) -> object:
    class FakeSubreddit:
        def search(self, query: str, sort: str, limit: int):
            return submissions_by_query.get(query, [])[:limit]

    class FakeReddit:
        def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
            self.client_id = client_id
            self.client_secret = client_secret
            self.user_agent = user_agent

        def subreddit(self, name: str) -> FakeSubreddit:
            return FakeSubreddit()

    return types.SimpleNamespace(Reddit=FakeReddit)


def fake_praw_module_by_subreddit(submissions_by_subreddit: dict[str, list]) -> object:
    class FakeSubreddit:
        def __init__(self, name: str) -> None:
            self.name = name

        def search(self, query: str, sort: str, limit: int):
            return submissions_by_subreddit.get(self.name, [])[:limit]

    class FakeReddit:
        def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
            self.client_id = client_id
            self.client_secret = client_secret
            self.user_agent = user_agent

        def subreddit(self, name: str) -> FakeSubreddit:
            return FakeSubreddit(name)

    return types.SimpleNamespace(Reddit=FakeReddit)


if __name__ == "__main__":
    unittest.main()
