from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.pipeline.stage2_publish import validate_required_images
from src.quality.hades import HadesQualityGate


class Stage2ImageGateTests(unittest.TestCase):
    def test_required_images_need_image_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError) as raised:
                validate_required_images(Path(tmpdir))

        self.assertIn("image_plan.json is required", str(raised.exception))

    def test_required_images_need_strict_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps({"strict": False, "images": []}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                validate_required_images(article_dir)

        self.assertIn("strict=true", str(raised.exception))

    def test_required_images_need_two_required_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [{"url": "assets/ai-hero.jpg", "required": True}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                validate_required_images(article_dir)

        self.assertIn("At least two required image assets", str(raised.exception))

    def test_required_images_must_exist_as_local_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"url": "assets/ai-hero.jpg", "required": True},
                            {"url": "assets/ai-inline-1.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError) as raised:
                validate_required_images(article_dir)

        self.assertIn("ai-hero.jpg", str(raised.exception))
        self.assertIn("ai-inline-1.jpg", str(raised.exception))

    def test_required_images_accept_two_local_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"url": "assets/ai-hero.jpg", "required": True},
                            {"url": "assets/ai-inline-1.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            validate_required_images(article_dir)

    def test_hades_blocks_articles_without_image_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            html = """
            <article>
              <h2>Quick Answer</h2>
              <img src="assets/ai-hero.jpg" alt="Hero">
              <img src="assets/ai-inline-1.jpg" alt="Inline">
            </article>
            """

            report = HadesQualityGate().review_html(html, article_dir, {"article": {}})

        self.assertIn("missing_image_plan", {issue.code for issue in report.issues})

    def test_hades_blocks_weak_image_alt_and_caption_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Hero",
                                "caption": "Hero image.",
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Inline",
                                "caption": "Inline image.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Answer</h2>
              <img src="assets/ai-hero.jpg" alt="Hero">
              <img src="assets/ai-inline-1.jpg" alt="Inline">
            </article>
            """

            report = HadesQualityGate().review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("weak_image_alt_text", issue_codes)
        self.assertIn("weak_image_caption", issue_codes)

    def test_hades_blocks_windows_image_plans_that_allow_fake_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Screenshot of Windows settings screen for update repair",
                                "caption": "A Windows UI screenshot showing the exact repair screen.",
                                "prompt": "Create a realistic fake Windows UI screenshot with readable error text.",
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Windows troubleshooting flow with safe abstract repair symbols",
                                "caption": "Use the safe visual checklist before trying advanced repair steps.",
                                "prompt": "Create a simple computer help image.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Summary</h2>
              <img src="assets/ai-hero.jpg" alt="Screenshot of Windows settings screen for update repair">
              <img src="assets/ai-inline-1.jpg" alt="Windows troubleshooting flow with safe abstract repair symbols">
            </article>
            """

            report = HadesQualityGate("windows_help").review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("unsafe_windows_image_label", issue_codes)
        self.assertIn("unsafe_windows_image_prompt", issue_codes)

    def test_hades_accepts_windows_image_prompts_with_strict_fake_ui_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            guarded_prompt = (
                "Create a realistic 16:9 beginner Windows help visual. Do not show fake Windows UI, "
                "readable error codes, readable letters or numbers, command prompts, registry editors, logos, or text overlays."
            )
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Beginner friendly Windows update repair checklist visual",
                                "caption": "A calm abstract checklist visual for safe Windows troubleshooting steps.",
                                "prompt": guarded_prompt,
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Safe Windows troubleshooting flow with abstract repair symbols",
                                "caption": "Follow the simple checks first before using advanced repair steps.",
                                "prompt": guarded_prompt,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Summary</h2>
              <img src="assets/ai-hero.jpg" alt="Beginner friendly Windows update repair checklist visual">
              <img src="assets/ai-inline-1.jpg" alt="Safe Windows troubleshooting flow with abstract repair symbols">
            </article>
            """

            report = HadesQualityGate("windows_help").review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertNotIn("unsafe_windows_image_label", issue_codes)
        self.assertNotIn("unsafe_windows_image_prompt", issue_codes)

    def test_hades_blocks_dangerous_windows_tool_recommendations(self) -> None:
        gate = HadesQualityGate("windows_help")
        text = (
            "Applies to Windows 11. Risk level Medium. Data loss risk Possible. "
            "Estimated time 20 minutes. Last checked 2026-06-26. Advanced fixes. "
            "Back up important files before advanced fixes. Download Driver Booster and use an activation bypass."
        ).casefold()

        issues = gate._review_windows_article(None, text, links=[])

        issue_codes = {issue.code for issue in issues}
        self.assertIn("dangerous_windows_recommendation", issue_codes)
        messages = " ".join(issue.message for issue in issues)
        self.assertIn("download driver booster", messages)
        self.assertIn("use an activation bypass", messages)

    def test_hades_allows_warnings_against_random_driver_tools(self) -> None:
        gate = HadesQualityGate("windows_help")
        text = (
            "Applies to Windows 11. Risk level Low. Data loss risk No. "
            "Estimated time 10 minutes. Last checked 2026-06-26. Advanced fixes. "
            "Back up important files before advanced fixes. Avoid random driver tools and do not use driver updater apps."
        ).casefold()

        issues = gate._review_windows_article(None, text, links=[])

        self.assertNotIn("dangerous_windows_recommendation", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
