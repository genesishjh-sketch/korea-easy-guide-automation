from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.run_repair import apply_run_projection_repairs
from src.topics.run_repair import audit_run_projections
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


class RunProjectionRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.store.ensure_site(SITE, default_categories(SITE))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_repairs_append_a_record_without_overwriting_archive(self) -> None:
        run_id = "historical-run"
        bundle = {
            "run_id": run_id,
            "ended_at": "2026-07-29T01:30:00+09:00",
            "questions": [
                {
                    "question_id": "q-1",
                    "source": "reddit",
                    "source_id": "source-1",
                    "url": "https://www.reddit.com/r/koreatravel/comments/1/q",
                    "title": "Question",
                    "summary": "Summary",
                    "evidence_type": "OBSERVED_QUESTION",
                    "verified_by_codex": True,
                }
            ],
            "unexplored_scope": ["Additional Windows device-specific problems"],
        }
        archive = self.store.site_dir(SITE) / "runs" / f"{run_id}.json"
        self.store._atomic_write(archive, bundle)
        self.store.record_rollout_run(
            SITE,
            run_id,
            "DEGRADED",
            run_at=bundle["ended_at"],
            details={
                "run_type": "BACKFILL_RESEARCH",
                "verified_questions": 0,
                "source_count": 0,
                "complete": False,
            },
        )
        original = archive.read_text(encoding="utf-8")

        audit = audit_run_projections(self.store, SITE)
        self.assertEqual(audit["repair_count"], 1)
        self.assertEqual(
            audit["repairs"][0]["changes"]["verified_questions"]["expected"],
            1,
        )
        self.assertEqual(
            audit["repairs"][0]["changes"]["unexplored_scope"]["expected"],
            [],
        )
        self.assertTrue(audit["scope_warnings"])

        applied = apply_run_projection_repairs(self.store, SITE)
        self.assertEqual(len(applied["applied_correction_run_ids"]), 1)
        self.assertEqual(archive.read_text(encoding="utf-8"), original)
        repair_record = self.store.get_rollout_state(SITE)["recent_runs"][-1]
        self.assertEqual(
            repair_record["details"]["correction_of"],
            run_id,
        )
        self.assertEqual(
            repair_record["details"]["corrected_details"]["unexplored_scope"],
            [],
        )
        self.assertEqual(audit_run_projections(self.store, SITE)["repair_count"], 0)


if __name__ == "__main__":
    unittest.main()
