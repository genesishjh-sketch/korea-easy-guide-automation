from __future__ import annotations

import unittest
from unittest.mock import patch

from src.pipeline import stage0_preflight


class PreflightTests(unittest.TestCase):
    def test_daily_workflow_safeguards_pass(self) -> None:
        check = stage0_preflight.check_daily_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("runs tests before publishing", check.message)

    def test_validate_workflow_coverage_pass(self) -> None:
        check = stage0_preflight.check_validate_workflow()

        self.assertEqual(check.status, "pass")
        self.assertIn("covers source, tests", check.message)

    def test_public_feed_warns_without_breaking_preflight(self) -> None:
        with patch.object(stage0_preflight, "fetch_public_feed", side_effect=RuntimeError("feed unavailable")):
            check = stage0_preflight.check_public_feed("https://easypcfixguide.blogspot.com")

        self.assertEqual(check.status, "warn")
        self.assertIn("feed unavailable", check.message)

    def test_overall_status_prefers_fail_over_warn(self) -> None:
        checks = [
            stage0_preflight.PreflightCheck("a", "pass", "ok"),
            stage0_preflight.PreflightCheck("b", "warn", "watch"),
            stage0_preflight.PreflightCheck("c", "fail", "broken"),
        ]

        self.assertEqual(stage0_preflight.overall_status(checks), "fail")


if __name__ == "__main__":
    unittest.main()
