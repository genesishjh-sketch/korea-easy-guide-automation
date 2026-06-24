from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import ROOT_DIR
from src.images.cover import create_local_svg_cover


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


def regenerate_cover(article_dir: Path) -> Path:
    metadata_path = article_dir / "metadata.json"
    article_html_path = article_dir / "article.html"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    article = metadata["article"]
    title = article["title"]
    old_url = article.get("image", {}).get("url")
    assets_dir = article_dir / "assets"
    image = create_local_svg_cover(title, assets_dir)
    image.url = f"assets/{Path(image.path).name}"

    article["image"] = {
        "path": image.path,
        "url": image.url,
        "alt": image.alt,
        "source": image.source,
        "credit": image.credit,
    }
    html = article_html_path.read_text(encoding="utf-8")
    if old_url and old_url in html:
        html = html.replace(old_url, image.url)
    article["html"] = html

    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    article_html_path.write_text(html, encoding="utf-8")
    return Path(image.path)


def run(root: Path | None) -> list[Path]:
    selected_root = root or ROOT_DIR / "data" / "generated"
    return [regenerate_cover(path) for path in article_dirs(selected_root)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate local SVG covers for generated article directories.")
    parser.add_argument("--root", help="Generated root or a single article directory. Defaults to data/generated.")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else None
    for output_path in run(root):
        print(output_path)


if __name__ == "__main__":
    main()
