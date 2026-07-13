from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline import stage6_repurpose_content
from src.reporting.adsense_readiness import FeedPost


class RepurposeContentTests(unittest.TestCase):
    def test_repurpose_writes_naver_threads_card_and_faq_files(self) -> None:
        html = """
        <h2>Quick Summary</h2>
        <p>This beginner guide explains the safest first checks before changing any setting.</p>
        <h2>Step-by-Step Fixes</h2>
        <p>Start with simple checks, confirm the official source, and keep notes about what changed.</p>
        <h2>FAQ</h2>
        <h3>Should beginners try this first?</h3>
        <p>Yes, start with the low-risk checks.</p>
        """
        post = FeedPost(
            title="Wi-Fi Button Missing on Windows 11",
            url="https://easypcfixguide.blogspot.com/2026/07/wifi-button-missing.html",
            published="2026-07-07T00:00:00Z",
            content_html=html,
        )
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage6_repurpose_content, "ROOT_DIR", Path(tmpdir)), patch(
            "src.pipeline.stage6_repurpose_content.fetch_posts", return_value=[post]
        ):
            manifest = stage6_repurpose_content.run("easy_pc_fix_guide", latest=True)
            output_dir = Path(manifest["output_dir"])
            self.assertTrue((output_dir / "naver_draft.md").exists())
            self.assertTrue((output_dir / "threads_x_posts.md").exists())
            self.assertTrue((output_dir / "card_news_outline.json").exists())
            self.assertTrue((output_dir / "summary_faq.md").exists())
            self.assertIn("한국어로 다시 정리한 초안", (output_dir / "naver_draft.md").read_text(encoding="utf-8"))
            self.assertIn("1.", (output_dir / "threads_x_posts.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
