from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from src.content.article_types import infer_article_type
from src.pipeline import daily_batch
from src.pipeline.daily_batch import build_published_item
from src.pipeline.daily_batch import build_combined_morning_message
from src.pipeline.daily_batch import classify_recovery_issue
from src.pipeline.daily_batch import notify_batch_completion
from src.pipeline.daily_batch import recovery_candidate_limit
from src.pipeline.daily_batch import select_seed_candidates
from src.pipeline.daily_batch import seed_matches_existing_public_title


class DailyBatchSelectionTests(unittest.TestCase):
    def test_published_item_preserves_blogger_live_evidence_for_publication_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(
                json.dumps({"article": {"title": "Verified post"}}),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 100, "metrics": {}}),
                encoding="utf-8",
            )
            publish_result = article_dir / "blogger_publish_result.json"
            publish_result.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "skipped": False,
                        "blogger": {
                            "status": "LIVE",
                            "id": "post-123",
                            "url": "https://example.com/verified.html",
                        },
                    }
                ),
                encoding="utf-8",
            )

            item = build_published_item(
                {
                    "seed": "verified seed",
                    "article_dir": str(article_dir),
                    "publish_result": str(publish_result),
                },
                {
                    "topic_id": "topic-123",
                    "cluster_id": "cluster-123",
                    "category_id": "category-123",
                },
            )

        self.assertEqual(item["blogger_status"], "LIVE")
        self.assertEqual(item["blogger_post_id"], "post-123")
        self.assertEqual(item["topic_id"], "topic-123")
        self.assertFalse(item["draft"])
        self.assertFalse(item["skipped"])

    def test_recovery_candidate_limit_allows_replacement_candidates(self) -> None:
        self.assertEqual(recovery_candidate_limit(1), 3)
        self.assertEqual(recovery_candidate_limit(3), 9)

    def test_recovery_classifies_reusable_images_as_codex_required(self) -> None:
        result = classify_recovery_issue(
            "Reusable image library assets cannot be used for public publishing. Generate fresh article-specific Codex images.",
            None,
        )

        self.assertEqual(result["issue_type"], "image_issue")
        self.assertEqual(result["recovery_status"], "codex_image_required")
        self.assertIn("Codex", result["next_action"])

    def test_recovery_classifies_missing_scene_images_as_codex_required(self) -> None:
        result = classify_recovery_issue(
            "FileNotFoundError: Windows AI image assets are missing for scene 'printer'. "
            "Generate fresh Codex images for this article and save them before publishing.",
            None,
        )

        self.assertEqual(result["issue_type"], "image_issue")
        self.assertEqual(result["recovery_status"], "codex_image_required")

    def test_recovery_classifies_dead_microsoft_links_as_source_issue(self) -> None:
        result = classify_recovery_issue(
            "Hades quality gate failed with score 88/90: dead_microsoft_research_links",
            None,
        )

        self.assertEqual(result["issue_type"], "source_issue")
        self.assertEqual(result["recovery_status"], "candidate_replaced")

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
        ), patch(
            "src.pipeline.daily_batch.today_queue_candidates", return_value=[]
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
        ), patch("src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}), patch(
            "src.pipeline.daily_batch.today_queue_candidates", return_value=[]
        ):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 3)

        self.assertEqual([item["category"] for item in selected], [
            "Windows Update",
            "Beginner PC Tips",
            "Printer & Scanner",
        ])
        self.assertNotIn("Wi-Fi & Internet", [item["category"] for item in selected])

        self.assertNotIn("wifi button missing windows 11", [item["seed"] for item in selected])

    def test_batch_skips_locally_published_topic_id_and_uses_replacement(self) -> None:
        registry_candidates = [
            {
                "seed": "already published registry topic",
                "topic_id": "topic-published",
                "category": "Windows Update",
                "action": "NEW_POST",
                "topic_source": "registry",
            },
            {
                "seed": "fresh registry topic",
                "topic_id": "topic-fresh",
                "category": "Apps & Settings",
                "action": "NEW_POST",
                "topic_source": "registry",
            },
        ]
        with patch("src.pipeline.daily_batch.today_queue_candidates", return_value=[]), patch(
            "src.pipeline.daily_batch.list_registry_ready_candidates",
            return_value=registry_candidates,
        ), patch("src.pipeline.daily_batch.choose_publish_seed_candidates", return_value=[]), patch(
            "src.pipeline.daily_batch.used_keywords", return_value=set()
        ), patch("src.pipeline.daily_batch.public_post_titles", return_value=[]), patch(
            "src.pipeline.daily_batch.public_recent_categories", return_value=[]
        ), patch(
            "src.pipeline.daily_batch.locally_published_topic_ids",
            return_value={"topic-published"},
        ), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ), patch(
            "src.pipeline.daily_batch.topic_board_mode",
            return_value="ready_first",
        ):
            selected = select_seed_candidates("easy_pc_fix_guide", "windows_help", 2)

        self.assertEqual([item["topic_id"] for item in selected], ["topic-fresh"])

    def test_daily_run_replaces_quality_failure_with_next_candidate(self) -> None:
        first = {
            "seed": "first registry topic",
            "topic_id": "topic-first",
            "cluster_id": "cluster-first",
            "category_id": "cat-update",
            "category": "Windows Update",
            "article_type": "error_code_fix",
            "action": "NEW_POST",
            "revision": 1,
        }
        second = {
            "seed": "replacement registry topic",
            "topic_id": "topic-second",
            "cluster_id": "cluster-second",
            "category_id": "cat-apps",
            "category": "Apps & Settings",
            "article_type": "symptom_fix",
            "action": "NEW_POST",
            "revision": 2,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_dir = root / "first"
            second_dir = root / "second"
            for article_dir, candidate, title in [
                (first_dir, first, "First"),
                (second_dir, second, "Replacement"),
            ]:
                article_dir.mkdir()
                (article_dir / "metadata.json").write_text(
                    json.dumps({"article": {"title": title}, "candidate": candidate}),
                    encoding="utf-8",
                )
                (article_dir / "quality_report.json").write_text(
                    json.dumps({"score": 96, "metrics": {}}),
                    encoding="utf-8",
                )
            publish_result = second_dir / "blogger_publish_result.json"
            publish_result.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "skipped": False,
                        "blogger": {
                            "id": "post-second",
                            "url": "https://example.com/replacement.html",
                            "status": "LIVE",
                        },
                    }
                ),
                encoding="utf-8",
            )

            def generate(seed, site, topic_context=None):
                return first_dir if seed == first["seed"] else second_dir

            with patch("src.pipeline.daily_batch.count_public_posts_today", return_value=0), patch(
                "src.pipeline.daily_batch.select_seed_candidates", return_value=[first, second]
            ), patch(
                "src.pipeline.daily_batch.claim_topic_candidate",
                side_effect=lambda site, candidate, run_id: (True, candidate, "claimed"),
            ), patch(
                "src.pipeline.daily_batch.mark_topic_generated"
            ), patch("src.pipeline.daily_batch.run_stage1", side_effect=generate), patch(
                "src.pipeline.daily_batch.run_publish_with_duplicate_guard",
                side_effect=[
                    ValueError("Hades quality gate failed with score 80/90: thin content"),
                    publish_result,
                ],
            ), patch("src.pipeline.daily_batch.mark_topic_for_review") as mark_review, patch(
                "src.pipeline.daily_batch.run_post_publish_checks", return_value={}
            ), patch(
                "src.pipeline.daily_batch.save_batch_report"
            ), patch("src.pipeline.daily_batch.save_recovery_report"), patch(
                "src.pipeline.daily_batch.save_daily_success_report"
            ):
                result = daily_batch.run(
                    site="easy_pc_fix_guide",
                    max_posts=1,
                    notify=False,
                )

        self.assertEqual(result["status"], "published")
        self.assertEqual(result["published"][0]["topic_id"], "topic-second")
        self.assertEqual(result["published"][0]["blogger_post_id"], "post-second")
        mark_review.assert_called_once()

    def test_daily_run_replaces_claim_conflict_with_next_candidate(self) -> None:
        first = {
            "seed": "stale scheduled topic",
            "topic_id": "topic-stale",
            "category": "Windows Update",
            "article_type": "error_code_fix",
            "action": "NEW_POST",
            "revision": 3,
        }
        second = {
            "seed": "claimable replacement topic",
            "topic_id": "topic-fresh",
            "category": "Apps & Settings",
            "article_type": "symptom_fix",
            "action": "NEW_POST",
            "revision": 7,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {"title": "Claimable replacement"},
                        "candidate": second,
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "quality_report.json").write_text(
                json.dumps({"score": 96, "metrics": {}}),
                encoding="utf-8",
            )
            publish_result = article_dir / "blogger_publish_result.json"
            publish_result.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "skipped": False,
                        "blogger": {
                            "id": "post-fresh",
                            "url": "https://example.com/fresh.html",
                            "status": "LIVE",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "src.pipeline.daily_batch.count_public_posts_today",
                return_value=0,
            ), patch(
                "src.pipeline.daily_batch.select_seed_candidates",
                return_value=[first, second],
            ), patch(
                "src.pipeline.daily_batch.claim_topic_candidate",
                side_effect=[
                    (False, first, "topic_claim_conflict_or_stale_revision"),
                    (True, second, "claimed"),
                ],
            ), patch(
                "src.pipeline.daily_batch.mark_topic_generated",
                return_value=second,
            ), patch(
                "src.pipeline.daily_batch.run_stage1",
                return_value=article_dir,
            ), patch(
                "src.pipeline.daily_batch.run_publish_with_duplicate_guard",
                return_value=publish_result,
            ), patch(
                "src.pipeline.daily_batch.verify_topic_publications",
                return_value=[],
            ), patch(
                "src.pipeline.daily_batch.run_post_publish_checks",
                return_value={},
            ), patch(
                "src.pipeline.daily_batch.save_batch_report"
            ), patch(
                "src.pipeline.daily_batch.save_recovery_report"
            ), patch(
                "src.pipeline.daily_batch.save_daily_success_report"
            ):
                result = daily_batch.run(
                    site="easy_pc_fix_guide",
                    max_posts=1,
                    notify=False,
                )

        self.assertEqual(result["status"], "published")
        self.assertEqual(result["published"][0]["topic_id"], "topic-fresh")
        self.assertEqual(result["skipped"][0]["topic_id"], "topic-stale")
        self.assertEqual(result["skipped"][0]["reason"], "topic_claim_failed")

    def test_claim_and_generated_transitions_refresh_revision_in_metadata(self) -> None:
        run_id = "batch-run"
        ready = {
            "seed": "windows settings app will not open",
            "topic_id": "topic-settings",
            "cluster_id": "cluster-settings",
            "category_id": "cat-apps",
            "category": "Apps & Settings",
            "article_type": "symptom_fix",
            "action": "NEW_POST",
            "revision": 4,
        }

        class FakeStore:
            def claim_topic(self, site, topic_id, selected_run_id, expected_revision=None):
                self.assert_claim = (topic_id, selected_run_id, expected_revision)
                return SimpleNamespace(
                    topic_id=topic_id,
                    cluster_id="cluster-settings",
                    canonical_title=ready["seed"],
                    category_id="cat-apps",
                    action="NEW_POST",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=selected_run_id,
                    publications=[],
                )

            def get_category(self, site, category_id):
                return {"blogger_label": "Apps & Settings"}

            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    revision=5,
                    claim_run_id=run_id,
                )

            def mark_topic_status(
                self,
                site,
                topic_id,
                status,
                reason="",
                *,
                expected_revision=None,
                run_id="",
            ):
                self.assert_generated = (expected_revision, run_id)
                return SimpleNamespace(
                    topic_id=topic_id,
                    cluster_id="cluster-settings",
                    canonical_title=ready["seed"],
                    category_id="cat-apps",
                    action="NEW_POST",
                    status="GENERATED",
                    revision=6,
                    claim_run_id=run_id,
                    publications=[],
                )

        store = FakeStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(
                json.dumps({"candidate": ready, "article": {"title": "Draft"}}),
                encoding="utf-8",
            )
            with patch.object(daily_batch, "load_topic_store", return_value=store):
                claimed, candidate, _ = daily_batch.claim_topic_candidate(
                    "easy_pc_fix_guide",
                    ready,
                    run_id,
                )
                generated = daily_batch.mark_topic_generated(
                    "easy_pc_fix_guide",
                    candidate,
                    run_id,
                    article_dir=article_dir,
                )
            metadata = json.loads(
                (article_dir / "metadata.json").read_text(encoding="utf-8")
            )

        self.assertTrue(claimed)
        self.assertEqual(candidate["revision"], 5)
        self.assertEqual(generated["revision"], 6)
        self.assertEqual(metadata["candidate"]["revision"], 6)
        self.assertEqual(metadata["candidate"]["topic_revision"], 6)
        self.assertEqual(metadata["candidate"]["claim_run_id"], run_id)
        self.assertEqual(store.assert_claim, ("topic-settings", run_id, 4))
        self.assertEqual(store.assert_generated, (5, run_id))

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
        ), patch(
            "src.pipeline.daily_batch.today_queue_candidates", return_value=[]
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
        self.assertIn("복구: 성공 0개 / 이미지 필요 0개 / 실패 0개", message)
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
