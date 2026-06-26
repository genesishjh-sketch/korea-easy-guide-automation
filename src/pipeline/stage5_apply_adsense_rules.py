from __future__ import annotations

import argparse
import json
from pathlib import Path

from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.content.adsense_rules import META_DESCRIPTION_MAX_CHARS
from src.content.adsense_rules import META_DESCRIPTION_MIN_CHARS
from src.quality.hades import HadesQualityGate
from src.sites import SITE_PROFILES


def article_dirs(root: Path) -> list[Path]:
    dirs = []
    for html_path in root.glob("**/article.html"):
        article_dir = html_path.parent
        if (article_dir / "metadata.json").exists():
            dirs.append(article_dir)
    return sorted(dirs)


def infer_site_key(article_dir: Path, metadata: dict) -> str:
    site = str(metadata.get("site") or "").strip()
    if site:
        return site
    candidate = metadata.get("candidate", {}) or {}
    article = metadata.get("article", {}) or {}
    text = f"{article.get('title', '')} {candidate.get('keyword', '')} {article_dir}".casefold()
    if "easy_pc_fix_guide" in text or "windows" in text or "microsoft" in text or "0x" in text:
        return "easy_pc_fix_guide"
    return "korea_easy_guide"


def content_domain_for_site(site_key: str) -> str:
    return SITE_PROFILES.get(site_key, SITE_PROFILES["korea_easy_guide"]).content_domain


def build_meta_description(title: str, keyword: str, content_domain: str) -> str:
    title = title.strip()
    keyword = keyword.strip() or title
    if content_domain == "windows_help":
        base = (
            f"{keyword.title()} guide for Windows users, covering safe first checks, common causes, "
            "official Microsoft sources, advanced warnings, and next steps."
        )
    else:
        base = (
            f"{keyword.title()} in Korea guide for foreign visitors, covering practical steps, common problems, "
            "official links, payment or app checks, and backup options."
        )
    if len(base) <= META_DESCRIPTION_MAX_CHARS:
        return base
    trimmed = base[: META_DESCRIPTION_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    if len(trimmed) < META_DESCRIPTION_MIN_CHARS:
        return base[:META_DESCRIPTION_MAX_CHARS]
    return f"{trimmed}."


def ensure_adsense_html(html: str, title: str, content_domain: str) -> tuple[str, bool]:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    changed = False

    if not article.find("h1"):
        h1 = soup.new_tag("h1")
        h1.string = title
        first_figure = article.find("figure")
        if first_figure:
            first_figure.insert_before(h1)
        elif article.contents:
            article.insert(0, h1)
        else:
            article.append(h1)
        changed = True

    headings = [heading.get_text(" ", strip=True).casefold() for heading in article.find_all("h2")]
    if "final summary" not in headings:
        h2 = soup.new_tag("h2")
        h2.string = "Final Summary"
        paragraph = soup.new_tag("p")
        if content_domain == "windows_help":
            paragraph.string = (
                f"{title} should be handled in a safe order. Start with simple checks, record what changes, "
                "use official Microsoft guidance for advanced steps, and stop if important files or sign-in access are affected."
            )
        else:
            paragraph.string = (
                f"{title} is easier when you check official information first, prepare a backup route or payment method, "
                "and save key details before you need them during your Korea trip."
            )
        article.append(h2)
        article.append(paragraph)
        changed = True

    return str(soup), changed


def apply_to_article_dir(article_dir: Path, write_quality: bool = True) -> dict:
    metadata_path = article_dir / "metadata.json"
    html_path = article_dir / "article.html"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    article = metadata.get("article", {})
    candidate = metadata.get("candidate", {})
    site_key = infer_site_key(article_dir, metadata)
    content_domain = content_domain_for_site(site_key)
    title = article.get("title") or candidate.get("keyword") or article_dir.name.replace("-", " ").title()
    keyword = candidate.get("keyword") or title

    changed = False
    description = str(article.get("meta_description") or "").strip()
    if not (META_DESCRIPTION_MIN_CHARS <= len(description) <= META_DESCRIPTION_MAX_CHARS):
        article["meta_description"] = build_meta_description(title, keyword, content_domain)
        changed = True

    html, html_changed = ensure_adsense_html(html_path.read_text(encoding="utf-8"), title, content_domain)
    if html_changed:
        html_path.write_text(html, encoding="utf-8")
        article["html"] = html
        changed = True

    if changed:
        metadata["article"] = article
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    quality = None
    if write_quality:
        report = HadesQualityGate(content_domain).review_article_dir(article_dir)
        quality = report.to_dict()
        (article_dir / "quality_report.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "article_dir": str(article_dir),
        "site": site_key,
        "content_domain": content_domain,
        "changed": changed,
        "quality_passed": None if quality is None else quality.get("passed"),
        "quality_score": None if quality is None else quality.get("score"),
        "issue_codes": [] if quality is None else [issue.get("code") for issue in quality.get("issues", [])],
    }


def run(root: Path | None = None, write_quality: bool = True) -> Path:
    selected_root = root or ROOT_DIR / "data" / "generated"
    results = [apply_to_article_dir(path, write_quality=write_quality) for path in article_dirs(selected_root)]
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "adsense-rules-application.json"
    output_path.write_text(json.dumps({"articles": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AdSense approval-stage structure to existing generated posts.")
    parser.add_argument("--root", help="Generated root to scan. Defaults to data/generated.")
    parser.add_argument("--no-quality", action="store_true", help="Do not rewrite quality_report.json files.")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else None
    print(run(root, write_quality=not args.no_quality))


if __name__ == "__main__":
    main()
