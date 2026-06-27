from __future__ import annotations

import unittest
from unittest.mock import patch

from src.content.article_types import infer_article_type
from src.pipeline.daily_batch import select_seed_candidates
from src.pipeline.daily_batch import seed_matches_existing_public_title


class DailyBatchSelectionTests(unittest.TestCase):
    def test_windows_article_type_classification_separates_code_symptom_and_beginner(self) -> None:
        self.assertEqual(
            infer_article_type("windows update error 0x80070005", "Windows Update", "windows_help"),
            "error_code_fix",
        )
        self.assertEqual(
            infer_article_type("wifi button missing windows 11", "Wi-Fi & Internet", "windows_help"),
            "symptom_fix",
        )
        self.assertEqual(
            infer_article_type("how to check windows version", "Beginner PC Tips", "windows_help"),
            "beginner_guide",
        )

    def test_windows_batch_selects_distinct_article_types_without_generating_all_candidates(self) -> None:
        seeds = [
            "wifi button missing windows 11",
            "printer offline windows 11",
            "windows update error 0x80070005",
            "windows update error 0x80070643",
            "how to check windows version",
        ]
        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch("src.pipeline.daily_batch.public_post_titles", return_value=[]), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

        self.assertEqual([item["seed"] for item in selected], [
            "wifi button missing windows 11",
            "windows update error 0x80070005",
            "how to check windows version",
        ])
        self.assertEqual({item["article_type"] for item in selected}, {
            "symptom_fix",
            "error_code_fix",
            "beginner_guide",
        })

    def test_windows_batch_skips_existing_public_title_before_generation(self) -> None:
        seeds = [
            "windows update error 0x80073712",
            "windows update error 0x80070005",
            "how to check windows version",
        ]
        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch(
            "src.pipeline.daily_batch.public_post_titles",
            return_value=["Windows Update Error 0X80073712: What It Means and How to Fix It"],
        ), patch("src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

        self.assertNotIn("windows update error 0x80073712", [item["seed"] for item in selected])

    def test_batch_skips_already_generated_candidates_to_reduce_waste(self) -> None:
        seeds = [
            "wifi button missing windows 11",
            "windows update error 0x80070005",
            "how to check windows version",
        ]

        def used_keywords_for_call(site: str, include_validation: bool = True) -> set[str]:
            return {"wifi button missing windows 11"} if include_validation else set()

        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", side_effect=used_keywords_for_call
        ), patch("src.pipeline.daily_batch.public_post_titles", return_value=[]), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

        self.assertNotIn("wifi button missing windows 11", [item["seed"] for item in selected])

    def test_korea_batch_skips_existing_public_title_before_generation(self) -> None:
        seeds = [
            "how to buy ktx tickets in korea",
            "korea esim guide for tourists",
            "how to use kakao taxi as a foreigner",
        ]
        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch(
            "src.pipeline.daily_batch.public_post_titles",
            return_value=["How to Buy KTX Tickets in Korea as a Foreigner"],
        ), patch("src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}):
            selected = select_seed_candidates("korea_easy_guide", "korea_travel", 3)

        self.assertNotIn("how to buy ktx tickets in korea", [item["seed"] for item in selected])

    def test_korea_batch_allows_not_applicable_precheck_but_still_diversifies_type(self) -> None:
        seeds = [
            "how to use kakao taxi as a foreigner",
            "naver map for foreigners",
            "where to stay in seoul first time",
            "korea esim for tourists",
        ]
        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch("src.pipeline.daily_batch.public_post_titles", return_value=[]), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "not_applicable"}
        ):
            selected = select_seed_candidates("korea_easy_guide", "korea_travel", 3)

        self.assertLessEqual(len(selected), 3)
        self.assertEqual(len({item["article_type"] for item in selected}), len(selected))

    def test_batch_prefilter_skips_existing_public_topic_titles(self) -> None:
        self.assertTrue(
            seed_matches_existing_public_title(
                "how to buy ktx tickets in korea",
                ["How to Buy KTX Tickets in Korea as a Foreigner"],
            )
        )
        self.assertTrue(
            seed_matches_existing_public_title(
                "windows update error 0x80073712",
                ["Windows Update Error 0X80073712: What It Means and How to Fix It"],
            )
        )
        self.assertFalse(
            seed_matches_existing_public_title(
                "korea esim guide for tourists",
                ["How to Buy KTX Tickets in Korea as a Foreigner"],
            )
        )


if __name__ == "__main__":
    unittest.main()
