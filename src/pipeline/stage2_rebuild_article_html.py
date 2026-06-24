from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.content.generator import EnglishArticleGenerator
from src.models import ImageAsset, TopicCandidate


def rebuild_article_html(article_dir: Path) -> Path:
    metadata_path = article_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidate_data = metadata["candidate"]
    article_data = metadata["article"]

    candidate = TopicCandidate(
        keyword=candidate_data["keyword"],
        category=candidate_data["category"],
        intent=candidate_data["intent"],
        score=candidate_data.get("score", 0),
        signals=[],
    )
    image_data = article_data["image"]
    image = ImageAsset(
        path=image_data["path"],
        url=image_data["url"],
        alt=image_data["alt"],
        source=image_data["source"],
        credit=image_data.get("credit", ""),
    )

    article = EnglishArticleGenerator(load_settings()).generate(candidate, image)
    (article_dir / "article.html").write_text(article.html, encoding="utf-8")

    metadata["article"] = {
        **metadata["article"],
        "html": article.html,
        "markdown": article.markdown,
        "title": article.title,
        "slug": article.slug,
        "category": article.category,
        "tags": article.tags,
        "meta_description": article.meta_description,
        "sources": article.sources,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return article_dir / "article.html"


def article_dirs(root: Path) -> list[Path]:
    if (root / "metadata.json").exists():
        return [root]
    direct_children = sorted(
        path
        for path in root.glob("*")
        if path.is_dir() and (path / "metadata.json").exists()
    )
    if direct_children:
        return direct_children
    return sorted(
        path
        for path in root.glob("*/*")
        if path.is_dir() and (path / "metadata.json").exists()
    )


def run(root: Path | None) -> list[Path]:
    selected_root = root or ROOT_DIR / "data" / "generated"
    return [rebuild_article_html(path) for path in article_dirs(selected_root)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild generated article.html files from metadata and the current template.")
    parser.add_argument("--root", help="Generated root or a single article directory. Defaults to data/generated.")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else None
    for output_path in run(root):
        print(output_path)


if __name__ == "__main__":
    main()
