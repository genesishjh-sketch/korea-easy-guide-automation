from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.content.topic_scoring import build_candidate
from src.images.ai_plan import build_article_image_plan
from src.models import TopicSignal
from src.pipeline import stage1_generate


class ImagePlanTests(unittest.TestCase):
    def test_default_uses_local_svg_fallback_filenames(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        with patch.dict("os.environ", {}, clear=True):
            plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        self.assertEqual([image.filename for image in plan.images], ["ai-hero.svg", "ai-inline-1.svg"])
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

    def test_windows_image_plan_has_descriptive_alt_and_captions(self) -> None:
        candidate = build_candidate("windows update error 0x80070643", [], "windows_help")

        plan = build_article_image_plan(candidate, "Windows Update Error 0x80070643")

        for image in plan.images:
            with self.subTest(filename=image.filename):
                self.assertGreaterEqual(len(image.alt.split()), 5)
                self.assertGreaterEqual(len(image.caption.split()), 7)
                self.assertNotIn(image.alt.lower(), {"hero", "inline", "image", "photo", "picture"})

    def test_korea_production_uses_local_svg_fallback_filenames(self) -> None:
        candidate = build_candidate("incheon airport to seoul", [], "korea_travel")

        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=False):
            plan = build_article_image_plan(candidate, "How to Get from Incheon Airport to Seoul")

        self.assertEqual([image.filename for image in plan.images], ["ai-hero.svg", "ai-inline-1.svg"])
        self.assertTrue(plan.strict)

    def test_korea_stage1_creates_two_local_svg_assets_in_production(self) -> None:
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
                    TopicSignal("google_suggest", "incheon airport to seoul", "incheon airport to seoul by train")
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
            hero_exists = (article_dir / "assets" / "ai-hero.svg").exists()
            inline_exists = (article_dir / "assets" / "ai-inline-1.svg").exists()

        self.assertEqual([image["url"] for image in image_plan["images"]], ["assets/ai-hero.svg", "assets/ai-inline-1.svg"])
        self.assertEqual(research_report["signal_source_counts"]["reddit"], 1)
        self.assertEqual(research_report["signal_source_counts"]["reddit_fallback"], 1)
        self.assertEqual(research_report["signal_source_counts"]["google_suggest"], 1)
        self.assertEqual(research_report["seed_keyword"], "incheon airport to seoul")
        self.assertEqual(research_report["content_domain"], "korea_travel")
        self.assertEqual(research_report["live_reddit_signal_count"], 1)
        self.assertEqual(research_report["reddit_oauth_signal_count"], 1)
        self.assertEqual(research_report["reddit_public_json_signal_count"], 0)
        self.assertEqual(research_report["fallback_reddit_signal_count"], 1)
        self.assertIn("reddit_collection_diagnostics", research_report)
        self.assertTrue(hero_exists)
        self.assertTrue(inline_exists)


if __name__ == "__main__":
    unittest.main()
