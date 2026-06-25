from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.pipeline import stage2_rebuild_article_html


class RebuildArticleHtmlTests(unittest.TestCase):
    def test_rebuild_uses_windows_generator_for_windows_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            stage2_rebuild_article_html, "load_settings"
        ) as load_settings, patch.object(
            stage2_rebuild_article_html, "WindowsArticleGenerator"
        ) as windows_generator, patch.object(
            stage2_rebuild_article_html, "EnglishArticleGenerator"
        ) as english_generator:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "candidate": {
                            "keyword": "wifi button missing windows 11",
                            "category": "Wi-Fi & Internet",
                            "intent": "Fix",
                            "score": 10,
                        },
                        "article": {
                            "title": "Old",
                            "slug": "old",
                            "category": "Wi-Fi & Internet",
                            "tags": [],
                            "meta_description": "",
                            "markdown": "",
                            "html": "",
                            "image": {
                                "path": "assets/ai-hero.svg",
                                "url": "assets/ai-hero.svg",
                                "alt": "Hero image for Windows troubleshooting",
                                "source": "codex_image_plan",
                            },
                            "inline_images": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = Mock(content_domain="windows_help")
            load_settings.return_value = settings
            generated = Mock(
                html="<article>Windows</article>",
                markdown="# Windows",
                title="New Windows Title",
                slug="new-windows-title",
                category="Wi-Fi & Internet",
                tags=["Windows"],
                meta_description="New description",
                sources=[],
            )
            windows_generator.return_value.generate.return_value = generated

            output_path = stage2_rebuild_article_html.rebuild_article_html(article_dir, site="easy_pc_fix_guide")
            html = output_path.read_text(encoding="utf-8")

        load_settings.assert_called_once_with("easy_pc_fix_guide")
        windows_generator.assert_called_once_with(settings)
        english_generator.assert_not_called()
        self.assertEqual(output_path, article_dir / "article.html")
        self.assertEqual(html, "<article>Windows</article>")


if __name__ == "__main__":
    unittest.main()
