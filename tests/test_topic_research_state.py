from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.research_state import ResearchCampaignStore
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


class ResearchCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.topic_store = TopicStore(Path(self.temp.name) / "topics")
        self.campaigns = ResearchCampaignStore(self.topic_store)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create(self) -> dict:
        return self.campaigns.create(
            SITE,
            "backfill-2026",
            run_type="BACKFILL_RESEARCH",
            window_start="2025-08-01",
            window_end="2026-07-31",
            logic_version="v2",
            work_items=[
                {
                    "work_id": "reddit-transit",
                    "source": "reddit",
                    "query_family": "transit",
                    "required": True,
                },
                {
                    "work_id": "quora-transit",
                    "source": "quora",
                    "query_family": "transit",
                    "required": False,
                },
            ],
        )

    def test_campaign_resumes_from_checkpoint_without_duplicate_ids(self) -> None:
        created = self._create()
        claimed = self.campaigns.claim_next(SITE, created["campaign_id"])
        self.assertEqual(claimed["work_id"], "reddit-transit")
        paused = self.campaigns.checkpoint(
            SITE,
            created["campaign_id"],
            "reddit-transit",
            state="PAUSED",
            cursor="page-2",
            discovered_ids=["q-1", "q-1"],
        )
        self.assertEqual(paused["state"], "PAUSED")

        resumed = self.campaigns.claim_next(SITE, created["campaign_id"])
        self.assertEqual(resumed["cursor"], "page-2")
        self.assertEqual(resumed["attempts"], 2)
        self.assertEqual(resumed["discovered_ids"], ["q-1"])

    def test_optional_blocked_source_does_not_block_completion(self) -> None:
        created = self._create()
        self.campaigns.checkpoint(
            SITE,
            created["campaign_id"],
            "reddit-transit",
            state="DONE",
            cursor="end",
        )
        completed = self.campaigns.checkpoint(
            SITE,
            created["campaign_id"],
            "quora-transit",
            state="BLOCKED",
            last_error="login required",
        )

        self.assertEqual(completed["state"], "DONE")
        metadata = self.campaigns.bundle_metadata(SITE, created["campaign_id"])
        self.assertTrue(metadata["complete"])
        self.assertEqual(metadata["unexplored_scope"], [])

    def test_campaign_id_is_content_addressed(self) -> None:
        self._create()
        with self.assertRaisesRegex(ValueError, "content mismatch"):
            self.campaigns.create(
                SITE,
                "backfill-2026",
                run_type="BACKFILL_RESEARCH",
                window_start="2025-08-01",
                window_end="2026-07-31",
                logic_version="v3",
                work_items=[
                    {
                        "work_id": "reddit-transit",
                        "source": "reddit",
                        "query_family": "transit",
                        "required": True,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
