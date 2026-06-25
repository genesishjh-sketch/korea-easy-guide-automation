from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import json
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
                "signal_quality": {
                    "status": "fallback_only",
                    "article_count_with_research": 1,
                    "live_reddit_signal_count": 0,
                    "reddit_oauth_signal_count": 0,
                    "reddit_public_json_signal_count": 0,
                    "fallback_reddit_signal_count": 2,
                    "google_suggest_signal_count": 3,
                    "fallback_only_articles": ["Wi-Fi Button Missing on Windows 11"],
                },
                "search_console": {"status": "not_configured", "note": "test"},
                "analytics": {"status": "not_configured", "note": "test"},
                "operations": {
                    "daily_success": {
                        "status": "validated",
                        "mode": "validate",
                        "title": "Wi-Fi Button Missing on Windows 11",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                        "quality_score": 100,
                        "operational_status": {
                            "publish_quality_ok": True,
                            "collection_status": "fallback_only",
                            "collection_status_label": "주의: fallback 질문 의존",
                            "ready_for_cadence_increase": False,
                            "status_label": "발행 품질 OK, 수집 안정성 점검 필요",
                        },
                    },
                    "daily_failure": {"status": "not_uploaded"},
                    "reddit_health": {
                        "status": "missing_credentials",
                        "status_label": "Reddit OAuth 키 없음",
                        "health_score": 0,
                        "blocks_cadence_increase": True,
                        "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
                    },
                    "preflight": {
                        "status": "pass",
                        "checks": [
                            {
                                "name": "seed_inventory",
                                "status": "pass",
                                "message": "83/103 exact-match topic seeds remain unused.",
                            }
                        ],
                    },
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
        self.assertIn("최근 일일 성공 리포트: 검증 완료", markdown)
        self.assertIn("리포트 구분: 검증 모드 리포트", markdown)
        self.assertIn("공개 발행 결과가 아닙니다", markdown)
        self.assertIn("품질점수: 100/100", markdown)
        self.assertIn("운영 상태: 발행 품질 OK, 수집 안정성 점검 필요", markdown)
        self.assertIn("발행량 증량 준비: 아니오", markdown)
        self.assertIn("최근 일일 실패 리포트: 미업로드", markdown)
        self.assertIn("Preflight: 통과", markdown)
        self.assertIn("시드 재고: 통과 - 83/103 exact-match topic seeds remain unused.", markdown)
        self.assertIn("Reddit OAuth Health: Reddit OAuth 키 없음", markdown)
        self.assertIn("상태 점수: 0/100", markdown)
        self.assertIn("발행량 증량 차단: 예", markdown)
        self.assertIn("발행 확인: 오늘 공개 글 확인", markdown)
        self.assertIn("Sitemap 제출: 제출됨", markdown)
        self.assertIn("## 수집 신호 품질", markdown)
        self.assertIn("Reddit OAuth 신호 수: 0", markdown)
        self.assertIn("Reddit public JSON 신호 수: 0", markdown)
        self.assertIn("Reddit fallback 신호 수: 2", markdown)
        self.assertIn("fallback만 사용한 글", markdown)

    def test_signal_quality_result_summarizes_research_reports(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        with tempfile.TemporaryDirectory() as tmpdir:
            article_one = Path(tmpdir) / "one"
            article_two = Path(tmpdir) / "two"
            article_one.mkdir()
            article_two.mkdir()
            (article_one / "research_report.json").write_text(
                json.dumps(
                    {
                        "live_reddit_signal_count": 0,
                        "reddit_oauth_signal_count": 0,
                        "reddit_public_json_signal_count": 0,
                        "fallback_reddit_signal_count": 2,
                        "google_suggest_signal_count": 4,
                        "signal_source_counts": {"reddit_fallback": 2, "google_suggest": 4},
                        "reddit_collection_method_counts": {"fallback": 2},
                    }
                ),
                encoding="utf-8",
            )
            (article_two / "research_report.json").write_text(
                json.dumps(
                    {
                        "live_reddit_signal_count": 3,
                        "reddit_oauth_signal_count": 2,
                        "reddit_public_json_signal_count": 1,
                        "fallback_reddit_signal_count": 1,
                        "google_suggest_signal_count": 2,
                        "signal_source_counts": {"reddit": 3, "reddit_fallback": 1, "google_suggest": 2},
                        "reddit_collection_method_counts": {"oauth": 2, "public_json": 1, "fallback": 1},
                    }
                ),
                encoding="utf-8",
            )

            result = reporter._signal_quality_result(
                [
                    {"title": "Fallback only article", "article_dir": str(article_one)},
                    {"title": "Live Reddit article", "article_dir": str(article_two)},
                ]
            )

        self.assertEqual(result["status"], "fallback_only")
        self.assertEqual(result["article_count_with_research"], 2)
        self.assertEqual(result["live_reddit_signal_count"], 3)
        self.assertEqual(result["reddit_oauth_signal_count"], 2)
        self.assertEqual(result["reddit_public_json_signal_count"], 1)
        self.assertEqual(result["fallback_reddit_signal_count"], 3)
        self.assertEqual(result["google_suggest_signal_count"], 6)
        self.assertEqual(result["signal_source_counts"]["reddit"], 3)
        self.assertEqual(result["reddit_collection_method_counts"]["oauth"], 2)
        self.assertEqual(result["reddit_collection_method_counts"]["public_json"], 1)
        self.assertEqual(result["fallback_only_articles"], ["Fallback only article"])

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

    def test_next_actions_include_signal_quality_fallback_warning(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={"preflight": {"status": "pass"}},
            signal_quality={"status": "fallback_only"},
        )

        joined = "\n".join(actions)
        self.assertIn("Reddit OAuth 설정", joined)
        self.assertIn("fallback 질문만 사용", joined)
        self.assertIn("https://www.reddit.com/prefs/apps", joined)
        self.assertIn("REDDIT_CLIENT_ID", joined)

    def test_next_actions_include_public_json_only_warning(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={"preflight": {"status": "pass"}},
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 4,
            },
        )

        joined = "\n".join(actions)
        self.assertIn("public JSON", joined)
        self.assertIn("Reddit OAuth 수집", joined)
        self.assertIn("https://www.reddit.com/prefs/apps", joined)
        self.assertIn("REDDIT_CLIENT_SECRET", joined)

    def test_next_actions_include_operational_status_cadence_warning(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {"status": "pass"},
                "daily_success": {
                    "status": "published",
                    "operational_status": {
                        "publish_quality_ok": True,
                        "collection_status": "fallback_only",
                        "ready_for_cadence_increase": False,
                    },
                },
            },
            signal_quality={"status": "fallback_only"},
        )

        joined = "\n".join(actions)
        self.assertIn("아직 발행량 증량 준비가 아닙니다", joined)
        self.assertIn("Reddit OAuth 수집 안정성", joined)

    def test_next_actions_include_reddit_health_cadence_block(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {"status": "pass"},
                "reddit_health": {
                    "status": "missing_credentials",
                    "health_score": 0,
                    "blocks_cadence_increase": True,
                    "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Reddit OAuth Health가 발행량 증량을 차단 중", joined)
        self.assertIn("상태 점수: 0/100", joined)
        self.assertIn("REDDIT_CLIENT_ID", joined)

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
            (report_dir / "easy_pc_fix_guide-reddit-health.json").write_text(
                '{"status":"oauth_connected","collection_status":"stable_oauth","health_score":100,"blocks_cadence_increase":false}',
                encoding="utf-8",
            )

            operations = reporter._operations_result()

        self.assertEqual(operations["daily_success"]["status"], "published")
        self.assertEqual(operations["daily_success_context"]["status"], "publish_related")
        self.assertEqual(operations["daily_failure"]["status"], "failed")
        self.assertEqual(operations["reddit_health"]["status"], "oauth_connected")
        self.assertEqual(operations["reddit_health"]["health_score"], 100)

    def test_operations_result_falls_back_to_public_feed_when_artifacts_are_not_persisted(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            operations = reporter._operations_result(
                now=now,
                public_posts={
                    "status": "connected",
                    "posts": [
                        {
                            "title": "Wi-Fi Button Missing on Windows 11",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                            "published_kst": "2026-06-25T09:12:00+09:00",
                        }
                    ],
                },
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["publication_check"]["status"], "published_today")
        self.assertEqual(operations["publication_check"]["today_post_count"], 1)
        self.assertEqual(operations["publication_check"]["source"], "weekly_public_feed_fallback")
        self.assertEqual(operations["sitemap_submit"]["status"], "not_persisted")

    def test_operations_result_accepts_today_post_before_cutoff(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            operations = reporter._operations_result(
                now=now,
                public_posts={
                    "status": "connected",
                    "posts": [
                        {
                            "title": "Early post",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/early-post.html",
                            "published_kst": "2026-06-25T00:12:00+09:00",
                        }
                    ],
                },
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["publication_check"]["status"], "published_today_before_cutoff")
        self.assertEqual(operations["publication_check"]["today_post_count"], 0)
        self.assertEqual(operations["publication_check"]["today_total_post_count"], 1)


if __name__ == "__main__":
    unittest.main()
