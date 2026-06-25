from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src.pipeline import daily_draft
from src.quality.hades import HadesQualityGate


class DuplicatePublishGuardTests(unittest.TestCase):
    def test_daily_success_report_is_written_with_quality_and_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            article_dir = root / "article"
            article_dir.mkdir()
            publish_result_path = article_dir / "blogger_publish_result.json"
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {
                            "title": "Wi-Fi Button Missing on Windows 11",
                            "category": "Wi-Fi & Internet",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "metrics": {"word_count": 1512}}),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "live_reddit_signal_count": 0,
                        "reddit_oauth_signal_count": 0,
                        "reddit_public_json_signal_count": 0,
                        "fallback_reddit_signal_count": 6,
                        "reddit_collection_method_counts": {"fallback": 6},
                        "reddit_collection_diagnostics": {
                            "status": "fallback_only",
                            "public_json_error_count": 4,
                            "public_json_failed_subreddits": [
                                {"subreddit": "WindowsHelp", "error": "403 blocked"},
                                {"subreddit": "Windows11", "error": "403 blocked"},
                                {"subreddit": "techsupport", "error": "403 blocked"},
                                {"subreddit": "pchelp", "error": "403 blocked"},
                            ],
                            "fallback_reason": "All available Reddit live collection paths returned no usable signals; public JSON had errors.",
                        },
                    }
                ),
                encoding="utf-8",
            )
            publish_result_path.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "blogger": {
                            "status": "LIVE",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                        },
                    }
                ),
                encoding="utf-8",
            )
            reports_dir = root / "reports"
            reports_dir.mkdir()
            stale_failure_path = reports_dir / "easy_pc_fix_guide-daily-failure.json"
            stale_failure_path.write_text(json.dumps({"status": "failed"}), encoding="utf-8")

            with patch.object(daily_draft, "ROOT_DIR", root):
                report_path = daily_draft.save_daily_success_report(
                    {
                        "site": "easy_pc_fix_guide",
                        "mode": "publish",
                        "seed": "wifi button missing windows 11",
                        "article_dir": str(article_dir),
                        "publish_result": str(publish_result_path),
                        "skipped_duplicate_seeds": [],
                    }
                )

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            stale_failure_removed = not stale_failure_path.exists()

        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["title"], "Wi-Fi Button Missing on Windows 11")
        self.assertEqual(payload["quality_score"], 100)
        self.assertEqual(payload["quality_metrics"]["word_count"], 1512)
        self.assertEqual(payload["reddit_signal_quality"]["fallback_reddit_signal_count"], 6)
        self.assertIn("fallback 질문만 사용", payload["reddit_signal_quality"]["warning"])
        self.assertTrue(payload["operational_status"]["publish_quality_ok"])
        self.assertEqual(payload["operational_status"]["collection_status"], "fallback_only")
        self.assertFalse(payload["operational_status"]["ready_for_cadence_increase"])
        self.assertEqual(payload["url"], "https://easypcfixguide.blogspot.com/2026/06/example.html")
        self.assertTrue(stale_failure_removed)

    def test_validate_success_report_does_not_overwrite_publish_success_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                json.dumps({"article": {"title": "Validation Topic", "category": "Windows"}}),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "issues": [], "metrics": {}}),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(json.dumps({}), encoding="utf-8")
            validation_result_path = article_dir / "validation_result.json"
            validation_result_path.write_text(json.dumps({"mode": "validate", "passed": True}), encoding="utf-8")
            reports_dir = root / "reports"
            reports_dir.mkdir()
            publish_success_path = reports_dir / "easy_pc_fix_guide-daily-success.json"
            publish_success_path.write_text(
                json.dumps({"status": "published", "title": "Keep this publish report"}),
                encoding="utf-8",
            )
            stale_validation_failure = reports_dir / "easy_pc_fix_guide-daily-validation-failure.json"
            stale_validation_failure.write_text(json.dumps({"status": "failed"}), encoding="utf-8")

            with patch.object(daily_draft, "ROOT_DIR", root):
                validation_report_path = daily_draft.save_daily_success_report(
                    {
                        "site": "easy_pc_fix_guide",
                        "mode": "validate",
                        "seed": "validation seed",
                        "article_dir": str(article_dir),
                        "publish_result": str(validation_result_path),
                    }
                )

            publish_payload = json.loads(publish_success_path.read_text(encoding="utf-8"))
            validation_payload = json.loads(validation_report_path.read_text(encoding="utf-8"))

        self.assertEqual(validation_report_path.name, "easy_pc_fix_guide-daily-validation-success.json")
        self.assertEqual(validation_payload["status"], "validated")
        self.assertEqual(publish_payload["title"], "Keep this publish report")
        self.assertFalse(stale_validation_failure.exists())

    def test_scheduled_publish_skips_when_public_post_already_exists_today(self) -> None:
        existing_post = {
            "title": "Wi-Fi Button Missing on Windows 11",
            "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
            "published_kst": "2026-06-25T00:12:10+09:00",
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(daily_draft, "ROOT_DIR", Path(tmpdir)), patch.object(
            daily_draft, "find_public_post_published_today", return_value=existing_post
        ), patch.object(daily_draft, "run_stage1") as stage1, patch.object(
            daily_draft, "run_publish_with_seed_fallback"
        ) as publish, patch.object(
            daily_draft, "notify_daily_completion"
        ) as notify:
            result = daily_draft.run(site="easy_pc_fix_guide", publish_mode="publish")
            report_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-daily-success.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        stage1.assert_not_called()
        publish.assert_not_called()
        notify.assert_called_once()
        self.assertTrue(result["daily_limit_skipped"])
        self.assertEqual(payload["status"], "skipped_daily_limit")
        self.assertEqual(payload["title"], "Wi-Fi Button Missing on Windows 11")
        self.assertEqual(payload["url"], "https://easypcfixguide.blogspot.com/2026/06/example.html")
        self.assertTrue(payload["operational_status"]["publish_quality_ok"])
        self.assertEqual(payload["operational_status"]["collection_status"], "not_run_daily_limit")
        self.assertEqual(payload["operational_status"]["status_label"], "오늘 공개 글 확인, 추가 발행 정상 스킵")

    def test_daily_limit_feed_error_is_reported_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            with patch.object(daily_draft, "ROOT_DIR", Path(tmpdir)), patch.object(
                daily_draft, "find_public_post_published_today", side_effect=RuntimeError("feed unavailable")
            ), patch.object(daily_draft, "notify_daily_failure") as notify:
                with self.assertRaises(RuntimeError):
                    daily_draft.run(site="easy_pc_fix_guide", publish_mode="publish")

            report_path = report_dir / "easy_pc_fix_guide-daily-failure.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        notify.assert_called_once()
        self.assertEqual(payload["seed"], "")
        self.assertEqual(payload["mode"], "publish")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertIn("feed unavailable", payload["error"])

    def test_explicit_publish_seed_does_not_use_daily_limit_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "article"
            article_dir.mkdir()
            result_path = article_dir / "blogger_publish_result.json"

            with patch.object(daily_draft, "find_public_post_published_today") as daily_guard, patch.object(
                daily_draft,
                "run_publish_with_seed_fallback",
                return_value=("manual seed", article_dir, result_path, [], []),
            ), patch.object(daily_draft, "save_daily_success_report"), patch.object(
                daily_draft, "notify_daily_completion"
            ):
                result = daily_draft.run(
                    seed="manual seed",
                    site="easy_pc_fix_guide",
                    publish_mode="publish",
                )

        daily_guard.assert_not_called()
        self.assertEqual(result["seed"], "manual seed")

    def test_daily_success_message_includes_quality_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            publish_result_path = article_dir / "blogger_publish_result.json"
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {
                            "title": "Wi-Fi Button Missing on Windows 11",
                            "category": "Wi-Fi & Internet",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps(
                    {
                        "score": 100,
                        "passed": True,
                        "issues": [],
                        "metrics": {
                            "word_count": 1512,
                            "image_count": 2,
                            "official_link_count": 7,
                            "faq_question_count": 9,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "live_reddit_signal_count": 0,
                        "reddit_oauth_signal_count": 0,
                        "reddit_public_json_signal_count": 0,
                        "fallback_reddit_signal_count": 6,
                        "reddit_collection_method_counts": {"fallback": 6},
                        "reddit_collection_diagnostics": {
                            "status": "fallback_only",
                            "public_json_error_count": 4,
                            "public_json_failed_subreddits": [
                                {"subreddit": "WindowsHelp", "error": "403 blocked"},
                                {"subreddit": "Windows11", "error": "403 blocked"},
                                {"subreddit": "techsupport", "error": "403 blocked"},
                                {"subreddit": "pchelp", "error": "403 blocked"},
                            ],
                            "fallback_reason": "All available Reddit live collection paths returned no usable signals; public JSON had errors.",
                        },
                    }
                ),
                encoding="utf-8",
            )
            publish_result_path.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "blogger": {
                            "status": "LIVE",
                            "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                        },
                    }
                ),
                encoding="utf-8",
            )

            message = daily_draft.build_daily_success_message(
                {
                    "site": "easy_pc_fix_guide",
                    "mode": "publish",
                    "seed": "wifi button missing windows 11",
                    "article_dir": str(article_dir),
                    "publish_result": str(publish_result_path),
                }
            )

        self.assertIn("- 단어 수: 1512", message)
        self.assertIn("- 이미지 수: 2", message)
        self.assertIn("- 공식 링크 수: 7", message)
        self.assertIn("- FAQ 수: 9", message)
        self.assertIn("- Reddit fallback 신호 수: 6", message)
        self.assertIn("- 운영 상태: 발행 품질 OK, 수집 안정성 점검 필요", message)
        self.assertIn("- 발행 품질 안정성: 안정", message)
        self.assertIn("- 수집 안정성: 주의: fallback 질문 의존", message)
        self.assertIn("수집 품질 경고", message)
        self.assertIn("fallback 질문만 사용", message)
        self.assertIn("- Reddit 수집 진단 상태: fallback_only", message)
        self.assertIn("- Reddit public JSON 실패 수: 4", message)
        self.assertIn("- 실패 subreddit: WindowsHelp, Windows11, techsupport, pchelp", message)
        self.assertIn("- fallback 이유: All available Reddit live collection paths returned no usable signals", message)
        self.assertIn("https://www.reddit.com/prefs/apps", message)
        self.assertIn("REDDIT_CLIENT_ID", message)
        self.assertIn("Easy PC Fix Reddit OAuth Health", message)

    def test_daily_limit_success_message_does_not_look_like_quality_failure(self) -> None:
        message = daily_draft.build_daily_success_message(
            {
                "site": "easy_pc_fix_guide",
                "mode": "publish",
                "daily_limit_skipped": True,
                "existing_post": {
                    "title": "Wi-Fi Button Missing on Windows 11",
                    "url": "https://easypcfixguide.blogspot.com/2026/06/example.html",
                    "published_kst": "2026-06-25T00:12:10+09:00",
                },
            }
        )

        self.assertIn("오늘 공개 글 이미 있음, 추가 발행 건너뜀", message)
        self.assertIn("- Blogger 상태: existing_public_post", message)
        self.assertIn("- 기존 공개 시각: 2026-06-25T00:12:10+09:00", message)
        self.assertIn("- 품질검수: 오늘 이미 공개된 글이 있어 새 글 생성/검수 없음", message)
        self.assertIn("- 운영 상태: 오늘 공개 글 확인, 추가 발행 정상 스킵", message)
        self.assertIn("- 발행 품질 안정성: 안정", message)
        self.assertNotIn("- 품질통과: 아니오", message)
        self.assertNotIn("- 품질점수: n/a/100", message)
        self.assertNotIn("- Reddit fallback 신호 수: 0", message)

    def test_daily_success_message_includes_quality_issue_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            publish_result_path = article_dir / "validation_result.json"
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {
                            "title": "Microsoft Store Not Opening on Windows 11",
                            "category": "Apps & Settings",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps(
                    {
                        "score": 64,
                        "passed": False,
                        "issues": [
                            {"code": "weak_related_guide_links", "message": "Missing internal related guide links."},
                            {"code": "missing_required_image_assets", "message": "Missing image assets."},
                            {"code": "unsafe_windows_image_prompt", "message": "Image prompt allows fake Windows UI."},
                            {"code": "shallow_microsoft_sources", "message": "Direct Microsoft source links missing."},
                            {"code": "topic_alignment_mismatch", "message": "Topic seed mismatch."},
                        ],
                        "metrics": {
                            "word_count": 1501,
                            "image_count": 0,
                            "official_link_count": 4,
                            "faq_question_count": 6,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(json.dumps({}), encoding="utf-8")
            publish_result_path.write_text(json.dumps({"draft": True, "blogger": {"status": "DRAFT"}}), encoding="utf-8")

            message = daily_draft.build_daily_success_message(
                {
                    "site": "easy_pc_fix_guide",
                    "mode": "validate",
                    "seed": "microsoft store not opening windows 11",
                    "article_dir": str(article_dir),
                    "publish_result": str(publish_result_path),
                }
            )

        self.assertIn("품질 이슈:", message)
        self.assertIn("weak_related_guide_links", message)
        self.assertIn("품질 조치:", message)
        self.assertIn("Related Guides 내부 링크 문제", message)
        self.assertIn("블로그 내부 검색 링크 3개 이상", message)
        self.assertIn("이미지 문제가 감지", message)
        self.assertIn("alt/caption", message)
        self.assertIn("Windows 이미지 안전 문제가 감지", message)
        self.assertIn("fake Windows UI", message)
        self.assertIn("abstract checklist", message)
        self.assertIn("공식 출처 문제가 감지", message)
        self.assertIn("주제 일치 문제가 감지", message)

    def test_operational_status_allows_cadence_increase_only_with_oauth_signals(self) -> None:
        result = daily_draft.build_operational_status(
            {"score": 100, "passed": True, "issues": []},
            {
                "reddit_oauth_signal_count": 3,
                "reddit_public_json_signal_count": 0,
                "fallback_reddit_signal_count": 0,
            },
        )

        self.assertTrue(result["publish_quality_ok"])
        self.assertEqual(result["collection_status"], "stable_oauth")
        self.assertTrue(result["ready_for_cadence_increase"])

    def test_operational_status_blocks_cadence_increase_when_quality_has_issues(self) -> None:
        result = daily_draft.build_operational_status(
            {"score": 88, "passed": False, "issues": [{"code": "thin_content"}]},
            {
                "reddit_oauth_signal_count": 3,
                "reddit_public_json_signal_count": 0,
                "fallback_reddit_signal_count": 0,
            },
        )

        self.assertFalse(result["publish_quality_ok"])
        self.assertEqual(result["collection_status"], "stable_oauth")
        self.assertFalse(result["ready_for_cadence_increase"])

    def test_daily_success_message_warns_when_reddit_uses_public_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            publish_result_path = article_dir / "blogger_publish_result.json"
            (article_dir / "metadata.json").write_text(
                json.dumps({"article": {"title": "Public JSON Topic", "category": "Windows"}}),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "issues": [], "metrics": {}}),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "live_reddit_signal_count": 4,
                        "reddit_oauth_signal_count": 0,
                        "reddit_public_json_signal_count": 4,
                        "fallback_reddit_signal_count": 0,
                        "reddit_collection_method_counts": {"public_json": 4},
                        "reddit_collection_diagnostics": {
                            "status": "public_json_connected",
                            "public_json_error_count": 1,
                            "public_json_failed_subreddits": [
                                {"subreddit": "WindowsHelp", "error": "403 blocked"},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            publish_result_path.write_text(
                json.dumps({"draft": False, "blogger": {"status": "LIVE", "url": "https://example.com/public-json.html"}}),
                encoding="utf-8",
            )

            message = daily_draft.build_daily_success_message(
                {
                    "site": "easy_pc_fix_guide",
                    "mode": "publish",
                    "seed": "public json topic",
                    "article_dir": str(article_dir),
                    "publish_result": str(publish_result_path),
                }
            )

        self.assertIn("- Reddit public JSON 신호 수: 4", message)
        self.assertIn("public JSON 경로에만 의존", message)
        self.assertIn("- Reddit 수집 진단 상태: public_json_connected", message)
        self.assertIn("- Reddit public JSON 실패 수: 1", message)
        self.assertIn("- 실패 subreddit: WindowsHelp", message)
        self.assertIn("https://www.reddit.com/prefs/apps", message)
        self.assertIn("REDDIT_CLIENT_SECRET", message)

    def test_production_uses_launch_queue_before_long_term_seed_list(self) -> None:
        with patch.object(daily_draft, "load_settings") as load_settings:
            load_settings.return_value.app_env = "production"
            load_settings.return_value.automation_start_date = "2026-06-24"
            with patch.object(daily_draft, "load_seed_list", return_value=["long term topic"]), patch.object(
                daily_draft, "load_launch_seed_list", return_value=["launch day one", "launch day two"]
            ), patch.object(daily_draft, "date") as fake_date:
                fake_date.today.return_value = datetime(2026, 6, 25).date()

                seed = daily_draft.choose_seed(site="easy_pc_fix_guide")

        self.assertEqual(seed, "launch day two")

    def test_production_returns_to_long_term_seeds_after_launch_queue(self) -> None:
        with patch.object(daily_draft, "load_settings") as load_settings:
            load_settings.return_value.app_env = "production"
            load_settings.return_value.automation_start_date = "2026-06-24"
            with patch.object(daily_draft, "load_seed_list", return_value=["long term one", "long term two"]), patch.object(
                daily_draft, "load_launch_seed_list", return_value=["launch only"]
            ), patch.object(daily_draft, "date") as fake_date:
                fake_date.today.return_value = datetime(2026, 6, 26).date()

                seed = daily_draft.choose_seed(site="easy_pc_fix_guide")

        self.assertEqual(seed, "long term one")

    def test_matches_existing_post_by_title_when_blogger_shortens_slug(self) -> None:
        existing_post = {
            "title": "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
            "url": "https://easypcfixguide.blogspot.com/2026/06/wi-fi-button-missing-on-windows-11.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }
        with patch.object(daily_draft, "fetch_public_feed", return_value={}), patch.object(
            daily_draft, "parse_posts", return_value=[existing_post]
        ):
            duplicate = daily_draft.find_public_post(
                "https://easypcfixguide.blogspot.com",
                "wi-fi-button-missing-on-windows-11-simple-fixes-for-beginners",
                "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners",
            )

        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate["url"], existing_post["url"])

    def test_public_feed_errors_stop_publish_instead_of_assuming_no_duplicate(self) -> None:
        with patch.object(daily_draft, "fetch_public_feed", side_effect=RuntimeError("feed unavailable")):
            with self.assertRaises(RuntimeError):
                daily_draft.find_public_post("https://easypcfixguide.blogspot.com", "any-slug", "Any Title")

    def test_publish_mode_tries_next_seed_when_first_seed_is_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            def fake_stage1(seed: str, site: str | None = None) -> Path:
                article_dir = root / seed.replace(" ", "-")
                article_dir.mkdir()
                (article_dir / "metadata.json").write_text(
                    json.dumps({"article": {"title": seed, "category": "Test", "slug": seed.replace(" ", "-")}}),
                    encoding="utf-8",
                )
                (article_dir / "quality_report.json").write_text(
                    json.dumps({"score": 100, "passed": True, "issues": []}),
                    encoding="utf-8",
                )
                return article_dir

            def fake_publish(article_dir: Path, site: str | None = None) -> Path:
                if article_dir.name == "duplicate-topic":
                    result = {
                        "skipped": True,
                        "blogger": {"status": "SKIPPED_DUPLICATE", "url": "https://example.com/old.html"},
                    }
                    result_path = article_dir / "duplicate_publish_result.json"
                else:
                    result = {"draft": False, "blogger": {"status": "LIVE", "url": "https://example.com/new.html"}}
                    result_path = article_dir / "blogger_publish_result.json"
                result_path.write_text(json.dumps(result), encoding="utf-8")
                return result_path

            with patch.object(
                daily_draft, "choose_publish_seed_candidates", return_value=["duplicate topic", "fresh topic"]
            ), patch.object(daily_draft, "run_stage1", side_effect=fake_stage1), patch.object(
                daily_draft, "run_publish_with_duplicate_guard", side_effect=fake_publish
            ), patch.object(
                daily_draft, "find_public_post_published_today", return_value=None
            ), patch.object(
                daily_draft, "ROOT_DIR", root
            ), patch.object(
                daily_draft, "notify_daily_completion"
            ):
                result = daily_draft.run(site="easy_pc_fix_guide", publish_mode="publish")

        self.assertEqual(result["seed"], "fresh topic")
        self.assertEqual(result["skipped_duplicate_seeds"], ["duplicate topic"])
        self.assertTrue(result["publish_result"].endswith("blogger_publish_result.json"))

    def test_publish_mode_tries_next_seed_when_first_seed_fails_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            def fake_stage1(seed: str, site: str | None = None) -> Path:
                article_dir = root / seed.replace(" ", "-")
                article_dir.mkdir()
                (article_dir / "metadata.json").write_text(
                    json.dumps({"article": {"title": seed, "category": "Test", "slug": seed.replace(" ", "-")}}),
                    encoding="utf-8",
                )
                return article_dir

            def fake_publish(article_dir: Path, site: str | None = None) -> Path:
                if article_dir.name == "thin-topic":
                    raise ValueError("Hades quality gate failed with score 76/90: thin_content")
                result_path = article_dir / "blogger_publish_result.json"
                result_path.write_text(
                    json.dumps({"draft": False, "blogger": {"status": "LIVE", "url": "https://example.com/new.html"}}),
                    encoding="utf-8",
                )
                return result_path

            with patch.object(
                daily_draft, "choose_publish_seed_candidates", return_value=["thin topic", "strong topic"]
            ), patch.object(daily_draft, "run_stage1", side_effect=fake_stage1), patch.object(
                daily_draft, "run_publish_with_duplicate_guard", side_effect=fake_publish
            ), patch.object(
                daily_draft, "find_public_post_published_today", return_value=None
            ), patch.object(
                daily_draft, "ROOT_DIR", root
            ), patch.object(
                daily_draft, "notify_daily_completion"
            ):
                result = daily_draft.run(site="easy_pc_fix_guide", publish_mode="publish")

            report_path = root / "reports" / "easy_pc_fix_guide-daily-success.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result["seed"], "strong topic")
        self.assertEqual(result["skipped_quality_seeds"], ["thin topic"])
        self.assertEqual(payload["skipped_quality_seeds"], ["thin topic"])
        self.assertTrue(result["publish_result"].endswith("blogger_publish_result.json"))

    def test_explicit_seed_quality_failure_does_not_switch_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "thin-topic"
            article_dir.mkdir()

            with patch.object(daily_draft, "run_stage1", return_value=article_dir), patch.object(
                daily_draft,
                "run_publish_with_duplicate_guard",
                side_effect=ValueError("Hades quality gate failed with score 76/90: thin_content"),
            ):
                with self.assertRaises(ValueError):
                    daily_draft.run_publish_with_seed_fallback("thin topic", "easy_pc_fix_guide")

    def test_explicit_seed_stops_on_duplicate_without_switching_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir) / "duplicate-topic"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                json.dumps({"article": {"title": "duplicate topic", "category": "Test", "slug": "duplicate-topic"}}),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "issues": []}),
                encoding="utf-8",
            )
            result_path = article_dir / "duplicate_publish_result.json"
            result_path.write_text(
                json.dumps({"skipped": True, "blogger": {"status": "SKIPPED_DUPLICATE"}}),
                encoding="utf-8",
            )

            with patch.object(daily_draft, "run_stage1", return_value=article_dir), patch.object(
                daily_draft, "run_publish_with_duplicate_guard", return_value=result_path
            ), patch.object(
                daily_draft, "ROOT_DIR", Path(tmpdir)
            ), patch.object(daily_draft, "notify_daily_completion"):
                result = daily_draft.run(
                    seed="duplicate topic",
                    site="easy_pc_fix_guide",
                    publish_mode="publish",
                )

        self.assertEqual(result["seed"], "duplicate topic")
        self.assertEqual(result["skipped_duplicate_seeds"], ["duplicate topic"])
        self.assertTrue(result["publish_result"].endswith("duplicate_publish_result.json"))

    def test_daily_success_message_includes_quality_retry_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            publish_result_path = article_dir / "blogger_publish_result.json"
            (article_dir / "metadata.json").write_text(
                json.dumps({"article": {"title": "Strong Topic", "category": "Windows"}}),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "passed": True, "issues": [], "metrics": {}}),
                encoding="utf-8",
            )
            publish_result_path.write_text(
                json.dumps({"draft": False, "blogger": {"status": "LIVE", "url": "https://example.com/new.html"}}),
                encoding="utf-8",
            )

            message = daily_draft.build_daily_success_message(
                {
                    "site": "easy_pc_fix_guide",
                    "mode": "publish",
                    "seed": "strong topic",
                    "article_dir": str(article_dir),
                    "publish_result": str(publish_result_path),
                    "skipped_quality_seeds": ["thin topic"],
                }
            )

        self.assertIn("- 품질검수 실패로 재시도한 시드 수: 1", message)
        self.assertIn("- 품질 재시도 시드: thin topic", message)

    def test_daily_failure_notification_is_required(self) -> None:
        with patch.object(daily_draft, "NotificationClient") as notification:
            daily_draft.notify_daily_failure("broken topic", ValueError("quality failed"), "easy_pc_fix_guide")

        notification.return_value.send_required.assert_called_once()
        message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("[Posting Bot] 일일 포스팅 실패", message)
        self.assertIn("broken topic", message)
        self.assertIn("quality failed", message)
        self.assertIn("- 오류 유형: ValueError", message)
        self.assertIn("실패 리포트:", message)
        self.assertIn("Easy PC Fix Validate Smoke Test", message)
        self.assertIn("Easy PC Fix Daily Publish", message)

    def test_daily_failure_message_classifies_quality_failures(self) -> None:
        message = daily_draft.build_daily_failure_message(
            "thin topic",
            ValueError("Hades quality gate failed with score 76/90: thin_content"),
            "easy_pc_fix_guide",
        )

        self.assertIn("Hades 품질검수 실패", message)
        self.assertIn("quality_report.json", message)
        self.assertIn("공식 Microsoft 출처", message)

    def test_daily_failure_message_classifies_auth_failures(self) -> None:
        message = daily_draft.build_daily_failure_message(
            "auth topic",
            RuntimeError("OAuth credentials unauthorized"),
            "easy_pc_fix_guide",
        )

        self.assertIn("인증 문제 가능성", message)
        self.assertIn("Google OAuth 토큰", message)

    def test_validate_failure_message_points_to_validation_failure_report(self) -> None:
        message = daily_draft.build_daily_failure_message(
            "validation topic",
            RuntimeError("unexpected validation error"),
            "easy_pc_fix_guide",
            mode="validate",
        )

        self.assertIn("easy_pc_fix_guide-daily-validation-failure.json", message)
        self.assertIn("daily-validation-failure.json traceback", message)

    def test_daily_failure_report_is_written_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            with patch.object(daily_draft, "ROOT_DIR", Path(tmpdir)), patch.object(
                daily_draft, "choose_seed", return_value="broken seed"
            ), patch.object(daily_draft, "run_stage1", side_effect=ValueError("generation failed")), patch.object(
                daily_draft, "notify_daily_failure"
            ):
                with self.assertRaises(ValueError):
                    daily_draft.run(site="easy_pc_fix_guide", publish_mode="validate")

            report_path = report_dir / "easy_pc_fix_guide-daily-validation-failure.json"
            self.assertTrue(report_path.exists())
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["seed"], "broken seed")
        self.assertEqual(payload["mode"], "validate")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertIn("generation failed", payload["error"])


