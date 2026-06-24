from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.pipeline.stage2_publish import load_article
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher
from src.config import load_settings


def run(article_dir: Path) -> Path:
    metadata_path = article_dir / "metadata.json"
    publish_result_path = article_dir / "blogger_publish_result.json"
    if not metadata_path.exists() or not publish_result_path.exists():
        raise FileNotFoundError("article_dir must contain metadata.json and blogger_publish_result.json")

    publish_result = json.loads(publish_result_path.read_text(encoding="utf-8"))
    post_id = publish_result["blogger"]["id"]
    title, html, labels = load_article(article_dir)

    publisher = BloggerPublisher(load_settings())
    result = publisher.update_post(post_id=post_id, title=title, html=html, labels=labels)

    result_path = article_dir / "blogger_refresh_result.json"
    result_path.write_text(
        json.dumps(
            {
                "blogger": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "selfLink": result.get("selfLink"),
                    "status": result.get("status"),
                    "updated": result.get("updated"),
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh an existing Blogger post from local generated HTML.")
    parser.add_argument("--article-dir", required=True)
    args = parser.parse_args()
    try:
        result_path = run(Path(args.article_dir).expanduser().resolve())
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
