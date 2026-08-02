from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import shutil

from src.config import ROOT_DIR
from src.models import Article, TopicCandidate


class ArticleStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or ROOT_DIR / "data" / "generated"

    def save(self, article: Article, candidate: TopicCandidate) -> Path:
        day = datetime.utcnow().strftime("%Y-%m-%d")
        article_dir = self.base_dir / day / article.slug
        assets_dir = article_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        image_source = Path(article.image.path)
        if image_source.exists():
            shutil.copy2(image_source, assets_dir / image_source.name)
        for inline_image in article.inline_images:
            inline_source = Path(inline_image.path)
            if inline_source.exists():
                shutil.copy2(inline_source, assets_dir / inline_source.name)

        (article_dir / "article.md").write_text(article.markdown, encoding="utf-8")
        (article_dir / "article.html").write_text(article.html, encoding="utf-8")
        candidate_metadata = asdict(candidate)
        candidate_metadata["topic_action"] = candidate.topic_action
        candidate_metadata["topic_revision"] = candidate.topic_revision
        (article_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "article": {
                        **asdict(article),
                        "created_at": article.created_at.isoformat(),
                    },
                    "candidate": candidate_metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return article_dir
