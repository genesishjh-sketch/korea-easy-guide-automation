from __future__ import annotations

import argparse
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import ROOT_DIR
from src.content.high_quality_posts import HIGH_QUALITY_POSTS


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

    inline_image = {
        "url": "assets/ai-inline-1.jpg",
        "alt": post.get("inline_alt", post["inline_caption"]),
    }

    html = env.get_template("high_quality_article.html.j2").render(
        post=post,
        image={"url": image_url, "alt": image_alt},
        inline_image=inline_image,
    )

    article["title"] = post["title"]
    article["meta_description"] = post["meta_description"]
    article["html"] = html
    article["sources"] = [{"name": name, "url": url} for name, url in post["sources"]]

    (article_dir / "article.html").write_text(html, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return article_dir / "article.html"


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
