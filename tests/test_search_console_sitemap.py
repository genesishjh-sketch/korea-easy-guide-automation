from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_submit_sitemap
from src.pipeline.stage3_submit_sitemap import build_indexing_guidance
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
        self.assertIn("색인 안내", message)
        self.assertIn("즉시 검색 노출을 보장하지는 않습니다", message)
        self.assertIn("Search Console > Sitemaps", message)

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

    def test_indexing_guidance_explains_wait_after_success(self) -> None:
        guidance = build_indexing_guidance({"status": "submitted"})

        self.assertEqual(guidance["status"], "submitted_waiting")
        self.assertIn("즉시 검색 노출", guidance["summary"])
        self.assertIn("며칠", guidance["expected_wait"])

    def test_indexing_guidance_blocks_wait_message_on_error(self) -> None:
        guidance = build_indexing_guidance({"status": "error"})

        self.assertEqual(guidance["status"], "needs_fix")
        self.assertIn("오류", guidance["summary"])

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
            report_path.write_text(
                json.dumps({"status": "submitted", "indexing_guidance": build_indexing_guidance({"status": "submitted"})}),
                encoding="utf-8",
            )

            with patch.object(stage3_submit_sitemap, "run", return_value=report_path), patch(
                "sys.argv", ["stage3_submit_sitemap"]
            ):
                stage3_submit_sitemap.main()

    def test_run_writes_submitted_at_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage3_submit_sitemap, "ROOT_DIR", Path(tmpdir)), patch(
            "src.pipeline.stage3_submit_sitemap.SearchConsoleClient"
        ) as client, patch("src.pipeline.stage3_submit_sitemap.NotificationClient"):
            client.return_value.submit_sitemap.return_value = {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
            }

            path = stage3_submit_sitemap.run(site="easy_pc_fix_guide")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "submitted")
        self.assertRegex(payload["submitted_at"], r"\d{4}-\d{2}-\d{2}T")
        self.assertEqual(payload["indexing_guidance"]["status"], "submitted_waiting")


if __name__ == "__main__":
    unittest.main()