class WindowsQualityGateTests(unittest.TestCase):
    def test_windows_articles_require_estimated_time_in_safety_heading(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "hero.jpg").write_bytes(b"hero")
            (assets_dir / "inline.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"filename": "hero.jpg", "required": True},
                            {"filename": "inline.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "queries": [f"query {i}" for i in range(6)],
                        "reader_questions": [f"question {i}" for i in range(5)],
                        "sources": [
                            {"name": "Microsoft Support", "url": "https://support.microsoft.com/windows"},
                            {"name": "Microsoft Learn", "url": "https://learn.microsoft.com/windows/"},
                            {"name": "Release Health", "url": "https://learn.microsoft.com/windows/release-health/"},
                            {"name": "Windows Update", "url": "https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd"},
                            {"name": "Microsoft Store official help", "url": "https://support.microsoft.com/microsoft-store"},
                            {"name": "Microsoft Store", "url": "https://support.microsoft.com/microsoft-store"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            filler = " ".join(["safe beginner windows troubleshooting guidance"] * 300)
            html = f"""
            <article>
              <h2>Quick Summary</h2>
              <h2>Applies to / Risk level / Data loss risk / Last checked</h2>
              <p>Applies to Windows 11. Risk level low. Data loss risk low. Estimated time 10 minutes. Last checked today.</p>
              <h2>Symptoms</h2>
              <h2>What This Usually Means</h2>
              <h2>What Not to Do First</h2>
              <h2>Try This First</h2>
              <h2>Step-by-Step Fixes</h2>
              <h2>Advanced Fixes</h2>
              <p>Back up important files before advanced fixes.</p>
              <h2>When to Stop and Get Help</h2>
              <h2>FAQ</h2>
              <h3>Question 1?</h3><h3>Question 2?</h3><h3>Question 3?</h3><h3>Question 4?</h3><h3>Question 5?</h3>
              <h2>Related Guides</h2>
              <h2>Sources</h2>
              <img src="assets/hero.jpg" alt="Hero">
              <img src="assets/inline.jpg" alt="Inline">
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd">Windows Update</a>
              <p>{filler}</p>
            </article>
            """

            report = gate.review_html(
                html,
                article_dir,
                {"article": {"meta_description": "Safe Windows help.", "tags": ["Windows"]}},
            )

        messages = " ".join(issue.message for issue in report.issues)
        self.assertIn("missing_required_sections", {issue.code for issue in report.issues})
        self.assertIn("Applies to / Risk level / Data loss risk / Estimated time / Last checked", messages)

    def test_windows_articles_require_follow_up_sections_for_beginners(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "hero.jpg").write_bytes(b"hero")
            (assets_dir / "inline.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"filename": "hero.jpg", "required": True},
                            {"filename": "inline.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            filler = " ".join(["safe beginner windows troubleshooting guidance"] * 300)
            html = f"""
            <article>
              <h2>Quick Summary</h2>
              <h2>Applies to / Risk level / Data loss risk / Estimated time / Last checked</h2>
              <p>Applies to Windows 11. Risk level low. Data loss risk low. Estimated time 10 minutes. Last checked today.</p>
              <h2>Symptoms</h2>
              <h2>What This Usually Means</h2>
              <h2>What Not to Do First</h2>
              <h2>Try This First</h2>
              <h2>Step-by-Step Fixes</h2>
              <h2>Advanced Fixes</h2>
              <p>Back up important files before advanced fixes.</p>
              <h2>When to Stop and Get Help</h2>
              <h2>FAQ</h2>
              <h3>Question 1?</h3><h3>Question 2?</h3><h3>Question 3?</h3><h3>Question 4?</h3><h3>Question 5?</h3>
              <h2>Related Guides</h2>
              <ul><li>Fix Wi-Fi problems</li><li>Fix Windows Update</li><li>Fix Microsoft Store</li></ul>
              <h2>Sources</h2>
              <img src="assets/hero.jpg" alt="Hero">
              <img src="assets/inline.jpg" alt="Inline">
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd">Windows Update</a>
              <p>{filler}</p>
            </article>
            """

            report = gate.review_html(
                html,
                article_dir,
                {"article": {"meta_description": "Safe Windows help.", "tags": ["Windows"]}},
            )

        messages = " ".join(issue.message for issue in report.issues)
        self.assertIn("missing_required_sections", {issue.code for issue in report.issues})
        self.assertIn("After Each Step", messages)
        self.assertIn("What to Record Before Asking for Help", messages)

    def test_windows_articles_require_official_microsoft_source(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("missing_microsoft_source", {issue.code for issue in issues})

    def test_windows_articles_require_multiple_microsoft_sources(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=soup.find_all("a"),
        )

        self.assertIn("weak_microsoft_sources", {issue.code for issue in issues})

    def test_windows_articles_reject_search_only_microsoft_sources(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <a href="https://support.microsoft.com/search/results?query=Windows%20troubleshooting">Search 1</a>
              <a href="https://support.microsoft.com/search/results?query=Windows%20Update">Search 2</a>
              <a href="https://support.microsoft.com/search/results?query=Bluetooth%20Windows">Search 3</a>
              <a href="https://support.microsoft.com/search/results?query=Printer%20Windows">Search 4</a>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=soup.find_all("a"),
        )

        self.assertIn("shallow_microsoft_sources", {issue.code for issue in issues})

    def test_windows_sources_section_requires_direct_microsoft_links(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Related Guides</h2>
              <ul>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Windows+Update">Windows Update</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Check+Windows+version">Check Windows version</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Free+disk+space">Free disk space</a></li>
              </ul>
              <h2>Sources</h2>
              <ul>
                <li><a href="https://support.microsoft.com/search/results?query=Windows%20troubleshooting">Search 1</a></li>
                <li><a href="https://support.microsoft.com/search/results?query=Windows%20Update">Search 2</a></li>
                <li><a href="https://support.microsoft.com/search/results?query=Bluetooth%20Windows">Search 3</a></li>
                <li><a href="https://support.microsoft.com/search/results?query=Printer%20Windows">Search 4</a></li>
              </ul>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=soup.find_all("a"),
        )

        self.assertIn("shallow_sources_section_microsoft_links", {issue.code for issue in issues})

    def test_windows_articles_reject_known_bad_microsoft_shortcuts(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Sources</h2>
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/windows/network-wi-fi">Dead Wi-Fi shortcut</a>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=soup.find_all("a"),
        )

        self.assertIn("dead_microsoft_shortcut_links", {issue.code for issue in issues})

    def test_windows_research_rejects_known_bad_microsoft_shortcuts(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "queries": [f"query {i}" for i in range(6)],
                        "reader_questions": [f"question {i}" for i in range(5)],
                        "sources": [
                            {"name": "Microsoft Support", "url": "https://support.microsoft.com/windows"},
                            {"name": "Microsoft Learn", "url": "https://learn.microsoft.com/windows/"},
                            {"name": "Release Health", "url": "https://learn.microsoft.com/windows/release-health/"},
                            {"name": "Dead Wi-Fi shortcut", "url": "https://support.microsoft.com/windows/network-wi-fi"},
                            {
                                "name": "Windows Update troubleshooter",
                                "url": "https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd",
                            },
                            {"name": "Microsoft Store", "url": "https://support.microsoft.com/microsoft-store"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            _metrics, issues = gate._review_research_report(article_dir)

        self.assertIn("dead_microsoft_research_links", {issue.code for issue in issues})

    def test_windows_safety_table_requires_concrete_values(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Applies to / Risk level / Data loss risk / Estimated time / Last checked</h2>
              <table>
                <tr><td>Applies to</td><td>Windows 11</td></tr>
                <tr><td>Risk level</td><td>Very risky</td></tr>
                <tr><td>Data loss risk</td><td>Maybe</td></tr>
                <tr><td>Estimated time</td><td>Soon</td></tr>
                <tr><td>Last checked</td><td>Today</td></tr>
              </table>
              <h2>Related Guides</h2>
              <ul>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Windows+Update">Windows Update</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Check+Windows+version">Check Windows version</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Free+disk+space">Free disk space</a></li>
              </ul>
              <h2>Sources</h2>
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd">Windows Update</a>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=soup.find_all("a"),
        )

        issue_codes = {issue.code for issue in issues}
        self.assertIn("invalid_windows_risk_level", issue_codes)
        self.assertIn("invalid_windows_data_loss_risk", issue_codes)
        self.assertIn("invalid_windows_estimated_time", issue_codes)
        self.assertIn("invalid_windows_last_checked", issue_codes)

    def test_windows_research_rejects_search_only_microsoft_sources(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "queries": [f"query {i}" for i in range(6)],
                        "reader_questions": [f"question {i}" for i in range(5)],
                        "sources": [
                            {"name": f"Search {i}", "url": f"https://support.microsoft.com/search/results?query=test{i}"}
                            for i in range(6)
                        ],
                    }
                ),
                encoding="utf-8",
            )

            metrics, issues = gate._review_research_report(article_dir)

        self.assertEqual(metrics["research_official_source_count"], 6)
        self.assertEqual(metrics["research_direct_official_source_count"], 0)
        self.assertIn("shallow_microsoft_research", {issue.code for issue in issues})

    def test_windows_articles_block_activation_bypass_content(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            "applies to risk level data loss risk estimated time last checked kms activator",
            links=[],
        )

        self.assertIn("blocked_windows_phrase", {issue.code for issue in issues})

    def test_windows_articles_keep_advanced_terms_out_of_beginner_fix_sections(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Try This First</h2>
              <p>Open regedit and change a Registry value.</p>
              <h2>Advanced Fixes</h2>
              <p>Back up important files before advanced fixes.</p>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("advanced_fix_in_beginner_section", {issue.code for issue in issues})

    def test_windows_command_repairs_require_beginner_safety_warnings(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            (
                "applies to risk level data loss risk estimated time last checked advanced fixes "
                "back up important files run powershell and dism to repair windows"
            ),
            links=[],
        )

        issue_codes = {issue.code for issue in issues}
        self.assertIn("missing_command_understanding_warning", issue_codes)
        self.assertIn("missing_official_command_source_warning", issue_codes)

    def test_windows_command_repairs_pass_with_official_command_warnings(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            (
                "applies to risk level data loss risk estimated time last checked advanced fixes "
                "back up important files do not run commands you do not understand "
                "use sfc or dism only from official microsoft instructions"
            ),
            links=[],
        )

        issue_codes = {issue.code for issue in issues}
        self.assertNotIn("missing_command_understanding_warning", issue_codes)
        self.assertNotIn("missing_official_command_source_warning", issue_codes)

    def test_windows_articles_require_three_related_guides(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Related Guides</h2>
              <ul><li>How to check your Windows version</li></ul>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("weak_related_guides", {issue.code for issue in issues})

    def test_windows_articles_accept_three_related_guides(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Related Guides</h2>
              <ul>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=How+to+check+your+Windows+version">How to check your Windows version</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=How+to+free+up+disk+space+on+Windows">How to free up disk space on Windows</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Windows+Update+stuck+at+100%25">Windows Update stuck at 100%</a></li>
              </ul>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertNotIn("weak_related_guides", {issue.code for issue in issues})
        self.assertNotIn("weak_related_guide_links", {issue.code for issue in issues})

    def test_windows_articles_require_internal_related_guide_links(self) -> None:
        gate = HadesQualityGate("windows_help")
        soup = BeautifulSoup(
            """
            <article>
              <h2>Related Guides</h2>
              <ul>
                <li>How to check your Windows version</li>
                <li>How to free up disk space on Windows</li>
                <li>Windows Update stuck at 100%</li>
              </ul>
            </article>
            """,
            "html.parser",
        )
        issues = gate._review_windows_article(
            soup,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("weak_related_guide_links", {issue.code for issue in issues})

    def test_windows_articles_block_onedrive_update_context_mismatch(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            (
                "applies to risk level data loss risk estimated time last checked advanced fixes back up important files "
                "onedrive error 0x8004de40 windows update shows 0x8004de40 "
                "run the windows update troubleshooter"
            ),
            links=[],
        )

        self.assertIn("windows_topic_context_mismatch", {issue.code for issue in issues})

    def test_windows_articles_block_seed_title_topic_mismatch(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "hero.jpg").write_bytes(b"hero")
            (assets_dir / "inline.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "filename": "hero.jpg",
                                "url": "assets/hero.jpg",
                                "required": True,
                                "alt": "Windows Update troubleshooting visual for beginner computer users",
                                "caption": "Use official update guidance before changing advanced settings.",
                            },
                            {
                                "filename": "inline.jpg",
                                "url": "assets/inline.jpg",
                                "required": True,
                                "alt": "Safe Windows Update checklist for beginner troubleshooting steps",
                                "caption": "Check each simple update step before trying advanced repair options.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            filler = " ".join(["safe beginner windows update troubleshooting guidance"] * 300)
            html = f"""
            <article>
              <h1>Windows Update Error 0X800F0922: What It Means and How to Fix It</h1>
              <h2>Quick Summary</h2>
              <h2>Applies to / Risk level / Data loss risk / Estimated time / Last checked</h2>
              <p>Applies to Windows 11. Risk level low. Data loss risk low. Estimated time 10 minutes. Last checked today.</p>
              <h2>Symptoms</h2><h2>What This Usually Means</h2><h2>What Not to Do First</h2>
              <h2>Try This First</h2><h2>Step-by-Step Fixes</h2><h2>After Each Step</h2>
              <h2>What to Record Before Asking for Help</h2><h2>Advanced Fixes</h2>
              <p>Back up important files before advanced fixes.</p>
              <h2>When to Stop and Get Help</h2>
              <h2>FAQ</h2>
              <h3>Question 1?</h3><h3>Question 2?</h3><h3>Question 3?</h3><h3>Question 4?</h3><h3>Question 5?</h3>
              <h2>Related Guides</h2>
              <ul>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Windows+Update">Windows Update</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Check+Windows+version">Check Windows version</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Free+disk+space">Free disk space</a></li>
              </ul>
              <h2>Sources</h2>
              <img src="assets/hero.jpg" alt="Windows Update troubleshooting visual for beginner computer users">
              <img src="assets/inline.jpg" alt="Safe Windows Update checklist for beginner troubleshooting steps">
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd">Windows Update</a>
              <p>{filler}</p>
            </article>
            """

            report = gate.review_html(
                html,
                article_dir,
                {
                    "article": {
                        "title": "Windows Update Error 0X800F0922: What It Means and How to Fix It",
                        "meta_description": "Safe Windows help.",
                        "tags": ["Windows"],
                    },
                    "candidate": {"keyword": "onedrive error 0x8004de40"},
                },
            )

        self.assertIn("topic_alignment_mismatch", {issue.code for issue in report.issues})

    def test_windows_articles_accept_seed_title_topic_alignment(self) -> None:
        gate = HadesQualityGate("windows_help")
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "hero.jpg").write_bytes(b"hero")
            (assets_dir / "inline.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "filename": "hero.jpg",
                                "url": "assets/hero.jpg",
                                "required": True,
                                "alt": "OneDrive error troubleshooting visual for beginner Windows users",
                                "caption": "Confirm the OneDrive account and connection before advanced fixes.",
                            },
                            {
                                "filename": "inline.jpg",
                                "url": "assets/inline.jpg",
                                "required": True,
                                "alt": "Safe OneDrive checklist for beginner troubleshooting steps",
                                "caption": "Record the OneDrive error code and what changed before retrying.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            filler = " ".join(["safe beginner onedrive windows troubleshooting guidance"] * 300)
            html = f"""
            <article>
              <h1>OneDrive Error 0X8004DE40: What It Means and How to Fix It</h1>
              <h2>Quick Summary</h2>
              <h2>Applies to / Risk level / Data loss risk / Estimated time / Last checked</h2>
              <p>Applies to Windows 11. Risk level low. Data loss risk low. Estimated time 10 minutes. Last checked today.</p>
              <h2>Symptoms</h2><h2>What This Usually Means</h2><h2>What Not to Do First</h2>
              <h2>Try This First</h2><h2>Step-by-Step Fixes</h2><h2>After Each Step</h2>
              <h2>What to Record Before Asking for Help</h2><h2>Advanced Fixes</h2>
              <p>Back up important files before advanced fixes.</p>
              <h2>When to Stop and Get Help</h2>
              <h2>FAQ</h2>
              <h3>Question 1?</h3><h3>Question 2?</h3><h3>Question 3?</h3><h3>Question 4?</h3><h3>Question 5?</h3>
              <h2>Related Guides</h2>
              <ul>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=OneDrive+sync">OneDrive sync</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Microsoft+account">Microsoft account</a></li>
                <li><a href="https://easypcfixguide.blogspot.com/search?q=Windows+settings">Windows settings</a></li>
              </ul>
              <h2>Sources</h2>
              <img src="assets/hero.jpg" alt="OneDrive error troubleshooting visual for beginner Windows users">
              <img src="assets/inline.jpg" alt="Safe OneDrive checklist for beginner troubleshooting steps">
              <a href="https://support.microsoft.com/windows">Microsoft Support</a>
              <a href="https://learn.microsoft.com/windows/">Microsoft Learn</a>
              <a href="https://learn.microsoft.com/windows/release-health/">Windows release health</a>
              <a href="https://support.microsoft.com/onedrive">OneDrive Support</a>
              <p>{filler}</p>
            </article>
            """

            report = gate.review_html(
                html,
                article_dir,
                {
                    "article": {
                        "title": "OneDrive Error 0X8004DE40: What It Means and How to Fix It",
                        "meta_description": "Safe Windows help.",
                        "tags": ["Windows", "OneDrive"],
                    },
                    "candidate": {"keyword": "onedrive error 0x8004de40"},
                },
            )

        self.assertNotIn("topic_alignment_mismatch", {issue.code for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
