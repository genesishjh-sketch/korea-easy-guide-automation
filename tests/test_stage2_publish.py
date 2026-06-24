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


if __name__ == "__main__":
    unittest.main()
