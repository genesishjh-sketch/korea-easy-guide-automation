from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from src.pipeline import daily_draft
from src.quality.hades import HadesQualityGate


class DuplicatePublishGuardTests(unittest.TestCase):
    def test_matches_existing_post_by_title_when_blogger_shortens_slug(self) -> None:
        existing_post = {
            "title": "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
            "url": "https://easypcfixguide.blogspot.com/2026/06/wi-fi-button-missing-on-windows-11.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }
        with patch.object(daily_draft, "fetch_public_feed", return_value={}), patch.object(
            daily_draft, "parse_posts", return_value=[existing_post]
        ):
            duplicate = daily_draft.find_public_post(
                "https://easypcfixguide.blogspot.com",
                "wi-fi-button-missing-on-windows-11-simple-fixes-for-beginners",
                "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
            )

        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate["url"], existing_post["url"])

    def test_public_feed_errors_stop_publish_instead_of_assuming_no_duplicate(self) -> None:
        with patch.object(daily_draft, "fetch_public_feed", side_effect=RuntimeError("feed unavailable")):
            with self.assertRaises(RuntimeError):
                daily_draft.find_public_post("https://easypcfixguide.blogspot.com", "any-slug", "Any Title")


class WindowsQualityGateTests(unittest.TestCase):
    def test_windows_articles_require_official_microsoft_source(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("missing_microsoft_source", {issue.code for issue in issues})

    def test_windows_articles_block_activation_bypass_content(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            "applies to risk level data loss risk estimated time last checked kms activator",
            links=[],
        )

        self.assertIn("blocked_windows_phrase", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
