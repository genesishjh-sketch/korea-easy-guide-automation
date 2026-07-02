from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.config import load_settings
from src.content.generator import EnglishArticleGenerator
from src.models import ImageAsset, TopicCandidate
from src.quality.hades import HadesQualityGate


class KoreaGeneratorQualityTests(unittest.TestCase):
    def test_generic_korea_topic_passes_hades_quality_gate(self) -> None:
        settings = load_settings("korea_easy_guide")
        generator = EnglishArticleGenerator(settings)
        candidate = TopicCandidate(
            keyword="olive young shopping in korea for foreigners",
            category="Shopping",
            intent="how-to",
            score=1.0,
        )
        article = generator.generate(
            candidate,
            ImageAsset(
                path="assets/ai-hero.jpg",
                url="",
                alt="Foreign visitor comparing skincare shelves inside a bright Olive Young store in Seoul",
                source="codex",
                caption="Use official store and tax refund information before planning a shopping stop.",
            ),
            [
                ImageAsset(
                    path="assets/ai-inline-1.jpg",
                    url="",
                    alt="Traveler checking Korean beauty product labels and payment options on a phone",
                    source="codex",
                    caption="Save product names, store branches, and payment backup details before checkout.",
                ),
                ImageAsset(
                    path="assets/ai-inline-2.jpg",
                    url="",
                    alt="Simple shopping route plan with subway station exit and cosmetics store location",
                    source="codex",
                    caption="Check the branch location and nearest station exit before leaving your hotel.",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            for filename in ["ai-hero.jpg", "ai-inline-1.jpg", "ai-inline-2.jpg"]:
                (assets_dir / filename).write_bytes(b"fake image")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": article.image.alt,
                                "caption": article.image.caption,
                            },
                            {
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": article.inline_images[0].alt,
                                "caption": article.inline_images[0].caption,
                            },
                            {
                                "filename": "ai-inline-2.jpg",
                                "required": True,
                                "alt": article.inline_images[1].alt,
                                "caption": article.inline_images[1].caption,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (article_dir / "research_report.json").write_text(
                json.dumps(
                    {
                        "queries": [f"olive young korea query {index}" for index in range(6)],
                        "sources": article.sources,
                        "reader_questions": [f"reader question {index}" for index in range(5)],
                    }
                ),
                encoding="utf-8",
            )
            metadata = {
                "article": {
                    "title": article.title,
                    "meta_description": article.meta_description,
                    "tags": article.tags,
                },
                "candidate": {
                    "keyword": candidate.keyword,
                    "category": candidate.category,
                },
            }

            report = HadesQualityGate(content_domain="korea_travel").review_html(article.html, article_dir, metadata)

        self.assertTrue(report.passed, [issue.code for issue in report.issues])
        self.assertGreaterEqual(report.metrics["word_count"], 1400)
        self.assertGreaterEqual(report.metrics["faq_question_count"], 5)
        self.assertGreaterEqual(report.metrics["research_source_count"], 6)


if __name__ == "__main__":
    unittest.main()
