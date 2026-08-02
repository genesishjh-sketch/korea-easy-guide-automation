from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.content.topic_scoring import build_candidate
from src.images.ai_library import install_korea_ai_assets
from src.images.ai_library import install_hosted_topic_assets
from src.images.ai_library import install_windows_ai_assets
from src.images.ai_library import windows_scene
from src.images.ai_plan import build_article_image_plan
from src.models import TopicSignal
from src.pipeline import stage1_generate


class ImagePlanTests(unittest.TestCase):
    def test_research_report_schema_rejects_numeric_strings(self) -> None:
        report = {
            "schema_version": stage1_generate.RESEARCH_REPORT_SCHEMA_VERSION,
            "signal_evidence": [],
            **{field: 0 for field in stage1_generate.NUMERIC_RESEARCH_FIELDS},
            **{field: {} for field in stage1_generate.NUMERIC_RESEARCH_MAP_FIELDS},
        }
        report["observed_evidence_count"] = "1"

        with self.assertRaisesRegex(ValueError, "observed_evidence_count"):
            stage1_generate.validate_research_report(report)

    def test_research_report_rejects_aggregate_not_derived_from_rows(self) -> None:
        report = {
            "schema_version": stage1_generate.RESEARCH_REPORT_SCHEMA_VERSION,
            "signal_evidence": [],
            **{field: 0 for field in stage1_generate.NUMERIC_RESEARCH_FIELDS},
            **{field: {} for field in stage1_generate.NUMERIC_RESEARCH_MAP_FIELDS},
        }
        report["demand_eligible_signal_count"] = 3

        with self.assertRaisesRegex(ValueError, "demand_eligible_signal_count"):
            stage1_generate.validate_research_report(report)

    def test_research_report_rejects_count_map_not_derived_from_rows(self) -> None:
        report = {
            "schema_version": stage1_generate.RESEARCH_REPORT_SCHEMA_VERSION,
            "signal_evidence": [],
            **{field: 0 for field in stage1_generate.NUMERIC_RESEARCH_FIELDS},
            **{field: {} for field in stage1_generate.NUMERIC_RESEARCH_MAP_FIELDS},
        }
        report["signal_source_counts"] = {"reddit": 7}

        with self.assertRaisesRegex(ValueError, "signal_source_counts"):
            stage1_generate.validate_research_report(report)

    def test_observed_question_requires_verified_provenance(self) -> None:
        unverified = TopicSignal(
            "reddit",
            "wifi issue",
            "Wi-Fi issue",
            url="https://www.reddit.com/r/test/comments/abc/example/",
            metadata={
                "collection_method": "public_json",
                "evidence_type": "OBSERVED_QUESTION",
                "reddit_item_id": "abc",
                "verified_by_codex": False,
            },
        )
        verified = TopicSignal(
            "reddit",
            "wifi issue",
            "Wi-Fi issue",
            url="https://www.reddit.com/r/test/comments/abc/example/",
            metadata={
                "collection_method": "research_bundle",
                "evidence_type": "OBSERVED_QUESTION",
                "reddit_item_id": "abc",
                "canonical_public_page_url": "https://www.reddit.com/r/test/comments/abc/example/",
                "verified_by_codex": True,
            },
        )

        with self.assertRaisesRegex(ValueError, "verified_by_codex"):
            stage1_generate.signal_evidence_type(unverified)
        self.assertEqual(
            stage1_generate.signal_evidence_type(verified),
            "OBSERVED_QUESTION",
        )
        self.assertTrue(stage1_generate.is_eligible_evidence(verified))

    def test_first_party_query_is_an_eligible_future_contract(self) -> None:
        signal = TopicSignal(
            "search_console",
            "wifi button missing",
            "wifi button missing",
            metadata={"evidence_type": "FIRST_PARTY_QUERY"},
        )

        self.assertEqual(
            stage1_generate.signal_evidence_type(signal),
            "FIRST_PARTY_QUERY",
        )
        self.assertEqual(stage1_generate.evidence_weight("FIRST_PARTY_QUERY"), 1.0)

    def test_topic_context_aliases_are_synchronized(self) -> None:
        candidate = build_candidate("wifi issue", [], "windows_help")

        stage1_generate.apply_topic_context(
            candidate,
            {
                "topic_id": "topic_123",
                "topic_action": "NEW_POST",
                "topic_revision": 7,
                "claim_run_id": "run_abc",
            },
        )

        self.assertEqual(candidate.topic_id, "topic_123")
        self.assertEqual(candidate.action, "NEW_POST")
        self.assertEqual(candidate.topic_action, "NEW_POST")
        self.assertEqual(candidate.revision, 7)
        self.assertEqual(candidate.topic_revision, 7)
        self.assertEqual(candidate.claim_run_id, "run_abc")

    def test_default_uses_codex_generated_jpg_filenames(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        with patch.dict("os.environ", {}, clear=True):
            plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        self.assertEqual([image.filename for image in plan.images], ["ai-hero.jpg", "ai-inline-1.jpg"])
        self.assertTrue(plan.strict)

    def test_manual_jpg_mode_uses_jpg_filenames(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        with patch.dict("os.environ", {"IMAGE_ASSET_MODE": "manual_jpg"}, clear=True):
            plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        self.assertEqual([image.filename for image in plan.images], ["ai-hero.jpg", "ai-inline-1.jpg"])
        self.assertTrue(plan.strict)

    def test_windows_prompts_block_fake_ui_and_readable_error_text(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        with patch.dict("os.environ", {"IMAGE_ASSET_MODE": "manual_jpg"}, clear=True):
            plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        combined_prompts = " ".join(image.prompt for image in plan.images).lower()
        self.assertIn("fake windows ui", combined_prompts)
        self.assertIn("readable error codes", combined_prompts)
        self.assertIn("readable letters or numbers", combined_prompts)
        self.assertIn("command prompts", combined_prompts)
        self.assertIn("registry editors", combined_prompts)

    def test_windows_prompts_are_topic_specific_and_deep(self) -> None:
        candidate = build_candidate("wifi button missing windows 11", [], "windows_help")

        with patch.dict("os.environ", {"IMAGE_ASSET_MODE": "manual_jpg"}, clear=True):
            plan = build_article_image_plan(candidate, "Wi-Fi Button Missing on Windows 11")

        combined_prompts = " ".join(image.prompt for image in plan.images).lower()
        self.assertIn("visual brief", combined_prompts)
        self.assertIn("fresh prompt rule", combined_prompts)
        self.assertIn("codex image generation brief", combined_prompts)
        self.assertIn("fresh visual metaphor", combined_prompts)
        self.assertIn("recent-image avoidance", combined_prompts)
        self.assertIn("role purpose", combined_prompts)
        self.assertIn("key objects or scene cues", combined_prompts)
        self.assertIn("composition:", combined_prompts)
        self.assertIn("distorted hands", combined_prompts)
        self.assertIn("extra fingers", combined_prompts)
        self.assertIn("avoid laptop centered on a bright desk", combined_prompts)

    def test_image_plan_declares_codex_app_prompt_policy(self) -> None:
        candidate = build_candidate("scanner not detected windows 11", [], "windows_help")

        plan = build_article_image_plan(candidate, "Scanner Not Detected Windows 11")

        self.assertEqual(plan.prompt_policy["generation_owner"], "codex_app_automation")
        self.assertEqual(plan.prompt_policy["tool"], "built_in_image_gen")
        self.assertIn("Do not call OpenAI Images API", plan.prompt_policy["api_cost_policy"])
        self.assertIn("fresh one-off image prompt", plan.prompt_policy["prompt_method"])
        self.assertIn("Hero and inline images", plan.prompt_policy["diversity_rule"])

    def test_hero_and_inline_prompts_use_different_visual_metaphors(self) -> None:
        candidate = build_candidate("scanner not detected windows 11", [], "windows_help")

        plan = build_article_image_plan(candidate, "Scanner Not Detected Windows 11")

        hero_metaphor = plan.images[0].prompt.split("Fresh visual metaphor: ", 1)[1].split(". Subject", 1)[0]
        inline_metaphor = plan.images[1].prompt.split("Fresh visual metaphor: ", 1)[1].split(". Subject", 1)[0]
        self.assertNotEqual(hero_metaphor, inline_metaphor)

    def test_windows_network_subtopics_use_different_image_scenes(self) -> None:
        cases = {
            "wi-fi keeps disconnecting on windows 11": "network_wifi_disconnect",
            "windows cannot connect to this network": "network_cannot_connect",
            "network adapter missing on windows 11": "network_adapter_missing",
            "dns server not responding on windows 11": "network_dns",
        }

        for keyword, expected_scene in cases.items():
            with self.subTest(keyword=keyword):
                self.assertEqual(windows_scene(keyword), expected_scene)

        self.assertEqual(len(set(cases.values())), len(cases))

    def test_windows_update_subtopics_use_different_image_scenes(self) -> None:
        cases = {
            "windows update download stuck at 0": "update_download",
            "windows update cleanup safe for beginners": "update_cleanup",
            "windows update install error 0x80248007": "update_error_code",
            "windows update pending restart stuck": "update_restart",
        }

        for keyword, expected_scene in cases.items():
            with self.subTest(keyword=keyword):
                self.assertEqual(windows_scene(keyword), expected_scene)

        self.assertEqual(len(set(cases.values())), len(cases))

    def test_hosted_topic_assets_are_installed_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hosted_dir = Path(tmpdir) / "hosted"
            article_dir = Path(tmpdir) / "article"
            hosted_dir.mkdir()
            (hosted_dir / "pc-mouse-cursor-disappears-windows-11-hero.jpg").write_bytes(b"hero")
            (hosted_dir / "pc-mouse-cursor-disappears-windows-11-inline.jpg").write_bytes(b"inline")

            with patch("src.images.ai_library.HOSTED_AI_ASSET_DIR", hosted_dir):
                installed = install_hosted_topic_assets(article_dir, "pc", "mouse cursor disappears windows 11")

            self.assertTrue(installed)
            self.assertEqual((article_dir / "assets" / "ai-hero.jpg").read_bytes(), b"hero")
            self.assertEqual((article_dir / "assets" / "ai-inline-1.jpg").read_bytes(), b"inline")

    def test_windows_update_subtopic_prompts_are_visually_distinct(self) -> None:
        download = build_article_image_plan(
            build_candidate("windows update download stuck at 0", [], "windows_help"),
            "Windows Update Download Stuck At 0",
        )
        cleanup = build_article_image_plan(
            build_candidate("windows update cleanup safe for beginners", [], "windows_help"),
            "Windows Update Cleanup Safe for Beginners",
        )
        error_code = build_article_image_plan(
            build_candidate("windows update install error 0x80248007", [], "windows_help"),
            "Windows Update Error 0x80248007",
        )

        self.assertIn("fresh prompt rule", download.images[0].prompt.lower())
        self.assertIn("fresh prompt rule", cleanup.images[0].prompt.lower())
        self.assertIn("fresh prompt rule", error_code.images[0].prompt.lower())
        self.assertIn("download that is waiting or paused", download.images[0].prompt.lower())
        self.assertIn("storage cleanup", cleanup.images[0].prompt.lower())
        self.assertIn("diagnostic puzzle", error_code.images[0].prompt.lower())
        self.assertNotEqual(download.images[0].prompt, cleanup.images[0].prompt)
        self.assertNotEqual(cleanup.images[0].prompt, error_code.images[0].prompt)

    def test_windows_image_plan_has_descriptive_alt_and_captions(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        for image in plan.images:
            with self.subTest(filename=image.filename):
                self.assertGreaterEqual(len(image.alt.split()), 5)
                self.assertGreaterEqual(len(image.caption.split()), 7)
                self.assertNotIn(image.alt.lower(), {"hero", "inline", "image", "photo", "picture"})

    def test_korea_production_uses_codex_generated_jpg_filenames(self) -> None:
        candidate = build_candidate("incheon airport to seoul", [], "korea_travel")

        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=False):
            plan = build_article_image_plan(candidate, "How to Get from Incheon Airport to Seoul")

        self.assertEqual([image.filename for image in plan.images], ["ai-hero.jpg", "ai-inline-1.jpg"])
        self.assertTrue(plan.strict)

    def test_korea_stage1_creates_two_codex_jpg_assets_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generated_dir = Path(tmpdir) / "generated"
            seed_file = Path(tmpdir) / "seeds.json"
            seed_file.write_text(json.dumps(["incheon airport to seoul"]), encoding="utf-8")
            with patch.dict("os.environ", {"APP_ENV": "production"}, clear=False), patch.object(
                stage1_generate, "load_settings"
            ) as load_settings, patch.object(
                stage1_generate.RedditCollector,
                "collect",
                return_value=[
                    TopicSignal("reddit_fallback", "incheon airport to seoul", "Should I use AREX or airport bus?"),
                    TopicSignal(
                        "reddit",
                        "incheon airport to seoul",
                        "Incheon to Seoul advice",
                        url="https://www.reddit.com/r/test/comments/oauth123/incheon_to_seoul_advice/",
                        metadata={
                            "collection_method": "oauth",
                            "source_item_id": "oauth123",
                            "canonical_public_page_url": (
                                "https://www.reddit.com/r/test/comments/oauth123/"
                                "incheon_to_seoul_advice/"
                            ),
                        },
                    ),
                ],
            ), patch.object(
                stage1_generate.GoogleSuggestCollector,
                "collect",
                return_value=[
                    TopicSignal(
                        "google_suggest",
                        "incheon airport to seoul",
                        "incheon airport to seoul by train",
                        metadata={"collection_method": "live"},
                    )
                ],
            ):
                load_settings.return_value.site_key = "korea_easy_guide"
                load_settings.return_value.site_name = "Korea Easy Guide"
                load_settings.return_value.site_url = "https://koreaeasyguide.blogspot.com"
                load_settings.return_value.default_author = "Guide Studio"
                load_settings.return_value.content_domain = "korea_travel"
                load_settings.return_value.generated_output_dir = str(generated_dir)
                load_settings.return_value.seed_file = str(seed_file)
                load_settings.return_value.reddit_user_agent = "test"
                load_settings.return_value.reddit_client_id = ""
                load_settings.return_value.reddit_client_secret = ""
                load_settings.return_value.reddit_subreddits = ["travel"]

                article_dir = stage1_generate.run(site="korea_easy_guide")

            image_plan = json.loads((article_dir / "image_plan.json").read_text(encoding="utf-8"))
            research_report = json.loads((article_dir / "research_report.json").read_text(encoding="utf-8"))
            hero_exists = (article_dir / "assets" / "ai-hero.jpg").exists()
            inline_exists = (article_dir / "assets" / "ai-inline-1.jpg").exists()

        self.assertEqual([image["url"] for image in image_plan["images"]], ["assets/ai-hero.jpg", "assets/ai-inline-1.jpg"])
        self.assertEqual(research_report["signal_source_counts"]["reddit"], 1)
        self.assertEqual(research_report["signal_source_counts"]["reddit_fallback"], 1)
        self.assertEqual(research_report["signal_source_counts"]["google_suggest"], 1)
        self.assertEqual(research_report["seed_keyword"], "incheon airport to seoul")
        self.assertEqual(research_report["content_domain"], "korea_travel")
        self.assertEqual(research_report["live_reddit_signal_count"], 1)
        self.assertEqual(research_report["reddit_oauth_signal_count"], 1)
        self.assertEqual(research_report["reddit_public_json_signal_count"], 0)
        self.assertEqual(research_report["fallback_reddit_signal_count"], 1)
        self.assertEqual(research_report["google_suggest_live_signal_count"], 1)
        self.assertEqual(research_report["google_suggest_fallback_signal_count"], 0)
        self.assertEqual(research_report["google_suggest_method_counts"]["live"], 1)
        self.assertEqual(research_report["schema_version"], 2)
        self.assertEqual(research_report["collector_role"], "seed_enricher")
        self.assertEqual(research_report["observed_evidence_count"], 1)
        self.assertEqual(research_report["fallback_evidence_count"], 1)
        self.assertEqual(research_report["search_suggestion_count"], 1)
        self.assertEqual(research_report["demand_eligible_signal_count"], 1)
        self.assertEqual(
            [row["evidence_type"] for row in research_report["signal_evidence"]],
            ["FALLBACK_TEMPLATE", "OBSERVED_QUESTION", "SEARCH_SUGGESTION"],
        )
        self.assertIn("reddit_collection_diagnostics", research_report)
        self.assertIn("google_suggest_diagnostics", research_report)
        self.assertTrue(hero_exists)
        self.assertTrue(inline_exists)

    def test_general_image_scene_is_not_installed_as_publishable_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)

            with self.assertRaises(FileNotFoundError) as korea_raised:
                install_korea_ai_assets(article_dir, "Generic Korea Help", "generic Korea help")
            with self.assertRaises(FileNotFoundError) as windows_raised:
                install_windows_ai_assets(article_dir, "Generic PC Help", "generic PC help")

        self.assertIn("general", str(korea_raised.exception))
        self.assertIn("general", str(windows_raised.exception))


if __name__ == "__main__":
    unittest.main()
