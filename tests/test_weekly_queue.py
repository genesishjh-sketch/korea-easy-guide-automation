from __future__ import annotations

from datetime import date
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline import daily_batch
from src.pipeline import weekly_queue


class WeeklyQueueTests(unittest.TestCase):
    def test_generate_weekly_queue_skips_existing_public_title_and_schedules_distinct_days(self) -> None:
        seeds = [
            "how to buy ktx tickets in korea",
            "korea tax refund for tourists",
            "wowpass korea for tourists",
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(weekly_queue, "QUEUE_DIR", Path(temp_dir)), patch(
            "src.pipeline.weekly_queue.choose_publish_seed_candidates", return_value=seeds
        ), patch("src.pipeline.weekly_queue.used_keywords", return_value=set()), patch(
            "src.pipeline.weekly_queue.public_post_titles",
            return_value=["How to Buy KTX Tickets in Korea as a Foreigner"],
        ), patch("src.pipeline.weekly_queue.seed_quality_precheck", return_value={"status": "ready"}):
            queue = weekly_queue.generate_weekly_queue(
                site="korea_easy_guide",
                start_date=date(2026, 7, 6),
                days=2,
                posts_per_day=1,
                notify=False,
            )

        seeds_in_queue = [item["seed"] for item in queue["items"]]
        self.assertNotIn("how to buy ktx tickets in korea", seeds_in_queue)
        self.assertEqual(seeds_in_queue, ["korea tax refund for tourists", "wowpass korea for tourists"])
        self.assertEqual([item["date"] for item in queue["items"]], ["2026-07-06", "2026-07-07"])

    def test_today_queue_candidates_loads_matching_week_file(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "date": "2026-07-06",
                    "seed": "windows update error 0x80070005",
                    "category": "Windows Update",
                    "article_type": "error_code_fix",
                    "quality_precheck": {"status": "ready"},
                    "difference_from_existing": "Different error code.",
                    "image_direction": "Use a distinct update error visual.",
                    "status": "scheduled",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(weekly_queue, "QUEUE_DIR", Path(temp_dir)):
            path = weekly_queue.weekly_queue_path("easy_pc_fix_guide", date(2026, 7, 6))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(weekly_queue.json.dumps(queue, ensure_ascii=False), encoding="utf-8")

            candidates = weekly_queue.today_queue_candidates(
                "easy_pc_fix_guide",
                selected_date=date(2026, 7, 6),
                max_posts=3,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["seed"], "windows update error 0x80070005")
        self.assertEqual(candidates[0]["weekly_queue"]["week"], "2026-W28")

    def test_daily_batch_prefers_weekly_queue_over_fallback_selection(self) -> None:
        queued_candidate = {
            "seed": "korea tax refund for tourists",
            "category": "Shopping",
            "article_type": "checklist",
            "quality_precheck": {"status": "ready"},
            "recent_category": False,
            "weekly_queue": {"week": "2026-W28"},
        }
        with patch("src.pipeline.daily_batch.today_queue_candidates", return_value=[queued_candidate]), patch(
            "src.pipeline.daily_batch.choose_publish_seed_candidates"
        ) as chooser:
            selected = daily_batch.select_seed_candidates("korea_easy_guide", "korea_travel", 3)

        chooser.assert_not_called()
        self.assertEqual(selected, [queued_candidate])

    def test_three_post_days_use_two_evergreen_and_one_trend_slot(self) -> None:
        candidates = [
            {
                "seed": "how to use naver map in korea",
                "category": "Apps in Korea",
                "article_type": "how_to",
                "slot_strategy": weekly_queue.EVERGREEN_SLOT,
                "strategy_reason": "evergreen",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
            {
                "seed": "korea esim guide for tourists",
                "category": "Mobile & Internet",
                "article_type": "checklist",
                "slot_strategy": weekly_queue.EVERGREEN_SLOT,
                "strategy_reason": "evergreen",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
            {
                "seed": "korea rainy season travel tips",
                "category": "Travel Basics",
                "article_type": "checklist",
                "slot_strategy": weekly_queue.TREND_SLOT,
                "strategy_reason": "seasonal",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
        ]

        items = weekly_queue.assign_candidates_to_week(
            candidates,
            start_date=date(2026, 7, 6),
            days=1,
            posts_per_day=3,
            site="korea_easy_guide",
        )

        self.assertEqual([item["slot_strategy"] for item in items], [
            weekly_queue.EVERGREEN_SLOT,
            weekly_queue.EVERGREEN_SLOT,
            weekly_queue.TREND_SLOT,
        ])
        self.assertEqual(items[2]["seed"], "korea rainy season travel tips")
        self.assertFalse(items[2]["strategy_fallback"])

    def test_candidate_from_queue_exposes_strategy_metadata(self) -> None:
        queue = {"week": "2026-W28", "_path": "/tmp/queue.json"}
        item = {
            "date": "2026-07-06",
            "seed": "windows 11 slow after update",
            "category": "Beginner PC Tips",
            "article_type": "beginner_guide",
            "slot_strategy": weekly_queue.TREND_SLOT,
            "strategy_reason": "Windows update or recent-issue demand",
        }

        candidate = weekly_queue.candidate_from_queue_item(queue, item)

        self.assertEqual(candidate["weekly_queue"]["slot_strategy"], weekly_queue.TREND_SLOT)
        self.assertIn("recent-issue", candidate["weekly_queue"]["strategy_reason"])


if __name__ == "__main__":
    unittest.main()
