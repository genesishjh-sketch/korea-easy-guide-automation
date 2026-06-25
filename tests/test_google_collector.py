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

    def test_windows_unknown_query_gets_generic_beginner_fallback_when_request_fails(self) -> None:
        collector = GoogleSuggestCollector()

        with patch("src.collectors.google.requests.get", side_effect=RuntimeError("network blocked")):
            signals = collector.collect("taskbar icons missing windows 11", limit=5)

        titles = [signal.title for signal in signals]
        self.assertEqual(len(signals), 5)
        self.assertIn("taskbar icons missing windows 11 safe beginner steps", titles)
        self.assertIn("taskbar icons missing windows 11 microsoft support", titles)

    def test_non_windows_unknown_query_still_returns_no_fallback(self) -> None:
        collector = GoogleSuggestCollector()

        with patch("src.collectors.google.requests.get", side_effect=RuntimeError("network blocked")):
            signals = collector.collect("unrelated lifestyle topic", limit=5)

        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
