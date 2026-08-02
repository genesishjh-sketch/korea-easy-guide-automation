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
        self.assertEqual(signals[0].metadata["evidence_type"], "OBSERVED_QUESTION")
        self.assertEqual(signals[0].metadata["demand_weight"], 1.0)
        self.assertEqual(collector.diagnostics["observed_signal_count"], 1)

    def test_fallback_signals_include_collection_method(self) -> None:
        collector = RedditCollector("easy-pc-fix-guide/0.1", subreddits=["WindowsHelp"])

        with patch("src.collectors.reddit.requests.get", side_effect=RuntimeError("blocked")), patch.object(
            collector, "_google_site_search_signals", return_value=[]
        ):
            signals = collector.collect("wifi button missing windows 11")

        self.assertTrue(signals)
        self.assertTrue(all(signal.source == "reddit_fallback" for signal in signals))
        self.assertTrue(all(signal.metadata["collection_method"] == "fallback" for signal in signals))
        self.assertTrue(
            all(signal.metadata["evidence_type"] == "FALLBACK_TEMPLATE" for signal in signals)
        )
        self.assertTrue(all(signal.score == 0 for signal in signals))
        self.assertTrue(all(signal.metadata["demand_weight"] == 0 for signal in signals))
        self.assertEqual(collector.diagnostics["status"], "fallback_only")
        self.assertEqual(collector.diagnostics["public_json_attempted_subreddits"], ["WindowsHelp"])
        self.assertEqual(collector.diagnostics["public_json_error_count"], 1)
        self.assertEqual(collector.diagnostics["public_json_failed_subreddits"][0]["subreddit"], "WindowsHelp")
        self.assertIn("blocked", collector.diagnostics["public_json_failed_subreddits"][0]["error"])
        self.assertTrue(collector.diagnostics["used_fallback"])

    def test_skip_public_json_uses_fallback_without_network_request(self) -> None:
        collector = RedditCollector(
            "easy-pc-fix-guide/0.1",
            subreddits=["WindowsHelp"],
            skip_public_json=True,
            skip_public_json_reason="approval pending",
        )

        with patch("src.collectors.reddit.requests.get") as public_get:
            signals = collector.collect("wifi button missing windows 11")

        public_get.assert_not_called()
        self.assertTrue(signals)
        self.assertEqual(collector.diagnostics["status"], "query_plan_only")
        self.assertTrue(collector.diagnostics["public_json_skipped"])
        self.assertEqual(collector.diagnostics["public_json_skip_reason"], "approval pending")
        self.assertEqual(collector.diagnostics["public_json_attempted_subreddits"], [])
        self.assertEqual(collector.diagnostics["public_json_error_count"], 0)
        self.assertEqual(collector.diagnostics["google_site_search_signal_count"], len(signals))
        self.assertEqual(signals[0].source, "reddit_search")
        self.assertEqual(signals[0].metadata["collection_method"], "google_site_search")
        self.assertEqual(signals[0].metadata["evidence_type"], "QUERY_PLAN")
        self.assertEqual(signals[0].score, 0)
        self.assertEqual(signals[0].metadata["ready_weight"], 0)

    def test_public_json_failure_uses_google_site_search_before_local_fallback(self) -> None:
        collector = RedditCollector("easy-pc-fix-guide/0.1", subreddits=["WindowsHelp"])

        with patch("src.collectors.reddit.requests.get", side_effect=RuntimeError("blocked")):
            signals = collector.collect("wifi button missing windows 11")

        self.assertTrue(signals)
        self.assertEqual(collector.diagnostics["status"], "query_plan_only")
        self.assertEqual(collector.diagnostics["public_json_error_count"], 1)
        self.assertEqual(collector.diagnostics["google_site_search_signal_count"], len(signals))
        self.assertTrue(all(signal.source == "reddit_search" for signal in signals))
        self.assertTrue(all(signal.metadata["evidence_type"] == "QUERY_PLAN" for signal in signals))
        self.assertTrue(all(signal.metadata["cadence_weight"] == 0 for signal in signals))

    def test_unverified_public_json_results_remain_zero_weight_query_plans(self) -> None:
        collector = RedditCollector("easy-pc-fix-guide/0.1", subreddits=["WindowsHelp"])

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "id": "abc123",
                                    "title": "Wi-Fi disappeared after an update",
                                    "permalink": "/r/WindowsHelp/comments/abc123/example/",
                                    "score": 25,
                                    "num_comments": 9,
                                    "created_utc": 1_700_000_000,
                                }
                            }
                        ]
                    }
                }

        with patch("src.collectors.reddit.requests.get", return_value=Response()):
            signals = collector.collect("wifi disappeared")

        self.assertEqual(collector.diagnostics["status"], "public_json_unverified")
        self.assertEqual(collector.diagnostics["observed_signal_count"], 0)
        self.assertEqual(collector.diagnostics["query_plan_count"], 1)
        self.assertEqual(signals[0].metadata["evidence_type"], "QUERY_PLAN")
        self.assertFalse(signals[0].metadata["verified_by_codex"])
        self.assertEqual(signals[0].metadata["reddit_item_id"], "abc123")
        self.assertEqual(signals[0].score, 0)
        self.assertEqual(signals[0].metadata["demand_weight"], 0)

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
        self.assertEqual(collector.diagnostics["status"], "query_plan_only")
        self.assertEqual(collector.diagnostics["oauth_error"], "invalid_grant")


if __name__ == "__main__":
    unittest.main()
