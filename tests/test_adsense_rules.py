from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.content.adsense_rules import daily_publish_limit_from_env
from src.pipeline.stage5_apply_adsense_rules import apply_to_article_dir
from src.quality.hades import HadesQualityGate


class AdsenseRulesTests(unittest.TestCase):
    def test_daily_limit_defaults_to_stabilization_cadence_and_clamps_emergency_limit(self) -> None:
        self.assertEqual(daily_publish_limit_from_env(None, quality_review_enabled=True), 1)
        self.assertEqual(daily_publish_limit_from_env(None, quality_review_enabled=False), 1)
        self.assertEqual(daily_publish_limit_from_env("5", quality_review_enabled=True), 3)

    def test_hades_blocks_affiliate_language_and_missing_adsense_structure(self) -> None:
        html = """
        <article>
          <h2>Quick Answer</h2>
          <p>This Windows guide includes an affiliate link and a buy now button.</p>
        </article>
        """

        report = HadesQualityGate("windows_help").review_html(
            html,
            Path("/tmp/not-used"),
            {
                "article": {
                    "title": "Windows Update Error 0x80070005: Causes and Fixes",
                    "meta_description": "Windows Update Error 0x80070005 guide for beginners, covering safe checks, Microsoft sources, warnings, and next steps.",
                    "tags": ["Windows help"],
                },
                "candidate": {"keyword": "windows update error 0x80070005"},
            },
        )

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("forbidden_monetization_language", issue_codes)
        self.assertIn("missing_h1", issue_codes)
        self.assertIn("missing_final_summary", issue_codes)

    def test_existing_article_patch_adds_h1_final_summary_and_meta_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "article.html").write_text(
                """
                <article>
                  <figure><img src="assets/ai-hero.jpg" alt="Korea travel route planning visual guide"></figure>
                  <p>Short intro.</p>
                </article>
                """,
                encoding="utf-8",
            )
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {
                            "title": "Korea eSIM Guide for Tourists",
                            "meta_description": "Too short.",
                            "tags": ["Korea travel"],
                        },
                        "candidate": {"keyword": "korea esim for tourists"},
                    }
                ),
                encoding="utf-8",
            )

            result = apply_to_article_dir(article_dir, write_quality=False)
            html = (article_dir / "article.html").read_text(encoding="utf-8")
            metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))

        self.assertTrue(result["changed"])
        self.assertIn("<h1>Korea eSIM Guide for Tourists</h1>", html)
        self.assertIn("Final Summary", html)
        self.assertGreaterEqual(len(metadata["article"]["meta_description"]), 120)


if __name__ == "__main__":
    unittest.main()
