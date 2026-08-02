from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_cadence_alert


class CadenceAlertTests(unittest.TestCase):
    def test_skips_when_today_is_not_review_date(self) -> None:
        with patch("src.pipeline.stage3_cadence_alert.NotificationClient") as notification:
            sent = stage3_cadence_alert.run(today=date(2026, 7, 21), site="easy_pc_fix_guide", verbose=False)

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
            reporter.return_value._signal_quality_result.return_value = {
                "status": "connected",
                "reddit_oauth_signal_count": 5,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 0,
                "fallback_reddit_signal_count": 0,
                "evidence_counts_verified": True,
                "derived_evidence_counts": {
                    "live_reddit_signal_count": 5,
                    "reddit_oauth_signal_count": 5,
                    "observed_question_count": 5,
                    "first_party_query_count": 0,
                    "demand_eligible_signal_count": 5,
                },
            }
            reporter.return_value._operations_result.return_value = {
                "reddit_health": {
                    "status": "oauth_connected",
                    "health_score": 100,
                    "blocks_cadence_increase": False,
                }
            }
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
                verbose=False,
            )

        self.assertTrue(sent)
        notification.return_value.send_required.assert_called_once()

    def test_query_plan_only_includes_observed_evidence_setup_fields(self) -> None:
        with patch("src.pipeline.stage3_cadence_alert.WeeklyReporter") as reporter, patch(
            "src.pipeline.stage3_cadence_alert.actual_public_post_count", return_value=25
        ), patch("src.pipeline.stage3_cadence_alert.SearchConsoleClient") as search_console, patch(
            "src.pipeline.stage3_cadence_alert.NotificationClient"
        ) as notification:
            reporter.return_value._collect_articles.return_value = []
            reporter.return_value._quality_issue_count.return_value = 0
            reporter.return_value._signal_quality_result.return_value = {
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 6,
                "fallback_reddit_signal_count": 0,
            }
            reporter.return_value._operations_result.return_value = {
                "reddit_health": {
                    "status": "missing_credentials",
                    "status_label": "Reddit OAuth 키 없음",
                    "health_score": 60,
                    "blocks_cadence_increase": True,
                    "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
                }
            }
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
                verbose=False,
            )

        self.assertTrue(sent)
        message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("Reddit QUERY_PLAN 수(판단 점수 0): 6", message)
        self.assertIn("OBSERVED_QUESTION 근거 수: 0", message)
        self.assertIn("FIRST_PARTY_QUERY 근거 수: 0", message)
        self.assertIn("Reddit 앱 입력값:", message)
        self.assertIn("REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret", message)

    def test_notification_failure_is_not_silenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "src.pipeline.stage3_cadence_alert.ROOT_DIR", Path(tmpdir)
        ), patch("src.pipeline.stage3_cadence_alert.WeeklyReporter") as reporter, patch(
            "src.pipeline.stage3_cadence_alert.actual_public_post_count", return_value=25
        ), patch("src.pipeline.stage3_cadence_alert.SearchConsoleClient") as search_console, patch(
            "src.pipeline.stage3_cadence_alert.NotificationClient"
        ) as notification:
            reporter.return_value._collect_articles.return_value = []
            reporter.return_value._quality_issue_count.return_value = 0
            reporter.return_value._signal_quality_result.return_value = {
                "status": "connected",
                "reddit_oauth_signal_count": 5,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 0,
                "fallback_reddit_signal_count": 0,
                "evidence_counts_verified": True,
                "derived_evidence_counts": {
                    "live_reddit_signal_count": 5,
                    "reddit_oauth_signal_count": 5,
                    "observed_question_count": 5,
                    "first_party_query_count": 0,
                    "demand_eligible_signal_count": 5,
                },
            }
            reporter.return_value._operations_result.return_value = {
                "reddit_health": {
                    "status": "oauth_connected",
                    "health_score": 100,
                    "blocks_cadence_increase": False,
                }
            }
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
                    verbose=False,
                )

            report_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-cadence-alert-2026-07-22.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["site_key"], "easy_pc_fix_guide")
        self.assertEqual(payload["review_date"], "2026-07-22")
        self.assertEqual(payload["review"]["published_posts"], 25)
        self.assertIn("발행량 전환 검토일 알림", payload["message"])


if __name__ == "__main__":
    unittest.main()
