from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.content.static_pages import required_pages
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage2_pages")


def run(site: str | None = None) -> Path:
    settings = load_settings(site)
    publisher = BloggerPublisher(settings)
    results = []
    for page in required_pages(settings.site_name, settings.content_domain):
        LOGGER.info("Upserting Blogger page: %s", page.title)
        result = publisher.upsert_page(page.title, page.html)
        results.append(
            {
                "title": page.title,
                "slug": page.slug,
                "id": result.get("id"),
                "url": result.get("url"),
                "selfLink": result.get("selfLink"),
                "status": result.get("status"),
                "updated": result.get("updated"),
            }
        )

    output_dir = Path(settings.generated_output_dir) / "static_pages"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "blogger_pages_result.json"
    output_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat(),
                "blog_id": settings.blogger_blog_id,
                "site_url": settings.site_url,
                "pages": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update required Blogger static pages.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    try:
        result_path = run(args.site)
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
