from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
from pathlib import Path

from bs4 import BeautifulSoup

from src.config import ROOT_DIR, load_settings
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage2")


def latest_article_dir() -> Path:
    generated_root = ROOT_DIR / "data" / "generated"
    candidates = [
        path
        for path in generated_root.glob("*/*")
        if path.is_dir() and (path / "article.html").exists() and (path / "metadata.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No generated article directories found. Run stage1 first.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_article(article_dir: Path) -> tuple[str, str, list[str]]:
    metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))
    article = metadata["article"]
    title = article["title"]
    labels = article.get("tags", [])
    validate_required_images(article_dir)
    html = (article_dir / "article.html").read_text(encoding="utf-8")
    html = rewrite_local_image_paths(html, article_dir)
    return title, html, labels


def validate_required_images(article_dir: Path) -> None:
    image_plan_path = article_dir / "image_plan.json"
    if not image_plan_path.exists():
        return

    image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
    if not image_plan.get("strict", False):
        return

    missing = []
    for image in image_plan.get("images", []):
        if not image.get("required", True):
            continue
        url = image.get("url") or f"assets/{image.get('filename', '')}"
        if not url.startswith("assets/"):
            continue
        if not (article_dir / url).exists():
            missing.append(url)

    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"Required Codex-generated image assets are missing: {joined}. "
            "Generate the images from image_plan.json and save them before publishing."
        )


def rewrite_local_image_paths(html: str, article_dir: Path) -> str:
    """Embed local image assets directly so Blogger posts have images without hosting costs."""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("assets/"):
            asset_path = article_dir / src
            if not asset_path.exists():
                img.decompose()
                continue
            mime_type = mimetypes.guess_type(asset_path.name)[0]
            if mime_type not in {"image/svg+xml", "image/png", "image/jpeg", "image/webp"}:
                img.decompose()
                continue
            encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
            img["src"] = f"data:{mime_type};base64,{encoded}"
            img["loading"] = "lazy"
    return str(soup)


def save_publish_result(article_dir: Path, result: dict, draft: bool) -> Path:
    result_path = article_dir / "blogger_publish_result.json"
    result_path.write_text(
        json.dumps(
            {
                "draft": draft,
                "blogger": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "selfLink": result.get("selfLink"),
                    "status": result.get("status"),
                    "published": result.get("published"),
                    "updated": result.get("updated"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result_path


def run(article_dir: Path | None, mode: str | None) -> Path:
    settings = load_settings()
    selected_dir = article_dir or latest_article_dir()
    publish_mode = mode or settings.blogger_publish_mode
    draft = publish_mode != "publish"

    title, html, labels = load_article(selected_dir)
    publisher = BloggerPublisher(settings)
    LOGGER.info("Publishing to Blogger blog_id=%s draft=%s title=%s", settings.blogger_blog_id, draft, title)
    result = publisher.publish(title=title, html=html, labels=labels, draft=draft)
    result_path = save_publish_result(selected_dir, result, draft)
    LOGGER.info("Saved publish result to %s", result_path)
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 2: publish a generated article to Blogger.")
    parser.add_argument("--article-dir", help="Generated article directory. Defaults to latest generated article.")
    parser.add_argument("--mode", choices=["draft", "publish"], help="Blogger publishing mode. Default: BLOGGER_PUBLISH_MODE")
    args = parser.parse_args()

    article_dir = Path(args.article_dir).expanduser().resolve() if args.article_dir else None
    try:
        result_path = run(article_dir, args.mode)
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
