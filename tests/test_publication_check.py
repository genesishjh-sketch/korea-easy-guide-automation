from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.pipeline import stage4_publication_check


class PublicationCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.object(stage4_publication_check, "ROOT_DIR", Path(self._tmpdir.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_run_detects_post_after_cutoff(self) -> None:
        post = {
            "title": "Fresh post",
            "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_publication_check, "fetch_public_feed", return_value={}), patch.object(
            stage4_publication_check, "parse_posts", return_value=[post]
        ), patch.object(
            stage4_publication_check, "check_daily_workflow_status", return_value={"status": "success", "today_run_count": 1}
        ), patch.object(
            stage4_publication_check,
            "read_daily_success_report",
            return_value={
                "status": "validated",
                "mode": "validate",
                "operational_status": {
                    "publish_quality_ok": True,
                    "collection_status_label": "주의: fallback 질문 의존",
                    "ready_for_cadence_increase": False,
                    "status_label": "발행 품질 OK, 수집 안정성 점검 필요",
                },
            },
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            result = stage4_publication_check.run(
                "easy_pc_fix_guide",
                today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                after_hour=9,
                notify=True,
            )

        self.assertEqual(result["status"], "published_today")
        self.assertEqual(result["today_post_count"], 1)
        self.assertEqual(result["daily_workflow"]["status"], "success")
        self.assertEqual(result["daily_success"]["operational_status"]["ready_for_cadence_increase"], False)
        self.assertEqual(result["daily_success_context"]["status"], "validation_only")
        self.assertEqual(result["publication_evidence"]["status"], "feed_and_workflow_confirmed_report_not_publish")
        self.assertTrue(result["publication_evidence"]["needs_attention"])
        notification.return_value.send_required.assert_called_once()

    def test_run_accepts_today_post_before_cutoff(self) -> None:
        post = {
            "title": "Early post",
            "url": "https://easypcfixguide.blogspot.com/2026/06/early-post.html",
            "published_kst": datetime(2026, 6, 25, 0, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_publication_check, "fetch_public_feed", return_value={}), patch.object(
            stage4_publication_check, "parse_posts", return_value=[post]
        ), patch.object(
            stage4_publication_check,
            "check_daily_workflow_status",
            return_value={"status": "no_run_today", "today_run_count": 0},
        ), patch.object(
            stage4_publication_check, "read_daily_success_report", return_value={"status": "not_uploaded"}
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            result = stage4_publication_check.run(
                "easy_pc_fix_guide",
                today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                after_hour=9,
                notify=True,
            )

        self.assertEqual(result["status"], "published_today_before_cutoff")
        self.assertEqual(result["today_post_count"], 0)
        self.assertEqual(result["today_total_post_count"], 1)
        self.assertEqual(result["daily_workflow"]["status"], "no_run_today")
        self.assertEqual(result["publication_evidence"]["status"], "feed_confirmed_needs_workflow_check")
        notification.return_value.send_required.assert_called_once()

    def test_run_flags_more_than_one_public_post_today(self) -> None:
        posts = [
            {
                "title": "First post",
                "url": "https://easypcfixguide.blogspot.com/2026/06/first-post.html",
                "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
            },
            {
                "title": "Second post",
                "url": "https://easypcfixguide.blogspot.com/2026/06/second-post.html",
                "published_kst": datetime(2026, 6, 25, 9, 28, tzinfo=ZoneInfo("Asia/Seoul")),
            },
        ]

        with patch.object(stage4_publication_check, "fetch_public_feed", return_value={}), patch.object(
            stage4_publication_check, "parse_posts", return_value=posts
        ), patch.object(
            stage4_publication_check, "check_daily_workflow_status", return_value={"status": "success", "today_run_count": 2}
        ), patch.object(
            stage4_publication_check, "read_daily_success_report", return_value={"status": "published", "mode": "publish"}
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            result = stage4_publication_check.run(
                "easy_pc_fix_guide",
                today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                after_hour=9,
                notify=True,
            )

        self.assertEqual(result["status"], "duplicate_today")
        self.assertEqual(result["today_post_count"], 2)
        self.assertEqual(result["today_total_post_count"], 2)
        self.assertEqual(result["publication_evidence"]["status"], "duplicate_publication_detected")
        self.assertTrue(result["publication_evidence"]["needs_attention"])
        sent_message = notification.return_value.send_required.call_args.args[0]
        self.assertIn("오늘 공개 글 2개 이상 감지", sent_message)
        self.assertIn("하루 1개 운영 기준을 초과", sent_message)
        saved = json.loads((Path(self._tmpdir.name) / "reports" / "easy_pc_fix_guide-publication-check.json").read_text(encoding="utf-8"))
        self.assertIn("수동 발행/예약 발행/백업 workflow", "\n".join(saved["action_items"]))
        self.assertIn("중복 글", "\n".join(saved["action_items"]))

    def test_run_raises_when_publication_check_notification_fails(self) -> None:
        post = {
            "title": "Fresh post",
            "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage4_publication_check, "ROOT_DIR", Path(tmpdir)), patch.object(
            stage4_publication_check, "fetch_public_feed", return_value={}
        ), patch.object(stage4_publication_check, "parse_posts", return_value=[post]), patch.object(
            stage4_publication_check, "check_daily_workflow_status", return_value={"status": "success", "today_run_count": 1}
        ), patch.object(stage4_publication_check, "read_daily_success_report", return_value={"status": "not_uploaded"}), patch(
            "src.pipeline.stage4_publication_check.NotificationClient"
        ) as notification:
            notification.return_value.send_required.side_effect = RuntimeError("telegram failed")

            with self.assertRaises(RuntimeError):
                stage4_publication_check.run(
                    "easy_pc_fix_guide",
                    today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                    after_hour=9,
                    notify=True,
                )
            report_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-publication-check.json"
            markdown_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-publication-check.md"
            saved = json.loads(report_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(saved["status"], "published_today")
        self.assertEqual(saved["publication_evidence"]["status"], "feed_and_workflow_confirmed_report_unavailable")
        self.assertIn("[Posting Bot] 공개 발행 확인", saved["human_summary"])
        self.assertIn("Fresh post", markdown)

    def test_run_writes_error_report_when_public_feed_fails(self) -> None:
        with patch.object(
            stage4_publication_check,
            "fetch_public_feed",
            side_effect=RuntimeError("feed unavailable"),
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            with self.assertRaises(RuntimeError):
                stage4_publication_check.run(
                    "easy_pc_fix_guide",
                    today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                    after_hour=9,
                    notify=True,
                )

            report_path = Path(self._tmpdir.name) / "reports" / "easy_pc_fix_guide-publication-check.json"
            markdown_path = Path(self._tmpdir.name) / "reports" / "easy_pc_fix_guide-publication-check.md"
            saved = json.loads(report_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["error_type"], "RuntimeError")
        self.assertIn("feed unavailable", saved["error"])
        self.assertIn("publication_check_error", saved["publication_evidence"]["status"])
        self.assertIn("action_items", saved)
        self.assertIn("publication check를 다시 실행", "\n".join(saved["action_items"]))
        self.assertIn("발행 확인 오류", saved["human_summary"])
        self.assertIn("공개 발행 확인 실행 오류", markdown)
        notification.return_value.send_required.assert_called_once()

    def test_run_preserves_feed_error_when_failure_notification_fails(self) -> None:
        with patch.object(
            stage4_publication_check,
            "fetch_public_feed",
            side_effect=RuntimeError("feed unavailable"),
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            notification.return_value.send_required.side_effect = RuntimeError("telegram failed")

            with self.assertRaises(RuntimeError) as raised:
                stage4_publication_check.run(
                    "easy_pc_fix_guide",
                    today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                    after_hour=9,
                    notify=True,
                )

            report_path = Path(self._tmpdir.name) / "reports" / "easy_pc_fix_guide-publication-check.json"
            saved = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertIn("feed unavailable", str(raised.exception))
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["error"], "feed unavailable")
        self.assertEqual(saved["notification_error"]["error"], "telegram failed")

    def test_run_can_skip_notification_for_local_smoke_check(self) -> None:
        post = {
            "title": "Fresh post",
            "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
            "published_kst": datetime(2026, 6, 25, 9, 12, tzinfo=ZoneInfo("Asia/Seoul")),
        }

        with patch.object(stage4_publication_check, "fetch_public_feed", return_value={}), patch.object(
            stage4_publication_check, "parse_posts", return_value=[post]
        ), patch.object(
            stage4_publication_check, "check_daily_workflow_status", return_value={"status": "success", "today_run_count": 1}
        ), patch.object(
            stage4_publication_check, "read_daily_success_report", return_value={"status": "published", "mode": "publish"}
        ), patch("src.pipeline.stage4_publication_check.NotificationClient") as notification:
            result = stage4_publication_check.run(
                "easy_pc_fix_guide",
                today=datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul")),
                after_hour=9,
                notify=False,
            )

        self.assertEqual(result["status"], "published_today")
        notification.assert_not_called()

    def test_main_accepts_today_post_before_cutoff(self) -> None:
        early_result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "site_url": "https://easypcfixguide.blogspot.com",
            "checked_at_kst": "2026-06-25T09:45:00+09:00",
            "cutoff_kst": "2026-06-25T09:00:00+09:00",
            "status": "published_today_before_cutoff",
            "today_post_count": 0,
            "today_total_post_count": 1,
            "latest_posts": [],
        }

        with patch.object(stage4_publication_check, "run", return_value=early_result) as run, patch.object(
            stage4_publication_check, "save_result"
        ), patch("sys.argv", ["stage4_publication_check", "--no-notify"]):
            stage4_publication_check.main()

        run.assert_called_once_with(None, after_hour=None, notify=False)

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
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage4_publication_check, "ROOT_DIR", Path(tmpdir)):
            path = stage4_publication_check.save_result(result)
            markdown_path = Path(tmpdir) / "reports" / "easy_pc_fix_guide-publication-check.md"
            saved_exists = path.exists()
            saved = json.loads(path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertTrue(saved_exists)
        self.assertEqual(saved["status"], "published_today")
        self.assertIn("action_items", saved)
        self.assertIn("증거가 완전히 일치하지 않습니다", "\n".join(saved["action_items"]))
        self.assertIn("human_summary", saved)
        self.assertIn("[Posting Bot] 공개 발행 확인", markdown)

    def test_save_result_writes_missing_publication_action_items(self) -> None:
        result = {
            "site": "easy_pc_fix_guide",
            "site_name": "Easy PC Fix Guide",
            "site_url": "https://easypcfixguide.blogspot.com",
            "checked_at_kst": "2026-06-25T09:45:00+09:00",
            "cutoff_kst": "2026-06-25T09:00:00+09:00",
            "status": "missing_today",
            "today_post_count": 0,
            "today_total_post_count": 0,
            "daily_workflow": {"status": "failed"},
            "daily_success_context": {"status": "validation_only", "publish_related": False},
            "latest_posts": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage4_publication_check, "ROOT_DIR", Path(tmpdir)):
            path = stage4_publication_check.save_result(result)
            saved = json.loads(path.read_text(encoding="utf-8"))
            markdown = (Path(tmpdir) / "reports" / "easy_pc_fix_guide-publication-check.md").read_text(encoding="utf-8")

        joined = "\n".join(saved["action_items"])
        self.assertIn("Easy PC Fix Daily Publish 실행 결과", joined)
        self.assertIn("daily-failure.json", joined)
        self.assertIn("실패한 primary/backup run", joined)
        self.assertIn("validate 결과", joined)
        self.assertIn("조치 필요:", markdown)
        self.assertIn("daily-failure.json", markdown)

    def test_publication_message_uses_fallback_daily_context_label(self) -> None:
        message = stage4_publication_check.build_message(
            {
                "site": "easy_pc_fix_guide",
                "site_name": "Easy PC Fix Guide",
                "site_url": "https://easypcfixguide.blogspot.com",
                "checked_at_kst": "2026-06-25T09:45:00+09:00",
                "cutoff_kst": "2026-06-25T09:00:00+09:00",
                "status": "missing_today",
                "today_post_count": 0,
                "today_total_post_count": 0,
                "daily_success_context": {"status": "validation_only"},
                "publication_evidence": {
                    "label": "공개 발행 증거 없음",
                    "needs_attention": True,
                },
                "latest_posts": [],
            }
        )

        self.assertIn("최근 일일 리포트 구분: 판단 필요", message)
        self.assertNotIn("None", message)

    def test_daily_workflow_status_summarizes_today_success_run(self) -> None:
        runs = [
            {
                "id": 123,
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-06-25T00:25:07Z",
                "html_url": "https://github.com/run/123",
                "head_sha": "abcdef123456",
            }
        ]

        with patch.object(stage4_publication_check, "fetch_daily_workflow_runs", return_value=runs):
            result = stage4_publication_check.check_daily_workflow_status(
                datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul"))
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["today_run_count"], 1)
        self.assertEqual(result["success_run_count"], 1)
        self.assertEqual(result["failed_run_count"], 0)
        self.assertEqual(result["in_progress_run_count"], 0)
        self.assertEqual(result["latest_run"]["head_sha"], "abcdef1")

    def test_daily_workflow_status_flags_mixed_success_and_failure_runs(self) -> None:
        runs = [
            {
                "id": 124,
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-06-25T00:25:07Z",
                "html_url": "https://github.com/run/124",
                "head_sha": "abcdeffedcba",
            },
            {
                "id": 123,
                "event": "schedule",
                "status": "completed",
                "conclusion": "failure",
                "created_at": "2026-06-25T00:10:07Z",
                "html_url": "https://github.com/run/123",
                "head_sha": "abcdef123456",
            },
        ]

        with patch.object(stage4_publication_check, "fetch_daily_workflow_runs", return_value=runs):
            result = stage4_publication_check.check_daily_workflow_status(
                datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul"))
            )

        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["today_run_count"], 2)
        self.assertEqual(result["success_run_count"], 1)
        self.assertEqual(result["failed_run_count"], 1)

    def test_daily_workflow_status_reports_no_run_today(self) -> None:
        with patch.object(stage4_publication_check, "fetch_daily_workflow_runs", return_value=[]):
            result = stage4_publication_check.check_daily_workflow_status(
                datetime(2026, 6, 25, 9, 45, tzinfo=ZoneInfo("Asia/Seoul"))
            )

        self.assertEqual(result["status"], "no_run_today")
        self.assertEqual(result["today_run_count"], 0)

    def test_publication_message_surfaces_confirmed_post_url(self) -> None:
        message = stage4_publication_check.build_message(
            {
                "site_name": "Easy PC Fix Guide",
                "site_url": "https://easypcfixguide.blogspot.com",
                "checked_at_kst": "2026-06-25T09:45:00+09:00",
                "cutoff_kst": "2026-06-25T09:00:00+09:00",
                "status": "published_today",
                "today_post_count": 1,
                "daily_workflow": {
                    "status": "success",
                    "today_run_count": 1,
                    "latest_run": {
                        "created_at_kst": "2026-06-25T09:25:07+09:00",
                        "conclusion": "success",
                        "url": "https://github.com/run/123",
                    },
                },
                "daily_success": {
                    "status": "validated",
                    "mode": "validate",
                    "operational_status": {
                        "publish_quality_ok": True,
                        "collection_status_label": "주의: fallback 질문 의존",
                        "ready_for_cadence_increase": False,
                        "status_label": "발행 품질 OK, 수집 안정성 점검 필요",
                    },
                },
                "publication_evidence": {
                    "status": "feed_and_workflow_confirmed_report_not_publish",
                    "label": "공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님",
                    "note": "최근 일일 성공 리포트는 validate 실행 결과이며 공개 발행 결과가 아닙니다.",
                    "needs_attention": True,
                },
                "latest_posts": [
                    {
                        "title": "Fresh post",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
                        "published_kst": "2026-06-25T09:12:00+09:00",
                    }
                ],
            }
        )

        self.assertIn("- 확인된 최신 글: Fresh post", message)
        self.assertIn("- 최신 글 URL: https://easypcfixguide.blogspot.com/2026/06/fresh-post.html", message)
        self.assertIn("- Daily workflow 상태: 오늘 실행 성공", message)
        self.assertIn("- 오늘 Daily workflow 성공 수: 0", message)
        self.assertIn("- 오늘 Daily workflow 실패 수: 0", message)
        self.assertIn("- 최근 일일 리포트 구분: 검증 모드 리포트", message)
        self.assertIn("공개 발행 결과가 아닙니다", message)
        self.assertIn("- 발행 증거 판정: 공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님", message)
        self.assertIn("추가 확인 필요: 예", message)
        self.assertIn("검수 결과이며 발행 완료 리포트가 아닙니다", message)
        self.assertIn("공개 URL과 오늘 Daily publish 리포트가 같은 실행에서 나온 결과인지 확인하세요", message)
        self.assertIn("- 최근 일일 운영 상태: 발행 품질 OK, 수집 안정성 점검 필요", message)
        self.assertIn("발행량 증량 준비: 아니오", message)

    def test_publication_message_warns_about_partial_workflow_failure(self) -> None:
        message = stage4_publication_check.build_message(
            {
                "site_name": "Easy PC Fix Guide",
                "site_url": "https://easypcfixguide.blogspot.com",
                "checked_at_kst": "2026-06-25T09:45:00+09:00",
                "cutoff_kst": "2026-06-25T09:00:00+09:00",
                "status": "published_today",
                "today_post_count": 1,
                "today_total_post_count": 1,
                "daily_workflow": {
                    "status": "partial_failure",
                    "today_run_count": 2,
                    "success_run_count": 1,
                    "failed_run_count": 1,
                    "in_progress_run_count": 0,
                    "latest_run": {
                        "created_at_kst": "2026-06-25T09:25:07+09:00",
                        "conclusion": "success",
                        "url": "https://github.com/run/124",
                    },
                },
                "daily_success": {"status": "published", "mode": "publish"},
                "daily_success_context": {
                    "status": "publish_related",
                    "publish_related": True,
                    "label": "발행 workflow 리포트",
                },
                "latest_posts": [
                    {
                        "title": "Fresh post",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/fresh-post.html",
                        "published_kst": "2026-06-25T09:12:00+09:00",
                    }
                ],
            }
        )

        self.assertIn("- Daily workflow 상태: 오늘 일부 실행 실패", message)
        self.assertIn("- 오늘 Daily workflow 실패 수: 1", message)
        self.assertIn("오늘 Daily workflow 실패 기록도 있습니다", message)
        self.assertIn("실패한 primary/backup 실행 로그", message)

    def test_classifies_publish_related_daily_success_report(self) -> None:
        result = stage4_publication_check.classify_daily_success_context({"status": "published", "mode": "publish"})

        self.assertEqual(result["status"], "publish_related")
        self.assertTrue(result["publish_related"])

    def test_classifies_validation_only_daily_success_report(self) -> None:
        result = stage4_publication_check.classify_daily_success_context({"status": "validated", "mode": "validate"})

        self.assertEqual(result["status"], "validation_only")
        self.assertFalse(result["publish_related"])

    def test_assess_publication_evidence_flags_workflow_success_without_feed(self) -> None:
        result = stage4_publication_check.assess_publication_evidence(
            {
                "status": "missing_today",
                "daily_workflow": {"status": "success"},
                "daily_success": {"status": "published", "mode": "publish"},
                "daily_success_context": {
                    "status": "publish_related",
                    "publish_related": True,
                    "label": "발행 workflow 리포트",
                },
            }
        )

        self.assertEqual(result["status"], "workflow_or_report_without_public_feed")
        self.assertTrue(result["needs_attention"])
        self.assertIn("공개 피드", result["label"])

    def test_assess_publication_evidence_accepts_missing_report_when_feed_and_workflow_match(self) -> None:
        result = stage4_publication_check.assess_publication_evidence(
            {
                "status": "published_today",
                "daily_workflow": {"status": "success"},
                "daily_success": {"status": "not_uploaded"},
                "daily_success_context": {
                    "status": "not_uploaded",
                    "publish_related": False,
                    "label": "일일 성공 리포트 없음",
                },
            }
        )

        self.assertEqual(result["status"], "feed_and_workflow_confirmed_report_unavailable")
        self.assertFalse(result["needs_attention"])
        self.assertIn("artifact", result["label"])

    def test_publication_message_explains_before_cutoff_post(self) -> None:
        message = stage4_publication_check.build_message(
            {
                "site_name": "Easy PC Fix Guide",
                "site_url": "https://easypcfixguide.blogspot.com",
                "checked_at_kst": "2026-06-25T09:45:00+09:00",
                "cutoff_kst": "2026-06-25T09:00:00+09:00",
                "status": "published_today_before_cutoff",
                "today_post_count": 0,
                "today_total_post_count": 1,
                "daily_workflow": {"status": "no_run_today", "today_run_count": 0},
                "latest_posts": [
                    {
                        "title": "Early post",
                        "url": "https://easypcfixguide.blogspot.com/2026/06/early-post.html",
                        "published_kst": "2026-06-25T00:12:00+09:00",
                    }
                ],
            }
        )

        self.assertIn("오늘 공개 글 확인, 기준시각 전 발행", message)
        self.assertIn("- 확인된 오늘 글: Early post", message)
        self.assertIn("- 오늘 전체 공개 글 수: 1", message)
        self.assertIn("오늘 글은 확인됐지만 기준시각 이후 자동 발행 증거는 아직 부족합니다", message)
        self.assertIn("공개 글은 확인됐지만 Daily workflow 상태 점검이 필요합니다.", message)


if __name__ == "__main__":
    unittest.main()
