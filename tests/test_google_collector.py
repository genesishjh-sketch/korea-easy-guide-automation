from __future__ import annotations

import unittest
from unittest.mock import patch

from src.collectors.google import GoogleSuggestCollector


class GoogleSuggestCollectorTests(unittest.TestCase):
    def test_windows_known_query_uses_topic_specific_fallback_when_request_fails(self) -> None:
        collector = GoogleSuggestCollector()

        with patch("src.collectors.google.requests.get", side_effect=RuntimeError("network blocked")):
            signals = collector.collect("snipping tool not working windows 11", limit=5)

        titles = [signal.title for signal in signals]
        self.assertEqual(len(signals), 5)
        self.assertIn("windows shift s not working windows 11", titles)
        self.assertIn("repair snipping tool windows 11", titles)
        self.assertTrue(all(signal.source == "google_suggest" for signal in signals))
        self.assertTrue(
            all(signal.metadata["collection_method"] == "fallback_template" for signal in signals)
        )
        self.assertTrue(
            all(signal.metadata["evidence_type"] == "FALLBACK_TEMPLATE" for signal in signals)
        )
        self.assertTrue(all(signal.metadata["query_expansion_only"] for signal in signals))
        self.assertTrue(all(signal.score == 0 for signal in signals))
        self.assertTrue(all(signal.metadata["demand_weight"] == 0 for signal in signals))
        self.assertEqual(collector.diagnostics["status"], "fallback_only")
        self.assertEqual(collector.diagnostics["fallback_suggestion_count"], 5)
        self.assertEqual(collector.diagnostics["search_suggestion_count"], 0)
        self.assertEqual(collector.diagnostics["fallback_template_count"], 5)
        self.assertTrue(collector.diagnostics["used_fallback"])

    def test_windows_unknown_query_gets_generic_beginner_fallback_when_request_fails(self) -> None:
        collector = GoogleSuggestCollector()

        with patch("src.collectors.google.requests.get", side_effect=RuntimeError("network blocked")):
            signals = collector.collect("taskbar icons missing windows 11", limit=5)

        titles = [signal.title for signal in signals]
        self.assertEqual(len(signals), 5)
        self.assertIn("taskbar icons missing windows 11 safe beginner steps", titles)
        self.assertIn("taskbar icons missing windows 11 microsoft support", titles)
        self.assertEqual(collector.diagnostics["status"], "fallback_only")

    def test_non_windows_unknown_query_still_returns_no_fallback(self) -> None:
        collector = GoogleSuggestCollector()

        with patch("src.collectors.google.requests.get", side_effect=RuntimeError("network blocked")):
            signals = collector.collect("unrelated lifestyle topic", limit=5)

        self.assertEqual(signals, [])
        self.assertEqual(collector.diagnostics["status"], "no_google_suggestions")

    def test_live_suggestions_include_live_collection_method(self) -> None:
        collector = GoogleSuggestCollector()

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return ["wifi", ["wifi button missing windows 11", "wifi adapter missing windows 11"]]

        with patch("src.collectors.google.requests.get", return_value=Response()):
            signals = collector.collect("wifi button missing windows 11", limit=5)

        self.assertEqual(len(signals), 2)
        self.assertTrue(all(signal.metadata["collection_method"] == "live" for signal in signals))
        self.assertTrue(all(signal.metadata["evidence_type"] == "SEARCH_SUGGESTION" for signal in signals))
        self.assertTrue(all(signal.metadata["ready_weight"] == 0 for signal in signals))
        self.assertTrue(all(signal.score == 0 for signal in signals))
        self.assertEqual(collector.diagnostics["status"], "live_connected")
        self.assertEqual(collector.diagnostics["live_suggestion_count"], 2)
        self.assertEqual(collector.diagnostics["search_suggestion_count"], 2)
        self.assertEqual(collector.diagnostics["fallback_template_count"], 0)


if __name__ == "__main__":
    unittest.main()
