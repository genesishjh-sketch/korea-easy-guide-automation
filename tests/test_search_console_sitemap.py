from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage3_submit_sitemap
from src.pipeline.stage3_submit_sitemap import build_indexing_guidance
from src.pipeline.stage3_submit_sitemap import build_message
from src.pipeline.stage3_submit_sitemap import daily_publish_status_label


class SearchConsoleSitemapMessageTests(unittest.TestCase):
    def test_success_message_is_korean_and_contains_sitemap(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                "daily_publish_context": {
                    "status": "published",
                    "status_label": "공개 발행 완료",
                    "title": "Wi-Fi Button Missing on Windows 11",
                    "url": "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
                    "quality_score": 100,
                },
            },
        )

        self.assertIn("Search Console sitemap 제출 결과", message)
        self.assertIn("제출 완료", message)
        self.assertIn("https://easypcfixguide.blogspot.com/sitemap.xml", message)
        self.assertIn("색인 안내", message)
        self.assertIn("크롤링 요청에 가깝고 색인/검색 노출 확정은 아닙니다", message)
        self.assertIn("즉시 검색 노출을 보장하지는 않습니다", message)
        self.assertIn("24~72시간", message)
        self.assertIn("Search Console > Sitemaps", message)
        self.assertIn("URL 검사 대상: https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html", message)
        self.assertIn("연결된 일일 발행 상태: 공개 발행 완료", message)
        self.assertIn("Wi-Fi Button Missing on Windows 11", message)
        self.assertIn("https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html", message)
        self.assertIn("연결된 글 품질점수: 100", message)

    def test_success_message_contains_url_fetch_diagnostics(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                "url_fetch_diagnostics": {
                    "status": "ok",
                    "checks": [
                        {
                            "label": "latest_post",
                            "ok": True,
                            "final_status": 200,
                            "final_url": "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
                        }
                    ],
                },
            },
        )

        self.assertIn("URL 사전 점검", message)
        self.assertIn("latest_post: 정상 / 200", message)

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
        self.assertIn("Easy PC Fix Daily Publish", message)

    def test_indexing_guidance_explains_wait_after_success(self) -> None:
        guidance = build_indexing_guidance({"status": "submitted"})

        self.assertEqual(guidance["status"], "submitted_waiting")
        self.assertIn("크롤링 요청", guidance["meaning"])
        self.assertIn("즉시 검색 노출", guidance["summary"])
        self.assertIn("며칠", guidance["expected_wait"])
        self.assertIn("24~72시간", guidance["first_signal_check"])
        self.assertEqual(guidance["url_inspection_target"], "오늘 공개 글 URL")

    def test_indexing_guidance_blocks_wait_message_on_error(self) -> None:
        guidance = build_indexing_guidance({"status": "error"})

        self.assertEqual(guidance["status"], "needs_fix")
        self.assertIn("오류", guidance["summary"])
        self.assertIn("완료되지 않았습니다", guidance["meaning"])

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
        ) as client, patch("src.pipeline.stage3_submit_sitemap.NotificationClient"), patch(
            "src.pipeline.stage3_submit_sitemap.build_url_fetch_diagnostics",
            return_value={
                "status": "ok",
                "checks": [
                    {"label": "sitemap", "ok": True, "final_status": 200, "final_url": "https://easypcfixguide.blogspot.com/sitemap.xml"},
                    {
                        "label": "latest_post",
                        "ok": True,
                        "final_status": 200,
                        "final_url": "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
                    },
                ],
            },
        ):
            reports_dir = Path(tmpdir) / "reports"
            reports_dir.mkdir()
            (reports_dir / "easy_pc_fix_guide-daily-success.json").write_text(
                json.dumps(
                    {
                        "status": "published",
                        "mode": "publish",
                        "seed": "wifi button missing windows 11",
                        "title": "Wi-Fi Button Missing on Windows 11",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
                        "quality_score": 100,
                        "quality_passed": True,
                        "created_at": "2026-06-25T00:12:00Z",
                    }
                ),
                encoding="utf-8",
            )
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
        self.assertEqual(
            payload["indexing_guidance"]["url_inspection_target"],
            "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
        )
        self.assertIn("24~72시간", payload["indexing_guidance"]["first_signal_check"])
        self.assertIn("Search Console > Sitemaps", "\n".join(payload["action_items"]))
        self.assertIn(
            "https://easypcfixguide.blogspot.com/2026/06/wifi-button-missing.html",
            "\n".join(payload["action_items"]),
        )
        self.assertIn("하루 1개 발행 리듬", "\n".join(payload["action_items"]))
        self.assertIn("Search Console sitemap 제출 결과", payload["human_summary"])
        self.assertEqual(payload["url_fetch_diagnostics"]["status"], "ok")
        self.assertEqual(payload["daily_publish_context"]["status"], "published")
        self.assertEqual(payload["daily_publish_context"]["status_label"], "공개 발행 완료")
        self.assertEqual(payload["daily_publish_context"]["title"], "Wi-Fi Button Missing on Windows 11")
        self.assertEqual(payload["daily_publish_context"]["quality_score"], 100)

    def test_run_skips_sitemap_telegram_notification_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage3_submit_sitemap, "ROOT_DIR", Path(tmpdir)), patch(
            "src.pipeline.stage3_submit_sitemap.SearchConsoleClient"
        ) as client, patch("src.pipeline.stage3_submit_sitemap.NotificationClient") as notification, patch(
            "src.pipeline.stage3_submit_sitemap.build_url_fetch_diagnostics", return_value={"status": "ok", "checks": []}
        ):
            client.return_value.submit_sitemap.return_value = {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
            }

            stage3_submit_sitemap.run(site="easy_pc_fix_guide")

        notification.assert_not_called()

    def test_run_sends_sitemap_telegram_notification_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage3_submit_sitemap, "ROOT_DIR", Path(tmpdir)), patch(
            "src.pipeline.stage3_submit_sitemap.SearchConsoleClient"
        ) as client, patch("src.pipeline.stage3_submit_sitemap.NotificationClient") as notification, patch(
            "src.pipeline.stage3_submit_sitemap.build_url_fetch_diagnostics", return_value={"status": "ok", "checks": []}
        ):
            client.return_value.submit_sitemap.return_value = {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
            }

            stage3_submit_sitemap.run(site="easy_pc_fix_guide", notify=True)

        notification.return_value.send_required.assert_called_once()
        message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("Search Console sitemap 제출 결과", message)

    def test_daily_publish_status_label_describes_daily_limit_skip(self) -> None:
        self.assertEqual(
            daily_publish_status_label("skipped_daily_limit"),
            "오늘 공개 글 이미 있어 추가 발행 건너뜀",
        )


if __name__ == "__main__":
    unittest.main()
