from __future__ import annotations

from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from src.pipeline.topic_intelligence_monitor import build_monitor_report
from src.topics.defaults import default_categories
from src.topics.sheet_sync import record_sheet_sync
from src.topics.store import TopicStore


SITE = "korea_easy_guide"
KST = ZoneInfo("Asia/Seoul")


class TopicIntelligenceMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.store.ensure_site(SITE, default_categories(SITE))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_monitor_reports_missing_backfill_run_queue_and_sheet(self) -> None:
        report = build_monitor_report(
            self.store,
            [SITE],
            now=datetime(2026, 7, 31, 14, 0, tzinfo=KST),
            queue_loader=lambda *_args: None,
        )

        codes = {
            item["code"]
            for item in report["sites"][0]["issues"]
        }
        self.assertEqual(report["status"], "ATTENTION")
        self.assertIn("BACKFILL_INCOMPLETE", codes)
        self.assertIn("WEEKLY_RUN_MISSING", codes)
        self.assertIn("CURRENT_QUEUE_MISSING", codes)

    def test_monitor_accepts_current_legacy_queue_after_successful_sync(self) -> None:
        self.store.record_rollout_run(
            SITE,
            "completed-backfill",
            "SUCCESS",
            run_at="2026-07-25T10:00:00+09:00",
            details={
                "run_type": "BACKFILL_RESEARCH",
                "complete": True,
                "schema_valid": True,
                "coverage_hash": "coverage-v1",
                "logic_version": "test-v1",
                "unexplored_scope": [],
            },
        )
        self.store.record_rollout_run(
            SITE,
            "weekly-current",
            "SUCCESS",
            run_at="2026-07-26T20:00:00+09:00",
            details={
                "run_type": "WEEKLY_RESEARCH",
                "complete": True,
                "schema_valid": True,
                "ready_evidence_locator_coverage": 1.0,
                "synthetic_influence_count": 0,
                "blogger_duplicate_count": 0,
                "auditor_passed": True,
                "source_count": 1,
            },
        )
        record_sheet_sync(
            self.store,
            SITE,
            "weekly-current",
            "SUCCESS",
        )
        report = build_monitor_report(
            self.store,
            [SITE],
            now=datetime(2026, 7, 31, 14, 0, tzinfo=KST),
            queue_loader=lambda *_args: {
                "_path": "legacy.json",
                "items": [{"topic_source": "legacy"}],
            },
        )

        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["sites"][0]["issues"], [])


if __name__ == "__main__":
    unittest.main()
