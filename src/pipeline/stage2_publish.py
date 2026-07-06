from __future__ import annotations

import argparse
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import urllib.request

from bs4 import BeautifulSoup

from src.config import ROOT_DIR, load_settings
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher
from src.quality.hades import HadesQualityGate


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage2")
RAW_IMAGE_BASE_URL = os.getenv(
    "RAW_IMAGE_BASE_URL",
    "https://raw.githubusercontent.com/genesishjh-sketch/korea-easy-guide-automation/main",
)
REUSABLE_IMAGE_PATH_PARTS = (
    "/src/images/ai_assets/korea/",
    "/src/images/ai_assets/windows/",
)
ALLOWED_UNIQUE_IMAGE_PATH_PART = "/src/images/ai_assets/hosted/"


def latest_article_dir(site: str | None = None) -> Path:
    settings = load_settings(site)
    generated_root = Path(settings.generated_output_dir)
    candidates = [
        path
        for path in generated_root.glob("*/*")
        if path.is_dir() and (path / "article.html").exists() and (path / "metadata.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No generated article directories found. Run stage1 first.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_article(article_dir: Path, site: str | None = None) -> tuple[str, str, list[str]]:
    metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))
    article = metadata["article"]
    title = article["title"]
    labels = article.get("tags", [])
    validate_required_images(article_dir)
    validate_quality(article_dir, site)
    html = (article_dir / "article.html").read_text(encoding="utf-8")
    html = rewrite_local_image_paths(html, article_dir)
    validate_fresh_public_images(html, site)
    return title, html, labels


def validate_quality(article_dir: Path, site: str | None = None) -> None:
    settings = load_settings(site)
    report = HadesQualityGate(settings.content_domain).review_article_dir(article_dir)
    report_path = article_dir / "quality_report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Hades quality gate failed with score {report.score}/{report.min_score}: {issues}")


def validate_required_images(article_dir: Path) -> None:
    image_plan_path = article_dir / "image_plan.json"
    if not image_plan_path.exists():
        raise FileNotFoundError("image_plan.json is required before Blogger publishing.")

    image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
    if not image_plan.get("strict", False):
        raise ValueError("image_plan.json must set strict=true before Blogger publishing.")

    required_images = [image for image in image_plan.get("images", []) if image.get("required", True)]
    if len(required_images) < 2:
        raise ValueError("At least two required image assets are needed before Blogger publishing.")

    invalid_urls = []
    missing = []
    invalid_extensions = []
    for image in required_images:
        url = image.get("url") or f"assets/{image.get('filename', '')}"
        if not url.startswith("assets/"):
            invalid_urls.append(url)
            continue
        if Path(url).suffix.lower() == ".svg":
            invalid_extensions.append(url)
            continue
        if not (article_dir / url).exists():
            missing.append(url)

    if invalid_urls:
        joined = ", ".join(invalid_urls)
        raise ValueError(f"Required image assets must be local assets/ files: {joined}.")

    if invalid_extensions:
        joined = ", ".join(invalid_extensions)
        raise ValueError(f"Public publishing requires fresh raster JPG/PNG/WebP images, not SVG fallback assets: {joined}.")

    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"Required Codex-generated image assets are missing: {joined}. "
            "Generate the images from image_plan.json and save them before publishing."
        )


def rewrite_local_image_paths(html: str, article_dir: Path) -> str:
    """Replace local image assets with stable raw GitHub URLs so Blogger lists stay lightweight."""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("assets/"):
            asset_path = article_dir / src
            if not asset_path.exists():
                img.decompose()
                continue
            mime_type = mimetypes.guess_type(asset_path.name)[0]
            if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                img.decompose()
                continue
            img["src"] = raw_image_url_for_asset(asset_path)
            img["loading"] = "lazy"
    return str(soup)


def raw_image_url_for_asset(asset_path: Path) -> str:
    library_path = find_matching_ai_asset(asset_path)
    if library_path is None:
        raise FileNotFoundError(
            f"Image asset is not available in src/images/ai_assets for lightweight Blogger publishing: {asset_path}. "
            "Copy the generated image into the image asset library or provide a stable external image URL."
        )
    relative = library_path.relative_to(ROOT_DIR).as_posix()
    validate_library_image_is_publishable(relative)
    return f"{RAW_IMAGE_BASE_URL.rstrip('/')}/{relative}"


def validate_library_image_is_publishable(relative_path: str) -> None:
    normalized = f"/{relative_path}"
    if ALLOWED_UNIQUE_IMAGE_PATH_PART in normalized:
        return
    if any(part in normalized for part in REUSABLE_IMAGE_PATH_PARTS):
        raise ValueError(
            "Reusable image library assets cannot be used for public publishing: "
            f"{relative_path}. Generate fresh article-specific Codex images and store them under src/images/ai_assets/hosted/."
        )


def validate_fresh_public_images(html: str, site: str | None = None) -> None:
    settings = load_settings(site)
    new_urls = set(image_urls_from_html(html))
    if not new_urls:
        raise ValueError("Public publishing requires image URLs after local image rewrite.")
    used_urls = public_image_urls(settings.site_url)
    reused = sorted(new_urls & used_urls)
    if reused:
        raise ValueError(
            "Fresh article-specific images are required; these image URLs are already used by published posts: "
            + ", ".join(reused[:5])
        )


def public_image_urls(site_url: str) -> set[str]:
    feed_url = f"{site_url.rstrip('/')}/feeds/posts/default?alt=json&max-results=100"
    try:
        with urllib.request.urlopen(feed_url, timeout=20) as response:
            payload = json.load(response)
    except Exception as exc:
        raise RuntimeError(f"Could not check published image reuse from Blogger feed: {exc}") from exc

    urls: set[str] = set()
    for entry in payload.get("feed", {}).get("entry", []):
        content = entry.get("content", {}).get("$t", "")
        urls.update(image_urls_from_html(content))
    return urls


def image_urls_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = [img.get("src", "").strip() for img in soup.find_all("img") if img.get("src")]
    if urls:
        return urls
    return [match.group(1).strip() for match in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", html, flags=re.I)]


def find_matching_ai_asset(asset_path: Path) -> Path | None:
    digest = sha256_file(asset_path)
    for candidate in (ROOT_DIR / "src" / "images" / "ai_assets").rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".svg"}:
            if sha256_file(candidate) == digest:
                return candidate
    return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def run(article_dir: Path | None, mode: str | None, site: str | None = None) -> Path:
    settings = load_settings(site)
    selected_dir = article_dir or latest_article_dir(site)
    publish_mode = mode or settings.blogger_publish_mode
    draft = publish_mode != "publish"

    title, html, labels = load_article(selected_dir, site)
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
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()

    article_dir = Path(args.article_dir).expanduser().resolve() if args.article_dir else None
    try:
        result_path = run(article_dir, args.mode, args.site)
    except BloggerCredentialsError as exc:
        raise SystemExit(f"Blogger credential setup required: {exc}") from exc
    print(result_path)


if __name__ == "__main__":
    main()
