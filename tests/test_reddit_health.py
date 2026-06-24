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
        self.assertIn("REDDIT_CLIENT_ID", result["action_required"])
        self.assertIn("GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요.", result["remediation_steps"])

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
        self.assertEqual(result["oauth_signal_count"], 1)
        self.assertEqual(result["sample_titles"], ["Wi-Fi button disappeared after a Windows update"])
        self.assertEqual(result["samples"][0]["subreddit"], "WindowsHelp")

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
        notifier.return_value.send_required.assert_called_once()
        message = notifier.return_value.send_required.call_args.args[0]
        self.assertIn("Reddit OAuth 상태 점검", message)
        self.assertIn("다음 조치:", message)
        self.assertIn("GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요.", message)

    def test_console_summary_includes_action_without_secret_values(self) -> None:
        result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "status": "missing_credentials",
            "query": "wifi button missing windows 11",
            "oauth_signal_count": 0,
            "action_required": "REDDIT_CLIENT_ID와 REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
            "remediation_steps": ["GitHub Secrets에 REDDIT_CLIENT_ID를 추가하세요."],
            "sample_titles": [],
        }

        summary = stage0_reddit_health.build_console_summary(result)
        payload = json.loads(summary)

        self.assertEqual(payload["status"], "missing_credentials")
        self.assertIn("REDDIT_CLIENT_ID", payload["action_required"])
        self.assertNotIn("super-secret-token", summary)


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


if __name__ == "__main__":
    unittest.main()
