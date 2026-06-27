from __future__ import annotations

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from src.content.topic_scoring import build_candidate
from src.images.ai_library import windows_scene
from src.images.ai_plan import build_article_image_plan
from src.models import TopicSignal
from src.pipeline import stage1_generate


class ImagePlanTests(unittest.TestCase):
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
        self.assertIn("use case: photorealistic home connectivity scene", combined_prompts)
        self.assertIn("router", combined_prompts)
        self.assertIn("wi-fi wave", combined_prompts)
        self.assertIn("composition/framing", combined_prompts)
        self.assertIn("distorted hands", combined_prompts)
        self.assertIn("extra fingers", combined_prompts)
        self.assertIn("style diversity rule", combined_prompts)

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

        self.assertIn("paused progress", download.images[0].prompt.lower())
        self.assertIn("storage drive", cleanup.images[0].prompt.lower())
        self.assertIn("puzzle pieces", error_code.images[0].prompt.lower())
        self.assertIn("network-and-waiting", download.images[0].prompt.lower())
        self.assertIn("top-down storage cleanup flat-lay", cleanup.images[0].prompt.lower())
        self.assertIn("cinematic diagnostic workbench", error_code.images[0].prompt.lower())
        self.assertIn("timeline-style network troubleshooting", download.images[1].prompt.lower())
        self.assertIn("storage decision board", cleanup.images[1].prompt.lower())
        self.assertIn("diagnostic decision tree", error_code.images[1].prompt.lower())

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

    def test_easy_pc_approval_pending_skips_unstable_reddit_public_json(self) -> None:
        settings = types.SimpleNamespace(
            content_domain="windows_help",
            reddit_client_id="",
            reddit_client_secret="",
            reddit_data_access_request_submitted_at="2026-06-25",
        )

        reason = stage1_generate.reddit_public_json_skip_reason_for_settings(settings)

        self.assertIn("approval is pending", reason)

    def test_reddit_public_json_skip_does_not_apply_to_korea_or_oauth(self) -> None:
        korea = types.SimpleNamespace(
            content_domain="korea_travel",
            reddit_client_id="",
            reddit_client_secret="",
            reddit_data_access_request_submitted_at="2026-06-25",
        )
        oauth_ready = types.SimpleNamespace(
            content_domain="windows_help",
            reddit_client_id="client",
            reddit_client_secret="secret",
            reddit_data_access_request_submitted_at="2026-06-25",
        )

        self.assertEqual(stage1_generate.reddit_public_json_skip_reason_for_settings(korea), "")
        self.assertEqual(stage1_generate.reddit_public_json_skip_reason_for_settings(oauth_ready), "")

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
                        url="https://reddit.com/r/test",
                        metadata={"collection_method": "oauth"},
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
        self.assertIn("reddit_collection_diagnostics", research_report)
        self.assertIn("google_suggest_diagnostics", research_report)
        self.assertTrue(hero_exists)
        self.assertTrue(inline_exists)


if __name__ == "__main__":
    unittest.main()
