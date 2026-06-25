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
from src.reporting.weekly import monitoring_review_items


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

    def test_collect_articles_includes_seed_and_content_domain(self) -> None:
        settings = load_settings("easy_pc_fix_guide")

        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "2026-06-25" / "bluetooth-not-working"
            article_dir.mkdir(parents=True)
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {
                            "title": "Bluetooth Not Working on Windows",
                            "slug": "bluetooth-not-working",
                            "category": "Bluetooth & Devices",
                            "tags": ["Bluetooth"],
                        },
                        "candidate": {
                            "keyword": "bluetooth not working windows 11",
                            "category": "Bluetooth & Devices",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "seed_keyword": "bluetooth not working windows 11",
                        "content_domain": "windows_help",
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "validation_result.json").write_text(
                json.dumps({"mode": "validate", "passed": True}),
                encoding="utf-8",
            )

            reporter = WeeklyReporter(replace(settings, generated_output_dir=str(Path(tmpdir))))
            result = reporter._collect_articles(datetime.utcnow() - timedelta(days=7))

        self.assertEqual(result[0]["seed_keyword"], "bluetooth not working windows 11")
        self.assertEqual(result[0]["content_domain"], "windows_help")
        self.assertEqual(result[0]["article_status"], "validated")

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
                    "reddit_collection_diagnostics": [
                        {
                            "title": "Wi-Fi Button Missing on Windows 11",
                            "status": "fallback_only",
                            "oauth_configured": False,
                            "public_json_error_count": 4,
                            "failed_subreddits": ["WindowsHelp", "Windows11"],
                            "fallback_reason": "All available Reddit live collection paths returned no usable signals; public JSON had errors.",
                            "oauth_error": "",
                        }
                    ],
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
                        "seed_attempt_summary": {
                            "attempted_seed_count": 3,
                            "selected_seed": "wifi button missing windows 11",
                            "duplicate_skip_count": 1,
                            "quality_retry_count": 1,
                            "attempted_seeds": [
                                "thin windows update topic",
                                "wifi button missing windows 11",
                                "fresh windows search topic",
                            ],
                        },
                        "skipped_duplicate_seeds": ["wifi button missing windows 11"],
                        "skipped_quality_seeds": ["thin windows update topic"],
                    },
                    "daily_failure": {"status": "not_uploaded"},
                    "reddit_health": {
                        "status": "missing_credentials",
                        "status_label": "Reddit OAuth 키 없음",
                        "health_score": 0,
                        "blocks_cadence_increase": True,
                        "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
                        "query_attempt_count": 2,
                        "query_attempts": [
                            {
                                "query": "rare windows error",
                                "status": "oauth_connected_no_results",
                                "oauth_signal_count": 0,
                            },
                            {
                                "query": "windows update error",
                                "status": "oauth_connected",
                                "oauth_signal_count": 3,
                            },
                        ],
                        "per_subreddit_counts": {"WindowsHelp": 0, "Windows11": 3},
                        "setup_links": {
                            "recommended_app_type": "script",
                            "recommended_redirect_uri": "http://localhost:8080",
                            "github_secret_mapping": [
                                "REDDIT_CLIENT_ID = Reddit 앱 이름 아래에 표시되는 client id",
                                "REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret",
                                "EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT = 권장 User-Agent 문자열",
                            ],
                            "user_action_checklist": [
                                "Reddit 앱 페이지에서 create app 또는 create another app을 누르고 이름을 'Easy PC Fix Guide Automation'로 입력하세요.",
                                "앱 타입은 반드시 script를 선택하세요. web app이나 installed app이 아닙니다.",
                                "redirect uri에는 http://localhost:8080를 그대로 입력하세요.",
                                "생성 후 앱 이름 아래의 짧은 client id를 GitHub Secret REDDIT_CLIENT_ID에 저장하세요.",
                                "앱 상세의 secret 값을 GitHub Secret REDDIT_CLIENT_SECRET에 저장하세요.",
                                "GitHub Variable EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT가 비어 있으면 'easy-pc-fix-guide/0.1 by posting-automation-alert-bot'로 저장하세요.",
                                "저장 후 Actions > Easy PC Fix Reddit OAuth Health workflow를 Run workflow로 실행하세요.",
                            ],
                        },
                    },
                    "preflight": {
                        "status": "pass",
                        "readiness": {
                            "ready_for_unattended_publish": True,
                            "ready_for_cadence_increase": False,
                            "required_user_action_count": 1,
                        },
                        "setup_actions": [
                            {
                                "name": "reddit_oauth",
                                "label": "Reddit OAuth 연결",
                                "status": "warn",
                                "urgency": "before_cadence_increase",
                                "next_step": "Reddit script app을 만들고 REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets에 저장한 뒤 Easy PC Fix Reddit OAuth Health workflow를 수동 실행하세요.",
                            }
                        ],
                        "checks": [
                            {
                                "name": "seed_inventory",
                                "status": "pass",
                                "message": "83/103 exact-match topic seeds remain unused.",
                            },
                            {
                                "name": "all_seed_quality",
                                "status": "pass",
                                "message": "103/103 long-term topics have specific categories and enough Microsoft sources.",
                            },
                            {
                                "name": "launch_queue_quality",
                                "status": "pass",
                                "message": "14/14 launch topics have specific categories and enough Microsoft sources.",
                            },
                        ],
                    },
                    "publication_check": {
                        "status": "published_today",
                        "today_post_count": 1,
                        "publication_evidence": {
                            "status": "feed_and_workflow_confirmed_report_not_publish",
                            "label": "공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님",
                            "note": "최근 일일 성공 리포트는 validate 실행 결과이며 공개 발행 결과가 아닙니다.",
                            "needs_attention": True,
                        },
                    },
                    "sitemap_submit": {
                        "status": "submitted",
                        "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                        "indexing_guidance": {
                            "status": "submitted_waiting",
                            "summary": "sitemap 제출은 Google에 새 글을 알려주는 단계이며, 즉시 검색 노출을 보장하지는 않습니다.",
                            "expected_wait": "보통 며칠, 새 블로그는 더 오래 걸릴 수 있음",
                            "check_location": "Search Console > Sitemaps, URL 검사, 페이지 색인 생성",
                        },
                    },
                },
                "cadence_review": {
                    "action": "하루 1개 유지",
                    "days_since_start": 2,
                    "published_posts": 1,
                    "indexed_pages_estimate": 0,
                    "recent_impressions": 0,
                    "quality_issue_count": 0,
                    "signal_quality_status": "fallback_only",
                    "reddit_oauth_signal_count": 0,
                    "reddit_public_json_signal_count": 0,
                    "fallback_reddit_signal_count": 2,
                    "reddit_health_status": "missing_credentials",
                    "reddit_health_score": 0,
                    "reddit_health_blocks_cadence_increase": True,
                    "two_post_review_date": "2026-07-22",
                    "three_post_review_date": "2026-08-19",
                    "reasons": ["Reddit OAuth Health가 발행량 증량을 차단 중입니다: Reddit OAuth 키 없음."],
                },
                "quality_issues": [
                    {
                        "title": "Windows Update Error 0x80070643",
                        "code": "missing_required_image_assets",
                        "message": "Missing image assets: assets/ai-hero.jpg, assets/ai-inline-1.jpg.",
                        "severity": "error",
                    }
                ],
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
        self.assertIn("시드 시도 수: 3", markdown)
        self.assertIn("최종 선택 시드: wifi button missing windows 11", markdown)
        self.assertIn("중복 스킵 수: 1", markdown)
        self.assertIn("품질 재시도 수: 1", markdown)
        self.assertEqual(markdown.count("- 초안 글 수:"), 1)
        self.assertEqual(markdown.count("최종 선택 시드: wifi button missing windows 11"), 1)
        self.assertIn("중복으로 건너뛴 시드 수: 1", markdown)
        self.assertIn("중복 시드: wifi button missing windows 11", markdown)
        self.assertIn("품질검수 실패로 재시도한 시드 수: 1", markdown)
        self.assertIn("품질 재시도 시드: thin windows update topic", markdown)
        self.assertIn("운영 상태: 발행 품질 OK, 수집 안정성 점검 필요", markdown)
        self.assertIn("발행량 증량 준비: 아니오", markdown)
        self.assertIn("최근 일일 실패 리포트: 미업로드", markdown)
        self.assertIn("Preflight: 통과", markdown)
        self.assertIn("무인 발행 준비: 예", markdown)
        self.assertIn("필요 사용자 조치 수: 1", markdown)
        self.assertIn("Reddit OAuth 연결: 주의 / before_cadence_increase", markdown)
        self.assertIn("Easy PC Fix Reddit OAuth Health workflow를 수동 실행하세요.", markdown)
        self.assertIn("시드 재고: 통과 - 83/103 exact-match topic seeds remain unused.", markdown)
        self.assertIn("장기 시드 품질: 통과 - 103/103 long-term topics have specific categories", markdown)
        self.assertIn("Launch queue 품질: 통과 - 14/14 launch topics have specific categories", markdown)
        self.assertIn("Reddit OAuth Health: Reddit OAuth 키 없음", markdown)
        self.assertIn("상태 점수: 0/100", markdown)
        self.assertIn("발행량 증량 차단: 예", markdown)
        self.assertIn("검색어 재시도 수: 2", markdown)
        self.assertIn("rare windows error: OAuth 연결됨, 결과 없음 / OAuth 신호 0개", markdown)
        self.assertIn("windows update error: OAuth 연결 확인 / OAuth 신호 3개", markdown)
        self.assertIn("subreddit별 결과: WindowsHelp 0개, Windows11 3개", markdown)
        self.assertIn("Reddit 앱 타입: script", markdown)
        self.assertIn("Redirect URI: http://localhost:8080", markdown)
        self.assertIn("REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret", markdown)
        self.assertIn("사용자가 직접 할 일", markdown)
        self.assertIn("앱 타입은 반드시 script를 선택하세요.", markdown)
        self.assertIn("Easy PC Fix Reddit OAuth Health workflow를 Run workflow로 실행하세요.", markdown)
        self.assertIn("발행 확인: 오늘 공개 글 확인", markdown)
        self.assertIn("발행 증거 판정: 공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님", markdown)
        self.assertIn("추가 확인 필요: 예", markdown)
        self.assertIn("Sitemap 제출: 제출됨", markdown)
        self.assertIn("색인 안내: sitemap 제출은 Google에 새 글을 알려주는 단계", markdown)
        self.assertIn("예상 대기: 보통 며칠", markdown)
        self.assertIn("확인 위치: Search Console > Sitemaps", markdown)
        self.assertIn("## 수집 신호 품질", markdown)
        self.assertIn("Reddit OAuth 신호 수: 0", markdown)
        self.assertIn("Reddit public JSON 신호 수: 0", markdown)
        self.assertIn("Reddit fallback 신호 수: 2", markdown)
        self.assertIn("fallback만 사용한 글", markdown)
        self.assertIn("최근 Reddit 수집 진단", markdown)
        self.assertIn("public JSON 실패 4개", markdown)
        self.assertIn("실패 subreddit: WindowsHelp, Windows11", markdown)
        self.assertIn("fallback 이유: All available Reddit live collection paths returned no usable signals", markdown)
        self.assertIn("## 발행량 전환 검토", markdown)
        self.assertIn("Reddit Health 상태: Reddit OAuth 키 없음", markdown)
        self.assertIn("Reddit Health 점수: 0/100", markdown)
        self.assertIn("Reddit Health 증량 차단: 예", markdown)
        self.assertIn("## 2~3주 모니터링", markdown)
        self.assertIn("2주 점검일: 2026-07-08", markdown)
        self.assertIn("3주 점검일: 2026-07-15", markdown)
        self.assertIn("Reddit OAuth Health", markdown)
        self.assertIn("품질 이슈 상세", markdown)
        self.assertIn("Windows Update Error 0x80070643", markdown)
        self.assertIn("missing_required_image_assets", markdown)

    def test_monitoring_review_items_flag_user_attention_after_two_weeks(self) -> None:
        items = monitoring_review_items(
            {
                "week_end": "2026-07-08",
                "published_count": 14,
                "quality_issues": [],
                "indexed_pages": {"page_count_with_search_data": 0},
                "search_console": {"totals_from_top_queries": {"impressions": 0}},
                "operations": {
                    "daily_success": {"seed_attempt_summary": {"attempted_seed_count": 2}},
                    "reddit_health": {"status": "missing_credentials"},
                    "publication_check": {"status": "published_today"},
                },
            }
        )

        self.assertEqual(items[0]["label"], "2주차 안정성 점검")
        self.assertEqual(items[0]["status_label"], "점검 필요")
        self.assertEqual(items[0]["target_date"], "2026-07-08")
        self.assertEqual(items[0]["reddit_health_status"], "missing_credentials")

    def test_markdown_article_list_includes_seed_and_domain(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        markdown = reporter._to_markdown(
            {
                "site_name": settings.site_name,
                "site_url": settings.site_url,
                "week_start": "2026-06-18",
                "week_end": "2026-06-25",
                "article_count": 1,
                "draft_count": 0,
                "published_count": 1,
                "local_published_count": 1,
                "articles": [
                    {
                        "title": "Bluetooth Not Working on Windows",
                        "seed_keyword": "bluetooth not working windows 11",
                        "content_domain": "windows_help",
                        "category": "Bluetooth & Devices",
                        "blogger_status": "LIVE",
                        "article_status": "LIVE",
                    }
                ],
                "public_posts": {"status": "connected", "posts": []},
                "static_pages": [],
                "signal_quality": {},
                "search_console": {"status": "not_configured"},
                "analytics": {"status": "not_configured"},
                "operations": {},
                "cadence_review": {},
                "quality_issues": [],
                "next_actions": [],
            }
        )

        self.assertIn("| 제목 | 시드 | 도메인 | 카테고리 | 처리 상태 |", markdown)
        self.assertIn("bluetooth not working windows 11", markdown)
        self.assertIn("windows_help", markdown)

    def test_markdown_article_list_marks_validation_only_articles(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        markdown = reporter._to_markdown(
            {
                "site_name": settings.site_name,
                "site_url": settings.site_url,
                "week_start": "2026-06-18",
                "week_end": "2026-06-25",
                "article_count": 1,
                "draft_count": 0,
                "published_count": 0,
                "local_published_count": 0,
                "articles": [
                    {
                        "title": "Bluetooth Not Working on Windows",
                        "seed_keyword": "bluetooth not working windows 11",
                        "content_domain": "windows_help",
                        "category": "Bluetooth & Devices",
                        "article_status": "validated",
                    }
                ],
                "public_posts": {"status": "connected", "posts": []},
                "static_pages": [],
                "signal_quality": {},
                "search_console": {"status": "not_configured"},
                "analytics": {"status": "not_configured"},
                "operations": {},
                "cadence_review": {},
                "quality_issues": [],
                "next_actions": [],
            }
        )

        self.assertIn("검증 완료", markdown)
        self.assertNotIn("미업로드", markdown.split("## Blogger 공개 피드 확인")[0])

    def test_quality_issues_result_summarizes_article_quality_reports(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "article"
            article_dir.mkdir()
            (article_dir / "quality_report.json").write_text(
                json.dumps(
                    {
                        "score": 88,
                        "passed": False,
                        "issues": [
                            {
                                "code": "missing_required_image_assets",
                                "message": "Missing image assets: assets/ai-hero.jpg, assets/ai-inline-1.jpg.",
                                "severity": "error",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = reporter._quality_issues_result(
                [
                    {
                        "title": "Windows Update Error 0x80070643",
                        "article_dir": str(article_dir),
                        "article_status": "failed",
                    }
                ]
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Windows Update Error 0x80070643")
        self.assertEqual(result[0]["code"], "missing_required_image_assets")

    def test_quality_issues_ignore_orphan_generated_candidates(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "orphan"
            article_dir.mkdir()
            (article_dir / "quality_report.json").write_text(
                json.dumps(
                    {
                        "score": 88,
                        "passed": False,
                        "issues": [
                            {
                                "code": "topic_alignment_mismatch",
                                "message": "Discarded fallback candidate did not match the seed.",
                                "severity": "error",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = reporter._quality_issues_result(
                [
                    {
                        "title": "Discarded Candidate",
                        "article_dir": str(article_dir),
                        "article_status": "not_uploaded",
                        "blogger_status": None,
                    }
                ]
            )
            issue_count = reporter._quality_issue_count(
                [
                    {
                        "title": "Discarded Candidate",
                        "article_dir": str(article_dir),
                        "article_status": "not_uploaded",
                        "blogger_status": None,
                    }
                ]
            )

        self.assertEqual(result, [])
        self.assertEqual(issue_count, 0)

    def test_quality_issues_ignore_failed_candidate_when_same_seed_later_passed(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        with tempfile.TemporaryDirectory() as tmpdir:
            failed_dir = Path(tmpdir) / "failed"
            passed_dir = Path(tmpdir) / "passed"
            failed_dir.mkdir()
            passed_dir.mkdir()
            (failed_dir / "quality_report.json").write_text(
                json.dumps(
                    {
                        "score": 88,
                        "passed": False,
                        "issues": [
                            {
                                "code": "topic_alignment_mismatch",
                                "message": "First generated candidate did not match the seed.",
                                "severity": "error",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (passed_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "issues": []}),
                encoding="utf-8",
            )
            articles = [
                {
                    "title": "Wi-Fi Button Missing on Windows 11",
                    "article_dir": str(failed_dir),
                    "seed_keyword": "wifi keeps disconnecting windows 11",
                    "article_status": "failed",
                    "blogger_status": None,
                },
                {
                    "title": "Wi-Fi Keeps Disconnecting on Windows 11",
                    "article_dir": str(passed_dir),
                    "seed_keyword": "wifi keeps disconnecting windows 11",
                    "article_status": "validated",
                    "blogger_status": None,
                },
            ]

            result = reporter._quality_issues_result(articles)
            issue_count = reporter._quality_issue_count(articles)

        self.assertEqual(result, [])
        self.assertEqual(issue_count, 0)

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
                        "google_suggest_live_signal_count": 0,
                        "google_suggest_fallback_signal_count": 4,
                        "signal_source_counts": {"reddit_fallback": 2, "google_suggest": 4},
                        "reddit_collection_method_counts": {"fallback": 2},
                        "google_suggest_method_counts": {"fallback": 4},
                        "reddit_collection_diagnostics": {
                            "status": "fallback_only",
                            "oauth_configured": False,
                            "public_json_error_count": 4,
                            "public_json_failed_subreddits": [
                                {"subreddit": "WindowsHelp", "error": "403 blocked"},
                                {"subreddit": "Windows11", "error": "403 blocked"},
                            ],
                            "fallback_reason": "All available Reddit live collection paths returned no usable signals; public JSON had errors.",
                        },
                        "google_suggest_diagnostics": {
                            "status": "fallback_only",
                            "live_suggestion_count": 0,
                            "fallback_suggestion_count": 4,
                            "used_fallback": True,
                            "fallback_reason": "Google Suggest request failed; used local query-intent fallback.",
                            "error": "timeout",
                        },
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
                        "google_suggest_live_signal_count": 2,
                        "google_suggest_fallback_signal_count": 0,
                        "signal_source_counts": {"reddit": 3, "reddit_fallback": 1, "google_suggest": 2},
                        "reddit_collection_method_counts": {"oauth": 2, "public_json": 1, "fallback": 1},
                        "google_suggest_method_counts": {"live": 2},
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
        self.assertEqual(result["google_suggest_live_signal_count"], 2)
        self.assertEqual(result["google_suggest_fallback_signal_count"], 4)
        self.assertEqual(result["signal_source_counts"]["reddit"], 3)
        self.assertEqual(result["reddit_collection_method_counts"]["oauth"], 2)
        self.assertEqual(result["reddit_collection_method_counts"]["public_json"], 1)
        self.assertEqual(result["google_suggest_method_counts"]["fallback"], 4)
        self.assertEqual(result["google_suggest_method_counts"]["live"], 2)
        self.assertEqual(result["fallback_only_articles"], ["Fallback only article"])
        self.assertEqual(result["reddit_collection_diagnostics"][0]["title"], "Fallback only article")
        self.assertEqual(result["reddit_collection_diagnostics"][0]["public_json_error_count"], 4)
        self.assertEqual(result["reddit_collection_diagnostics"][0]["failed_subreddits"], ["WindowsHelp", "Windows11"])
        self.assertEqual(result["google_suggest_diagnostics"][0]["title"], "Fallback only article")
        self.assertEqual(result["google_suggest_diagnostics"][0]["fallback_suggestion_count"], 4)

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

    def test_next_actions_explain_launch_queue_warn(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "warn",
                    "checks": [
                        {
                            "name": "launch_queue",
                            "status": "warn",
                            "message": "0/14 launch topics remain unused before the long-term queue. Production will use the long-term seed list.",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Preflight 주의 항목", joined)
        self.assertIn("Launch queue가 소진", joined)
        self.assertIn("장기 Windows topic seed 목록", joined)

    def test_next_actions_explain_launch_queue_quality_failure(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "launch_queue_quality",
                            "status": "fail",
                            "message": "Launch queue quality failed: windows problem: generic_computer_help_category, weak_microsoft_sources",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Launch queue 품질검수에 실패", joined)
        self.assertIn("Microsoft 출처 부족", joined)
        self.assertIn("generic_computer_help_category", joined)

    def test_next_actions_include_seed_inventory_warning(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "warn",
                    "checks": [
                        {
                            "name": "seed_inventory",
                            "status": "warn",
                            "message": "8/103 exact-match topic seeds remain unused. Add at least two weeks of fresh topic seeds soon.",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Windows topic seed 재고가 낮습니다", joined)
        self.assertIn("최소 2주치 이상", joined)
        self.assertIn("8/103 exact-match topic seeds remain unused", joined)

    def test_next_actions_include_seed_inventory_failure(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "seed_inventory",
                            "status": "fail",
                            "message": "0/103 exact-match topic seeds remain unused. Add fresh Windows topic seeds before the next unattended publish.",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Windows topic seed 재고가 소진되었습니다", joined)
        self.assertIn("다음 무인 발행 전", joined)
        self.assertIn("0/103 exact-match topic seeds remain unused", joined)

    def test_next_actions_include_all_seed_quality_failure(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "all_seed_quality",
                            "status": "fail",
                            "message": "Long-term seed quality failed for 2/103 topic(s): windows problem: generic_computer_help_category",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("장기 Windows topic seed 품질검수에 실패", joined)
        self.assertIn("장기 큐로 넘어가기 전", joined)
        self.assertIn("generic_computer_help_category", joined)

    def test_next_actions_include_seed_file_duplicate_guidance(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "seed_file",
                            "status": "fail",
                            "message": "Duplicate topic seeds found: wifi button missing windows 11.",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Windows topic seed 파일에 중복", joined)
        self.assertIn("중복 시드를 제거", joined)

    def test_next_actions_include_seed_file_weak_seed_guidance(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {
                    "status": "fail",
                    "checks": [
                        {
                            "name": "seed_file",
                            "status": "fail",
                            "message": "Weak Windows topic seeds found: windows error.",
                        }
                    ],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("Windows topic seed가 너무 모호", joined)
        self.assertIn("오류 코드, 증상, 앱, Windows 기능", joined)

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

    def test_next_actions_merge_reddit_fallback_and_cadence_warnings_when_health_blocks(self) -> None:
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
                "reddit_health": {
                    "status": "missing_credentials",
                    "health_score": 0,
                    "blocks_cadence_increase": True,
                    "action_required": "Reddit 승인 메일을 기다리세요.",
                },
            },
            signal_quality={"status": "fallback_only"},
        )

        joined = "\n".join(actions)
        self.assertIn("Reddit OAuth Health가 발행량 증량을 차단 중", joined)
        self.assertEqual(joined.count("Reddit"), 2)
        self.assertNotIn("Reddit 실제 신호 없이 fallback 질문만 사용한 글", joined)
        self.assertNotIn("일일 운영 상태 기준으로 아직 발행량 증량 준비가 아닙니다", joined)

    def test_next_actions_include_daily_retry_seed_guidance(self) -> None:
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
                    "skipped_duplicate_seeds": ["wifi button missing windows 11"],
                    "skipped_quality_seeds": ["thin windows update topic"],
                },
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("중복 주제가 감지", joined)
        self.assertIn("Windows topic seed 목록에 새 주제를 보충", joined)
        self.assertIn("품질검수 실패 후 다른 시드로 재시도", joined)
        self.assertIn("공식 출처", joined)

    def test_next_actions_include_quality_issue_guidance(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={"preflight": {"status": "pass"}},
            signal_quality={"status": "connected"},
            quality_issues=[
                {"code": "weak_related_guide_links", "message": "Related guide links missing."},
                {"code": "missing_required_image_assets", "message": "Missing image assets."},
                {"code": "unsafe_windows_image_label", "message": "Image label mentions screenshot."},
                {"code": "shallow_microsoft_sources", "message": "Direct Microsoft sources missing."},
                {"code": "topic_alignment_mismatch", "message": "Topic seed mismatch."},
            ],
        )

        joined = "\n".join(actions)
        self.assertIn("Related Guides 내부 링크 문제", joined)
        self.assertIn("블로그 내부 검색 링크 3개 이상", joined)
        self.assertIn("이미지 문제가 감지", joined)
        self.assertIn("hero/inline 이미지 2개", joined)
        self.assertIn("alt/caption", joined)
        self.assertIn("Windows 이미지 안전 문제가 감지", joined)
        self.assertIn("readable error text", joined)
        self.assertIn("Registry Editor", joined)
        self.assertIn("공식 출처 문제가 감지", joined)
        self.assertIn("Microsoft Support/Learn 직접 링크", joined)
        self.assertIn("주제 일치 문제가 감지", joined)
        self.assertIn("topic seed의 핵심 단어", joined)

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
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_confirmed",
        )
        self.assertFalse(operations["publication_check"]["publication_evidence"]["needs_attention"])
        self.assertEqual(operations["sitemap_submit"]["status"], "not_persisted")
        self.assertEqual(operations["sitemap_submit"]["previous_status"], "not_uploaded")

    def test_operations_result_keeps_current_sitemap_report(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-search-console-sitemap-submit.json").write_text(
                json.dumps(
                    {
                        "status": "submitted",
                        "submitted_at": "2026-06-25T00:15:00Z",
                        "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(
                now=now,
                public_posts={"status": "connected", "posts": []},
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["sitemap_submit"]["status"], "submitted")
        self.assertEqual(operations["sitemap_submit"]["submitted_at"], "2026-06-25T00:15:00Z")

    def test_operations_result_accepts_legacy_submitted_sitemap_report_without_timestamp(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-search-console-sitemap-submit.json").write_text(
                json.dumps(
                    {
                        "status": "submitted",
                        "site_url": "https://easypcfixguide.blogspot.com/",
                        "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(
                now=now,
                public_posts={"status": "connected", "posts": []},
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["sitemap_submit"]["status"], "submitted")
        self.assertEqual(operations["sitemap_submit"]["timestamp_status"], "legacy_missing_submitted_at")
        self.assertIn("submitted_at", operations["sitemap_submit"]["note"])

    def test_operations_result_marks_stale_sitemap_report_as_not_persisted(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-search-console-sitemap-submit.json").write_text(
                json.dumps(
                    {
                        "status": "submitted",
                        "submitted_at": "2026-06-24T00:15:00Z",
                        "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(
                now=now,
                public_posts={"status": "connected", "posts": []},
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["sitemap_submit"]["status"], "not_persisted")
        self.assertEqual(operations["sitemap_submit"]["previous_status"], "submitted")
        self.assertEqual(operations["sitemap_submit"]["previous_submitted_at"], "2026-06-24T00:15:00Z")

    def test_next_actions_include_not_persisted_sitemap_guidance(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {"status": "pass"},
                "sitemap_submit": {"status": "not_persisted"},
            },
            signal_quality={"status": "connected"},
        )

        joined = "\n".join(actions)
        self.assertIn("sitemap 제출 리포트가 주간 workflow 환경에 보존되지 않았습니다", joined)
        self.assertIn("Daily Publish artifact", joined)

    def test_operations_result_marks_stale_daily_failure_as_previous_failure(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-daily-failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "created_at": "2026-06-24T09:10:00Z",
                        "error": "old failure",
                        "seed": "old seed",
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(now=now)

        self.assertEqual(operations["daily_failure"]["status"], "stale_failure")
        self.assertEqual(operations["daily_failure"]["previous_status"], "failed")
        self.assertEqual(operations["daily_failure"]["previous_created_at"], "2026-06-24T09:10:00Z")

        actions = reporter._next_actions(
            articles=[],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={"daily_failure": operations["daily_failure"], "preflight": {"status": "pass"}},
        )
        self.assertNotIn("최근 일일 자동화 실패 리포트", "\n".join(actions))

    def test_operations_result_keeps_current_daily_failure_as_failed(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-daily-failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "created_at": "2026-06-25T00:10:00Z",
                        "error": "today failure",
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(now=now)

        self.assertEqual(operations["daily_failure"]["status"], "failed")
        self.assertEqual(operations["daily_failure"]["error"], "today failure")

    def test_operations_result_marks_missing_reddit_health_as_cadence_blocker(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            operations = reporter._operations_result(now=now)

        self.assertEqual(operations["reddit_health"]["status"], "reddit_health_missing")
        self.assertEqual(operations["reddit_health"]["health_score"], 0)
        self.assertTrue(operations["reddit_health"]["blocks_cadence_increase"])
        self.assertIn("workflow", operations["reddit_health"]["action_required"])

    def test_operations_result_marks_stale_reddit_health_as_cadence_blocker(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-reddit-health.json").write_text(
                json.dumps(
                    {
                        "status": "oauth_connected",
                        "checked_at": "2026-06-24T00:20:00Z",
                        "health_score": 100,
                        "blocks_cadence_increase": False,
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(now=now)

        self.assertEqual(operations["reddit_health"]["status"], "stale_reddit_health")
        self.assertEqual(operations["reddit_health"]["previous_status"], "oauth_connected")
        self.assertEqual(operations["reddit_health"]["previous_checked_at"], "2026-06-24T00:20:00Z")
        self.assertEqual(operations["reddit_health"]["health_score"], 0)
        self.assertTrue(operations["reddit_health"]["blocks_cadence_increase"])

    def test_operations_result_keeps_current_reddit_health(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 9, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-reddit-health.json").write_text(
                json.dumps(
                    {
                        "status": "oauth_connected",
                        "checked_at": "2026-06-25T00:20:00Z",
                        "health_score": 100,
                        "blocks_cadence_increase": False,
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(now=now)

        self.assertEqual(operations["reddit_health"]["status"], "oauth_connected")
        self.assertEqual(operations["reddit_health"]["health_score"], 100)
        self.assertFalse(operations["reddit_health"]["blocks_cadence_increase"])

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
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_confirmed",
        )

    def test_operations_result_refreshes_legacy_publication_check_after_validation_report_migration(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-publication-check.json").write_text(
                json.dumps(
                    {
                        "status": "published_today_before_cutoff",
                        "checked_at_kst": "2026-06-25T11:32:30+09:00",
                        "today_post_count": 0,
                        "today_total_post_count": 1,
                        "publication_evidence": {
                            "status": "feed_and_workflow_confirmed_report_not_publish",
                            "label": "공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님",
                            "needs_attention": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

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

        self.assertEqual(operations["daily_success_context"]["status"], "not_uploaded")
        self.assertEqual(operations["publication_check"]["source"], "weekly_public_feed_fallback")
        self.assertEqual(operations["publication_check"]["status"], "published_today_before_cutoff")
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_confirmed",
        )
        self.assertFalse(operations["publication_check"]["publication_evidence"]["needs_attention"])

    def test_operations_result_refreshes_stale_publication_check_from_previous_day(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            (report_dir / "easy_pc_fix_guide-publication-check.json").write_text(
                json.dumps(
                    {
                        "status": "published_today",
                        "checked_at_kst": "2026-06-24T09:45:00+09:00",
                        "today_post_count": 1,
                    }
                ),
                encoding="utf-8",
            )

            operations = reporter._operations_result(
                now=now,
                public_posts={
                    "status": "connected",
                    "posts": [
                        {
                            "title": "Fresh post",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
                            "published_kst": "2026-06-25T09:12:00+09:00",
                        }
                    ],
                },
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["publication_check"]["source"], "weekly_public_feed_fallback")
        self.assertEqual(operations["publication_check"]["status"], "published_today")
        self.assertEqual(operations["publication_check"]["today_post_count"], 1)
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_confirmed",
        )

    def test_operations_result_marks_weekly_public_feed_missing_as_attention_needed(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            operations = reporter._operations_result(
                now=now,
                public_posts={"status": "connected", "posts": []},
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["publication_check"]["status"], "missing_today")
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_missing_today",
        )
        self.assertTrue(operations["publication_check"]["publication_evidence"]["needs_attention"])

    def test_operations_result_marks_weekly_public_feed_before_cutoff_as_pending(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)
        now = datetime(2026, 6, 25, 1, 40, tzinfo=ZoneInfo("Asia/Seoul"))

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.reporting.weekly.ROOT_DIR", Path(tmpdir)):
            operations = reporter._operations_result(
                now=now,
                public_posts={"status": "connected", "posts": []},
                search_console={"status": "connected"},
            )

        self.assertEqual(operations["publication_check"]["status"], "pending_today_before_cutoff")
        self.assertEqual(
            operations["publication_check"]["publication_evidence"]["status"],
            "weekly_public_feed_before_cutoff",
        )
        self.assertFalse(operations["publication_check"]["publication_evidence"]["needs_attention"])

    def test_next_actions_do_not_warn_for_publication_before_cutoff_pending(self) -> None:
        settings = load_settings("easy_pc_fix_guide")
        reporter = WeeklyReporter(settings)

        actions = reporter._next_actions(
            articles=[{"blogger_status": "LIVE"}],
            static_pages=[{"title": "About"}, {"title": "Contact"}, {"title": "Privacy Policy"}, {"title": "Disclaimer"}],
            public_posts={"status": "connected", "posts": [{"title": "Published"}]},
            operations={
                "preflight": {"status": "pass"},
                "publication_check": {"status": "pending_today_before_cutoff"},
                "sitemap_submit": {"status": "submitted"},
            },
            signal_quality={"status": "connected"},
        )

        self.assertNotIn("오늘 공개 글을 찾지 못했습니다", "\n".join(actions))


if __name__ == "__main__":
    unittest.main()
