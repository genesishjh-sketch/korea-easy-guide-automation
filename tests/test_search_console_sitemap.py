from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_submit_sitemap
from src.pipeline.stage3_submit_sitemap import build_message


class SearchConsoleSitemapMessageTests(unittest.TestCase):
    def test_success_message_is_korean_and_contains_sitemap(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
            },
        )

        self.assertIn("Search Console sitemap 제출 결과", message)
        self.assertIn("제출 완료", message)
        self.assertIn("https://easypcfixguide.blogspot.com/sitemap.xml", message)

    def test_error_message_contains_action_items(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "error",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                "error": "permission denied",
            },
        )

        self.assertIn("제출 실패", message)
        self.assertIn("permission denied", message)
        self.assertIn("조치 필요", message)

    def test_main_exits_nonzero_when_sitemap_submit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "sitemap.json"
            report_path.write_text(json.dumps({"status": "error", "error": "permission denied"}), encoding="utf-8")

            with patch.object(stage3_submit_sitemap, "run", return_value=report_path), patch(
                "sys.argv", ["stage3_submit_sitemap"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    stage3_submit_sitemap.main()

        self.assertEqual(raised.exception.code, 1)

    def test_main_accepts_successful_sitemap_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "sitemap.json"
            report_path.write_text(json.dumps({"status": "submitted"}), encoding="utf-8")

            with patch.object(stage3_submit_sitemap, "run", return_value=report_path), patch(
                "sys.argv", ["stage3_submit_sitemap"]
            ):
                stage3_submit_sitemap.main()


if __name__ == "__main__":
    unittest.main()
