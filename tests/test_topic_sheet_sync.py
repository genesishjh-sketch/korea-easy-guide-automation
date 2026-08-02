from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.sheet_export import build_sheet_export
from src.topics.sheet_sync import load_sheet_sync_state
from src.topics.sheet_sync import record_sheet_sync
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


class TopicSheetSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.store.ensure_site(SITE, default_categories(SITE))
        self.store.record_rollout_run(
            SITE,
            "weekly-sync-ledger",
            "DEGRADED",
            run_at="2026-07-26T20:00:00+09:00",
            details={
                "run_type": "WEEKLY_RESEARCH",
                "complete": False,
                "schema_valid": True,
                "ready_evidence_url_coverage": 0.0,
                "synthetic_influence_count": 0,
                "blogger_duplicate_count": 0,
                "auditor_passed": False,
                "source_count": 0,
                "sheet_sync_status": "PENDING",
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_failed_sheet_sync_is_durable_and_success_ack_is_idempotent(self) -> None:
        failed = record_sheet_sync(
            self.store,
            SITE,
            "weekly-sync-ledger",
            "FAILED",
            error="Google Sheets write timed out",
        )
        self.assertTrue(failed["pending"])
        self.assertEqual(failed["attempts"], 1)

        success = record_sheet_sync(
            self.store,
            SITE,
            "weekly-sync-ledger",
            "SUCCESS",
        )
        repeated = record_sheet_sync(
            self.store,
            SITE,
            "weekly-sync-ledger",
            "SUCCESS",
        )
        self.assertFalse(success["pending"])
        self.assertEqual(success["attempts"], 2)
        self.assertEqual(repeated, success)

        persisted = load_sheet_sync_state(self.store, SITE)
        self.assertEqual(
            persisted["runs"]["weekly-sync-ledger"]["status"],
            "SUCCESS",
        )

    def test_sheet_export_overlays_post_import_sync_outcome(self) -> None:
        record_sheet_sync(
            self.store,
            SITE,
            "weekly-sync-ledger",
            "FAILED",
            error="quota",
        )

        export = build_sheet_export(self.store, [SITE])
        row = next(
            item
            for item in export["runs"]
            if item["run_id"] == "weekly-sync-ledger"
        )

        self.assertEqual(row["sheet_sync_status"], "FAILED")
        self.assertTrue(row["sheet_sync_pending"])
        self.assertEqual(row["sheet_sync_error"], "quota")
        self.assertEqual(
            export["dashboard"][0]["sheet_sync_pending_count"],
            1,
        )

    def test_unknown_run_cannot_be_acknowledged(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown topic-intelligence run"):
            record_sheet_sync(
                self.store,
                SITE,
                "unknown-run",
                "SUCCESS",
            )


if __name__ == "__main__":
    unittest.main()
