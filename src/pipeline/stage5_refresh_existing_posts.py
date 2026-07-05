from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.images.ai_library import install_korea_ai_assets
from src.images.ai_library import install_windows_ai_assets
from src.pipeline.stage1_generate import run as generate_article
from src.pipeline.stage2_apply_high_quality_posts import run as apply_high_quality_posts
from src.pipeline.stage2_publish import load_article
from src.pipeline.stage2_rebuild_article_html import rebuild_article_html
from src.pipeline.stage5_apply_adsense_rules import apply_to_article_dir
from src.publishing.blogger import BloggerPublisher


REPURPOSED_POSTS = {
    "korea_easy_guide": {
        "5362386935147860367": "how to call a taxi without korean phone number",
    }
}

REGENERATED_POSTS = {
    "korea_easy_guide": {
        "4739302218146947058": "olive young shopping guide for tourists",
    }
}


def generated_article_dirs() -> list[Path]:
    return sorted(
        path.parent
        for path in (ROOT_DIR / "data" / "generated").glob("**/article.html")
        if (path.parent / "metadata.json").exists()
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def article_post_id(article_dir: Path) -> str:
    try:
        return str(load_json(article_dir / "blogger_publish_result.json").get("blogger", {}).get("id", ""))
    except Exception:
        return ""


def article_title(article_dir: Path) -> str:
    try:
        return str(load_json(article_dir / "metadata.json").get("article", {}).get("title", ""))
    except Exception:
        return ""


def article_site(article_dir: Path) -> str:
    if "easy_pc_fix_guide" in article_dir.parts:
        return "easy_pc_fix_guide"
    if "korea_easy_guide" in article_dir.parts:
        return "korea_easy_guide"
    title = article_title(article_dir).casefold()
    if "windows" in title or "microsoft" in title or "wi-fi" in title or "0x" in title:
        return "easy_pc_fix_guide"
    return "korea_easy_guide"


def build_article_index() -> tuple[dict[str, dict[str, Path]], dict[str, dict[str, list[Path]]]]:
    by_id: dict[str, dict[str, Path]] = defaultdict(dict)
    by_title: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for article_dir in generated_article_dirs():
        site = article_site(article_dir)
        post_id = article_post_id(article_dir)
        title = article_title(article_dir).strip().casefold()
        if post_id:
            by_id[site][post_id] = article_dir
        if title:
            by_title[site][title].append(article_dir)
    return by_id, by_title


def newest_article_dir(paths: list[Path]) -> Path:
    return max(paths, key=lambda path: path.stat().st_mtime)


def prepare_article_dir(article_dir: Path, site: str) -> dict:
    metadata = load_json(article_dir / "metadata.json")
    article = metadata.get("article", {})
    candidate = metadata.get("candidate", {})
    title = str(article.get("title") or article_title(article_dir))
    keyword = str(candidate.get("keyword") or title)
    settings = load_settings(site)

    if settings.content_domain == "windows_help":
        scene = install_windows_ai_assets(article_dir, title, keyword)
    else:
        scene = install_korea_ai_assets(article_dir, title, keyword)

    rebuild_article_html(article_dir, site)
    apply_high_quality_posts(article_dir)
    quality = apply_to_article_dir(article_dir)
    return {"scene": scene, "quality": quality}


def update_blogger_post(article_dir: Path, site: str, post_id: str) -> dict:
    title, html, labels = load_article(article_dir, site)
    publisher = BloggerPublisher(load_settings(site))
    result = publisher.update_post(post_id=post_id, title=title, html=html, labels=labels)
    refresh_path = article_dir / "blogger_refresh_result.json"
    refresh_path.write_text(
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
    return {"title": title, "url": result.get("url"), "updated": result.get("updated"), "refresh_result": str(refresh_path)}


def repurpose_article(site: str, post_id: str, seed: str) -> Path:
    article_dir = generate_article(seed, site)
    publish_result_path = article_dir / "blogger_publish_result.json"
    publish_result_path.write_text(
        json.dumps(
            {
                "draft": False,
                "repurposed_existing_post": True,
                "blogger": {
                    "id": post_id,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return article_dir


def live_posts(site: str) -> list[dict]:
    return BloggerPublisher(load_settings(site)).list_live_posts()


def run(sites: list[str] | None = None, dry_run: bool = False) -> Path:
    selected_sites = sites or ["korea_easy_guide", "easy_pc_fix_guide"]
    by_id, by_title = build_article_index()
    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "dry_run": dry_run,
        "updated": [],
        "failed": [],
        "skipped": [],
        "duplicates": [],
    }

    for site in selected_sites:
        seen_titles: dict[str, dict] = {}
        for post in live_posts(site):
            post_id = str(post.get("id", ""))
            live_title = str(post.get("title", ""))
            normalized_title = live_title.strip().casefold()
            duplicate_of = seen_titles.get(normalized_title)
            if duplicate_of:
                report["duplicates"].append({"site": site, "post_id": post_id, "title": live_title, "duplicate_of": duplicate_of})
            else:
                seen_titles[normalized_title] = {"post_id": post_id, "url": post.get("url")}

            try:
                if post_id in REPURPOSED_POSTS.get(site, {}):
                    seed = REPURPOSED_POSTS[site][post_id]
                    if dry_run:
                        report["skipped"].append({"site": site, "post_id": post_id, "title": live_title, "action": f"would_repurpose:{seed}"})
                        continue
                    article_dir = repurpose_article(site, post_id, seed)
                elif post_id in REGENERATED_POSTS.get(site, {}):
                    seed = REGENERATED_POSTS[site][post_id]
                    if dry_run:
                        report["skipped"].append({"site": site, "post_id": post_id, "title": live_title, "action": f"would_regenerate:{seed}"})
                        continue
                    article_dir = repurpose_article(site, post_id, seed)
                else:
                    article_dir = by_id.get(site, {}).get(post_id)
                    if article_dir is None:
                        candidates = by_title.get(site, {}).get(normalized_title, [])
                        article_dir = newest_article_dir(candidates) if candidates else None
                    if article_dir is None:
                        report["skipped"].append({"site": site, "post_id": post_id, "title": live_title, "reason": "no_local_article_match"})
                        continue

                if dry_run:
                    report["skipped"].append({"site": site, "post_id": post_id, "title": live_title, "article_dir": str(article_dir), "action": "would_update"})
                    continue

                prepared = prepare_article_dir(article_dir, site)
                updated = update_blogger_post(article_dir, site, post_id)
                report["updated"].append(
                    {
                        "site": site,
                        "post_id": post_id,
                        "old_title": live_title,
                        "new_title": updated["title"],
                        "url": updated["url"] or post.get("url"),
                        "article_dir": str(article_dir),
                        "scene": prepared["scene"],
                        "quality_score": prepared["quality"].get("quality_score"),
                        "updated": updated.get("updated"),
                    }
                )
            except Exception as exc:
                report["failed"].append(
                    {
                        "site": site,
                        "post_id": post_id,
                        "title": live_title,
                        "error": str(exc),
                        "traceback": "".join(traceback.format_exception_only(type(exc), exc)).strip(),
                    }
                )

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "existing-post-refresh-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh existing live Blogger posts from upgraded local article templates.")
    parser.add_argument("--site", action="append", choices=["korea_easy_guide", "easy_pc_fix_guide"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(run(args.site, args.dry_run))


if __name__ == "__main__":
    main()
