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
        self.assertEqual(payload["url"], "https://easypcfixguide.blogspot.com/2026/06/example.html")
        self.assertTrue(stale_failure_removed)

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
                daily_draft, "run_publish_with_seed_fallback", return_value=("manual seed", article_dir, result_path, [])
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
                daily_draft, "notify_daily_completion"
            ):
                result = daily_draft.run(site="easy_pc_fix_guide", publish_mode="publish")

        self.assertEqual(result["seed"], "fresh topic")
        self.assertEqual(result["skipped_duplicate_seeds"], ["duplicate topic"])
        self.assertTrue(result["publish_result"].endswith("blogger_publish_result.json"))

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
            ), patch.object(daily_draft, "notify_daily_completion"):
                result = daily_draft.run(
                    seed="duplicate topic",
                    site="easy_pc_fix_guide",
                    publish_mode="publish",
                )

        self.assertEqual(result["seed"], "duplicate topic")
        self.assertEqual(result["skipped_duplicate_seeds"], ["duplicate topic"])
        self.assertTrue(result["publish_result"].endswith("duplicate_publish_result.json"))

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

            report_path = report_dir / "easy_pc_fix_guide-daily-failure.json"
            self.assertTrue(report_path.exists())
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["seed"], "broken seed")
        self.assertEqual(payload["mode"], "validate")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertIn("generation failed", payload["error"])


class WindowsQualityGateTests(unittest.TestCase):
    def test_windows_articles_require_official_microsoft_source(self) -> None:
        gate = HadesQualityGate("windows_help")
        issues = gate._review_windows_article(
            None,
            "applies to risk level data loss risk estimated time last checked advanced fixes back up important files",
            links=[],
        )

        self.assertIn("missing_microsoft_source", {issue.code for issue in issues})

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


if __name__ == "__main__":
    unittest.main()
