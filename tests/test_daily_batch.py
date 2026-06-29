from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from src.content.article_types import infer_article_type
from src.pipeline import daily_batch
from src.pipeline.daily_batch import build_combined_morning_message
from src.pipeline.daily_batch import notify_batch_completion
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
            "src.pipeline.daily_batch.public_recent_categories", return_value=[]
        ), patch(
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
        ), patch("src.pipeline.daily_batch.public_recent_categories", return_value=[]), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
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
            "src.pipeline.daily_batch.public_recent_categories", return_value=[]
        ), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

    def test_windows_batch_moves_recent_network_category_behind_other_topics(self) -> None:
        seeds = [
            "wifi keeps disconnecting windows 11",
            "dns server not responding windows 11",
            "network adapter missing windows 11",
            "windows update error 0x80070005",
            "how to check windows version",
            "printer offline windows 11",
        ]
        with patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=seeds), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch("src.pipeline.daily_batch.public_post_titles", return_value=[]), patch(
            "src.pipeline.daily_batch.public_recent_categories", return_value=["Wi-Fi & Internet", "Wi-Fi & Internet"]
        ), patch("src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

        self.assertEqual([item["category"] for item in selected], [
            "Windows Update",
            "Beginner PC Tips",
            "Printer & Scanner",
        ])
        self.assertNotIn("Wi-Fi & Internet", [item["category"] for item in selected])

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
        ), patch("src.pipeline.daily_batch.public_recent_categories", return_value=[]), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
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
            "src.pipeline.daily_batch.public_recent_categories", return_value=[]
        ), patch(
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

    def test_combined_morning_message_lists_both_blogs(self) -> None:
        now = datetime(2026, 6, 27, 9, 58, tzinfo=ZoneInfo("Asia/Seoul"))
        posts_by_url = {
            "https://easypcfixguide.blogspot.com": [
                {
                    "title": "PC One",
                    "url": "https://easypcfixguide.blogspot.com/pc-one.html",
                    "published_kst": now,
                }
            ],
            "https://koreaeasyguide.blogspot.com": [
                {
                    "title": "Korea One",
                    "url": "https://koreaeasyguide.blogspot.com/korea-one.html",
                    "published_kst": now,
                },
                {
                    "title": "Korea Two",
                    "url": "https://koreaeasyguide.blogspot.com/korea-two.html",
                    "published_kst": now,
                },
            ],
        }

        def fake_today_public_posts(site_url: str, selected_now: datetime | None = None) -> list[dict]:
            return posts_by_url[site_url]

        with patch.object(daily_batch, "today_public_posts", side_effect=fake_today_public_posts):
            message = build_combined_morning_message(now)

        self.assertIn("전체 목표: 6개", message)
        self.assertIn("공개 확인: 3개", message)
        self.assertIn("[Easy PC Fix Guide] 1/3개", message)
        self.assertIn("[Korea Easy Guide] 2/3개", message)
        self.assertIn("PC One", message)
        self.assertIn("Korea Two", message)
        self.assertIn("중복 주제는 발행하지 않고 건너뜁니다", message)

    def test_scheduled_pc_batch_suppresses_individual_notification(self) -> None:
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "schedule"}), patch(
            "src.pipeline.daily_batch.NotificationClient"
        ) as notification:
            notify_batch_completion({"site": "easy_pc_fix_guide"})

        notification.assert_not_called()

    def test_scheduled_korea_batch_sends_one_combined_notification(self) -> None:
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "schedule"}), patch(
            "src.pipeline.daily_batch.build_combined_morning_message", return_value="combined"
        ), patch("src.pipeline.daily_batch.NotificationClient") as notification:
            notify_batch_completion({"site": "korea_easy_guide"})

        notification.return_value.send_required.assert_called_once_with("combined")


if __name__ == "__main__":
    unittest.main()
