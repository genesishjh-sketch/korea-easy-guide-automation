from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import patch

from src.pipeline import stage3_cadence_alert


class CadenceAlertTests(unittest.TestCase):
    def test_skips_when_today_is_not_review_date(self) -> None:
        with patch("src.pipeline.stage3_cadence_alert.NotificationClient") as notification:
            sent = stage3_cadence_alert.run(today=date(2026, 7, 21), site="easy_pc_fix_guide")

        self.assertFalse(sent)
        notification.assert_not_called()

    def test_force_sends_required_notification(self) -> None:
        with patch("src.pipeline.stage3_cadence_alert.WeeklyReporter") as reporter, patch(
            "src.pipeline.stage3_cadence_alert.actual_public_post_count", return_value=25
        ), patch("src.pipeline.stage3_cadence_alert.SearchConsoleClient") as search_console, patch(
            "src.pipeline.stage3_cadence_alert.NotificationClient"
        ) as notification:
            reporter.return_value._collect_articles.return_value = []
            reporter.return_value._quality_issue_count.return_value = 0
            search_console.return_value.summary.return_value = {
                "totals_from_top_queries": {"impressions": 100},
            }
            search_console.return_value.indexed_page_estimate.return_value = {
                "page_count_with_search_data": 25,
            }

            sent = stage3_cadence_alert.run(
                today=date(2026, 7, 22),
                force=True,
                site="easy_pc_fix_guide",
            )

        self.assertTrue(sent)
        notification.return_value.send_required.assert_called_once()

    def test_notification_failure_is_not_silenced(self) -> None:
        with patch("src.pipeline.stage3_cadence_alert.WeeklyReporter") as reporter, patch(
            "src.pipeline.stage3_cadence_alert.actual_public_post_count", return_value=25
        ), patch("src.pipeline.stage3_cadence_alert.SearchConsoleClient") as search_console, patch(
            "src.pipeline.stage3_cadence_alert.NotificationClient"
        ) as notification:
            reporter.return_value._collect_articles.return_value = []
            reporter.return_value._quality_issue_count.return_value = 0
            search_console.return_value.summary.return_value = {
                "totals_from_top_queries": {"impressions": 100},
            }
            search_console.return_value.indexed_page_estimate.return_value = {
                "page_count_with_search_data": 25,
            }
            notification.return_value.send_required.side_effect = RuntimeError("telegram failed")

            with self.assertRaises(RuntimeError):
                stage3_cadence_alert.run(
                    today=date(2026, 7, 22),
                    force=True,
                    site="easy_pc_fix_guide",
                )


if __name__ == "__main__":
    unittest.main()
