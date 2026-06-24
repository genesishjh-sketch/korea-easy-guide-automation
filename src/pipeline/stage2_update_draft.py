from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from src.config import load_settings
from src.content.high_quality_posts import INCHEON_AIRPORT_TO_SEOUL_HTML
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage2_update_draft")


def run(article_dir: Path) -> Path:
    metadata_path = article_dir / "metadata.json"
    result_path = article_dir / "blogger_publish_result.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    publish_result = json.loads(result_path.read_text(encoding="utf-8"))

    article = metadata["article"]
    post_id = publish_result["blogger"]["id"]
    title = article["title"]
    labels = article.get("tags", [])

    (article_dir / "article.html").write_text(INCHEON_AIRPORT_TO_SEOUL_HTML, encoding="utf-8")

    settings = load_settings()
    publisher = BloggerPublisher(settings)
    LOGGER.info("Updating Blogger draft post_id=%s title=%s", post_id, title)
    result = publisher.update_post(post_id=post_id, title=title, html=INCHEON_AIRPORT_TO_SEOUL_HTML, labels=labels)

    update_result_path = article_dir / "blogger_update_result.json"
    update_result_path.write_text(
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
    return update_result_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Update an existing Blogger draft with improved content.")
    parser.add_argument("--article-dir", required=True)
    args = parser.parse_args()
    try:
        result_path = run(Path(args.article_dir).expanduser().resolve())
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
