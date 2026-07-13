from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.pipeline import stage4_missing_publish_alert


class MissingPublishAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.object(stage4_missing_publish_alert, "ROOT_DIR", Path(self._tmpdir.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_run_skips_notification_when_all_sites_have_today_post(self) -> None:
        today = datetime(2026, 7, 2, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        post = {
            "title": "Today post",
            "url": "https://example.blogspot.com/today.html",
            "published_kst": today,
        }

        with patch.object(stage4_missing_publish_alert, "fetch_public_feed", return_value={}), patch.object(
            stage4_missing_publish_alert, "parse_posts", return_value=[post]
        ), patch("src.pipeline.stage4_missing_publish_alert.NotificationClient") as notification:
            result = stage4_missing_publish_alert.run(["easy_pc_fix_guide", "korea_easy_guide"], today=today)

        self.assertEqual(result["status"], "ok")
        notification.assert_not_called()

    def test_run_sends_notification_when_a_site_has_no_today_post(self) -> None:
        today = datetime(2026, 7, 2, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        old_post = {
            "title": "Yesterday post",
            "url": "https://example.blogspot.com/yesterday.html",
            "published_kst": datetime(2026, 7, 1, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_missing_publish_alert, "fetch_public_feed", return_value={}), patch.object(
            stage4_missing_publish_alert, "parse_posts", return_value=[old_post]
        ), patch("src.pipeline.stage4_missing_publish_alert.NotificationClient") as notification:
            result = stage4_missing_publish_alert.run(["easy_pc_fix_guide"], today=today)

        self.assertEqual(result["status"], "missing_publication")
        notification.return_value.send_required.assert_called_once()
        message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("발행 누락 경고", message)
        self.assertIn("Easy PC Fix Guide", message)
        self.assertIn("누락은 알림으로 끝내지 말고 복구 대상으로 처리", message)
        self.assertIn("Hades 품질검수", message)

    def test_missing_message_includes_recovery_report_status(self) -> None:
        today = datetime(2026, 7, 2, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        reports = Path(self._tmpdir.name) / "reports"
        reports.mkdir(parents=True)
        (reports / "easy_pc_fix_guide-daily-recovery-report.json").write_text(
            json.dumps(
                {
                    "status": "codex_image_required",
                    "target_posts": 3,
                    "public_total_after_batch": 1,
                    "missing_count": 2,
                    "next_actions": ["Codex 이미지 복구 필요: 새 JPG 이미지를 생성하세요."],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        old_post = {
            "title": "Yesterday post",
            "url": "https://example.blogspot.com/yesterday.html",
            "published_kst": datetime(2026, 7, 1, 14, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_missing_publish_alert, "fetch_public_feed", return_value={}), patch.object(
            stage4_missing_publish_alert, "parse_posts", return_value=[old_post]
        ), patch("src.pipeline.stage4_missing_publish_alert.NotificationClient") as notification:
            stage4_missing_publish_alert.run(["easy_pc_fix_guide"], today=today)

        message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("복구 상태: codex_image_required", message)
        self.assertIn("복구 후 공개 수: 1/3", message)
        self.assertIn("Codex 이미지 복구 필요", message)

    def test_run_reports_feed_errors_as_attention_needed(self) -> None:
        today = datetime(2026, 7, 2, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        with patch.object(stage4_missing_publish_alert, "fetch_public_feed", side_effect=RuntimeError("feed down")), patch(
            "src.pipeline.stage4_missing_publish_alert.NotificationClient"
        ) as notification:
            result = stage4_missing_publish_alert.run(["korea_easy_guide"], today=today)

        self.assertEqual(result["status"], "missing_publication")
        self.assertEqual(result["missing_sites"][0]["status"], "feed_error")
        notification.return_value.send_required.assert_called_once()


if __name__ == "__main__":
    unittest.main()
