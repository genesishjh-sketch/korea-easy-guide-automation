from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.config import load_settings
from src.reporting.weekly import WeeklyReporter


class WeeklyReportPublicFeedTests(unittest.TestCase):
    def test_collects_recent_blogger_feed_posts(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        post = {
            "title": "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
            "url": "https://easypcfixguide.blogspot.com/2026/06/wi-fi-button-missing-on-windows-11.html",
            "published_kst": datetime.now(tz=ZoneInfo("Asia/Seoul")) - timedelta(days=1),
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "src.reporting.weekly.fetch_public_feed", return_value={}
        ), patch("src.reporting.weekly.parse_posts", return_value=[post]):
            reporter = WeeklyReporter(replace(settings, generated_output_dir=str(Path(tmpdir))))
            result = reporter._collect_public_posts(datetime.utcnow() - timedelta(days=7))

        self.assertEqual(result["status"], "connected")
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["posts"][0]["url"], post["url"])

    def test_public_feed_error_is_reported_without_breaking_weekly_report(self) -> None:
        settings = load_settings("easy_pc_fix_guide")

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "src.reporting.weekly.fetch_public_feed", side_effect=RuntimeError("feed unavailable")
        ):
            reporter = WeeklyReporter(replace(settings, generated_output_dir=str(Path(tmpdir))))
            result = reporter._collect_public_posts(datetime.utcnow() - timedelta(days=7))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["posts"], [])
        self.assertIn("feed unavailable", result["error"])

    def test_markdown_includes_public_feed_section(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        markdown = reporter._to_markdown(
            {
                "site_name": settings.site_name,
                "site_url": settings.site_url,
                "week_start": "2026-06-18",
                "week_end": "2026-06-25",
                "article_count": 0,
                "draft_count": 0,
                "published_count": 1,
                "local_published_count": 0,
                "articles": [],
                "public_posts": {
                    "status": "connected",
                    "posts": [
                        {
                            "title": "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/wi-fi-button-missing-on-windows-11.html",
                            "published_kst": "2026-06-25T09:12:00+09:00",
                        }
                    ],
                },
                "static_pages": [],
                "search_console": {"status": "not_configured", "note": "test"},
                "analytics": {"status": "not_configured", "note": "test"},
                "operations": {
                    "daily_success": {
                        "status": "published",
                        "title": "Wi-Fi Button Missing on Windows 11",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                        "quality_score": 100,
                    },
                    "daily_failure": {"status": "not_uploaded"},
                    "preflight": {"status": "pass", "checks": []},
                    "publication_check": {"status": "published_today", "today_post_count": 1},
                    "sitemap_submit": {
                        "status": "submitted",
                        "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                    },
                },
                "cadence_review": {},
                "next_actions": [],
            }
        )

        self.assertIn("## Blogger 공개 피드 확인", markdown)
        self.assertIn("최근 7일 공개 피드 글 수: 1", markdown)
        self.assertIn("Wi-Fi Button Missing on Windows 11", markdown)
        self.assertIn("## 운영 점검", markdown)
        self.assertIn("최근 일일 성공 리포트: 공개 발행", markdown)
        self.assertIn("품질점수: 100/100", markdown)
        self.assertIn("최근 일일 실패 리포트: 미업로드", markdown)
        self.assertIn("Preflight: 통과", markdown)
        self.assertIn("발행 확인: 오늘 공개 글 확인", markdown)
        self.assertIn("Sitemap 제출: 제출됨", markdown)

    def test_next_actions_do_not_ask_for_first_article_when_public_feed_has_posts(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={
                "status": "connected",
                "posts": [
                    {
                        "title": "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/wi-fi-button-missing-on-windows-11.html",
                    }
                ],
            },
        )

        joined = "\n".join(actions)
        self.assertNotIn("최소 1개의 글 초안을 생성하세요.", joined)
        self.assertNotIn("공개 글이 생긴 뒤 Search Console 연결을 확인하세요.", joined)

    def test_next_actions_include_operations_failures(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "daily_failure": {"status": "failed"},
                "preflight": {"status": "fail"},
                "publication_check": {"status": "missing_today"},
                "sitemap_submit": {"status": "error"},
            },
        )

        joined = "\n".join(actions)
        self.assertIn("Preflight 실패", joined)
        self.assertIn("최근 일일 자동화 실패 리포트", joined)
        self.assertIn("오늘 공개 글을 찾지 못했습니다", joined)
        self.assertIn("sitemap 제출 실패", joined)

    def test_operations_result_reads_daily_success_and_failure_reports(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-daily-success.json").write_text(
                '{"status":"published","title":"Published post"}',
                encoding="utf-8",
            )
            (report_dir / "easy_pc_fix_guide-daily-failure.json").write_text(
                '{"status":"failed","error":"boom"}',
                encoding="utf-8",
            )

            operations = reporter._operations_result()

        self.assertEqual(operations["daily_success"]["status"], "published")
        self.assertEqual(operations["daily_failure"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
