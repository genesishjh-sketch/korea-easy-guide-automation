from __future__ import annotations

from datetime import datetime
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.pipeline import stage4_publication_check


class PublicationCheckTests(unittest.TestCase):
    def test_run_detects_post_after_cutoff(self) -> None:
        post = {
            "title": "Fresh post",
            "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_publication_check, "fetch_public_feed", return_value={}), patch.object(
            stage4_publication_check, "parse_posts", return_value=[post]
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            result = stage4_publication_check.run(
                "easy_pc_fix_guide",
                today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                after_hour=9,
            )

        self.assertEqual(result["status"], "published_today")
        self.assertEqual(result["today_post_count"], 1)
        notification.return_value.send.assert_called_once()

    def test_main_exits_nonzero_when_public_post_is_missing(self) -> None:
        missing_result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "site_url": "https://easypcfixguide.blogspot.com",
            "checked_at_kst": "2026-06-25T09:45:00+09:00",
            "cutoff_kst": "2026-06-25T09:00:00+09:00",
            "status": "missing_today",
            "today_post_count": 0,
            "latest_posts": [],
        }

        with patch.object(stage4_publication_check, "run", return_value=missing_result), patch.object(
            stage4_publication_check, "save_result"
        ), patch("sys.argv", ["stage4_publication_check"]):
            with self.assertRaises(SystemExit) as raised:
                stage4_publication_check.main()

        self.assertEqual(raised.exception.code, 1)

    def test_save_result_writes_publication_report(self) -> None:
        result = {
            "site": "easy_pc_fix_guide",
            "status": "published_today",
            "today_post_count": 1,
        }
        path = stage4_publication_check.save_result(result)

        self.assertTrue(path.exists())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "published_today")


if __name__ == "__main__":
    unittest.main()
