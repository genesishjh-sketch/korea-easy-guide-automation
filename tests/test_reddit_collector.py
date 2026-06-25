from __future__ import annotations

import unittest
from unittest.mock import patch

from src.collectors.reddit import RedditCollector
from src.models import TopicSignal


class RedditCollectorTests(unittest.TestCase):
    def test_oauth_signals_skip_public_json_collection(self) -> None:
        collector = RedditCollector(
            "easy-pc-fix-guide/0.1",
            client_id="client",
            client_secret="secret",
            subreddits=["WindowsHelp"],
        )
        oauth_signal = TopicSignal(
            "reddit",
            "wifi button missing windows 11",
            "Wi-Fi button disappeared after update",
            metadata={"collection_method": "oauth"},
        )

        with patch.object(collector, "_collect_with_praw", return_value=[oauth_signal]) as oauth, patch(
            "src.collectors.reddit.requests.get"
        ) as public_get:
            signals = collector.collect("wifi button missing windows 11")

        oauth.assert_called_once()
        public_get.assert_not_called()
        self.assertEqual(signals, [oauth_signal])
        self.assertEqual(signals[0].metadata["collection_method"], "oauth")

    def test_fallback_signals_include_collection_method(self) -> None:
        collector = RedditCollector("easy-pc-fix-guide/0.1", subreddits=["WindowsHelp"])

        with patch("src.collectors.reddit.requests.get", side_effect=RuntimeError("blocked")):
            signals = collector.collect("wifi button missing windows 11")

        self.assertTrue(signals)
        self.assertTrue(all(signal.source == "reddit_fallback" for signal in signals))
        self.assertTrue(all(signal.metadata["collection_method"] == "fallback" for signal in signals))
        self.assertEqual(collector.diagnostics["status"], "fallback_only")
        self.assertEqual(collector.diagnostics["public_json_attempted_subreddits"], ["WindowsHelp"])
        self.assertEqual(collector.diagnostics["public_json_error_count"], 1)
        self.assertEqual(collector.diagnostics["public_json_failed_subreddits"][0]["subreddit"], "WindowsHelp")
        self.assertIn("blocked", collector.diagnostics["public_json_failed_subreddits"][0]["error"])
        self.assertTrue(collector.diagnostics["used_fallback"])

    def test_oauth_failure_is_recorded_before_public_json_fallback(self) -> None:
        collector = RedditCollector(
            "easy-pc-fix-guide/0.1",
            client_id="client",
            client_secret="secret",
            subreddits=["WindowsHelp"],
        )

        def fail_oauth(_query: str, _limit: int) -> list:
            collector.diagnostics["oauth_error"] = "invalid_grant"
            return []

        with patch.object(collector, "_collect_with_praw", side_effect=fail_oauth):
            with patch("src.collectors.reddit.requests.get", side_effect=RuntimeError("blocked")):
                signals = collector.collect("wifi button missing windows 11")

        self.assertTrue(signals)
        self.assertTrue(collector.diagnostics["oauth_configured"])
        self.assertEqual(collector.diagnostics["status"], "fallback_only")
        self.assertEqual(collector.diagnostics["oauth_error"], "invalid_grant")


if __name__ == "__main__":
    unittest.main()
