from __future__ import annotations

import argparse
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.high_quality_posts import HIGH_QUALITY_POSTS
from src.content.internal_links import resolve_related_posts


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


def render_post(article_dir: Path, env: Environment) -> Path | None:
    post = HIGH_QUALITY_POSTS.get(article_dir.name)
    if not post:
        return None

    metadata_path = article_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    article = metadata["article"]
    image = article.get("image", {})
    image_url = image.get("url") or "assets/ai-hero.jpg"
    image_alt = image.get("alt") or post["title"]

    inline_images = build_inline_images(article_dir, article, post)
    candidate = metadata.get("candidate", {}) or {}
    settings = load_settings("korea_easy_guide")
    related_guides = resolve_related_posts(
        settings.site_url,
        str(candidate.get("keyword") or post["title"]),
        str(article.get("category") or candidate.get("category") or ""),
        current_title=post["title"],
    )

    html = env.get_template("high_quality_article.html.j2").render(
        post=post,
        image={"url": image_url, "alt": image_alt},
        inline_images=inline_images,
        related_guides=related_guides,
    )

    article["title"] = post["title"]
    article["meta_description"] = post["meta_description"]
    article["html"] = html
    article["inline_images"] = [
        {
            "path": str(article_dir / inline_image["url"]),
            "url": inline_image["url"],
            "alt": inline_image["alt"],
            "source": "codex_image_plan",
            "credit": "Generated with Codex image generation",
            "caption": inline_image["caption"],
        }
        for inline_image in inline_images
    ]
    article["sources"] = [{"name": name, "url": url} for name, url in post["sources"]]

    (article_dir / "article.html").write_text(html, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return article_dir / "article.html"


def build_inline_images(article_dir: Path, article: dict, post: dict) -> list[dict[str, str]]:
    existing = list(article.get("inline_images") or [])
    captions = [
        post.get("inline_caption", "Use this visual checkpoint before continuing with the next step."),
        "Use this visual checklist before moving to payment, timing, or backup options.",
        "Keep this reminder in mind before relying on the service during your trip.",
    ]
    images = []
    for index in range(1, 5):
        url = f"assets/ai-inline-{index}.jpg"
        if not (article_dir / url).exists():
            continue
        previous = existing[index - 1] if index - 1 < len(existing) else {}
        images.append(
            {
                "url": url,
                "alt": previous.get("alt") or post.get("inline_alt") or captions[min(index - 1, len(captions) - 1)],
                "caption": previous.get("caption") or captions[min(index - 1, len(captions) - 1)],
            }
        )
    if images:
        return images
    return [
        {
            "url": "assets/ai-inline-1.jpg",
            "alt": post.get("inline_alt", post["inline_caption"]),
            "caption": post["inline_caption"],
        }
    ]


def run(root: Path | None) -> list[Path]:
    template_dir = ROOT_DIR / "src" / "content" / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    selected_root = root or ROOT_DIR / "data" / "generated"
    outputs = []
    for path in article_dirs(selected_root):
        output = render_post(path, env)
        if output:
            outputs.append(output)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply high-quality article bodies to generated posts.")
    parser.add_argument("--root", help="Generated root or a single article directory. Defaults to data/generated.")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else None
    for output_path in run(root):
        print(output_path)


if __name__ == "__main__":
    main()
