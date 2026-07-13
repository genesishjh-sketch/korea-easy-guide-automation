from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import traceback

from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.config import load_settings
from src.images.ai_plan import build_article_image_plan
from src.images.ai_library import install_korea_ai_assets
from src.images.ai_library import install_windows_ai_assets
from src.models import TopicCandidate
from src.pipeline.stage1_generate import run as generate_article
from src.pipeline.stage2_apply_high_quality_posts import run as apply_high_quality_posts
from src.pipeline.stage2_publish import load_article
from src.pipeline.stage2_rebuild_article_html import rebuild_article_html
from src.pipeline.stage5_apply_adsense_rules import apply_to_article_dir
from src.publishing.blogger import BloggerPublisher
from src.reporting.adsense_readiness import build_readiness_report
from src.reporting.adsense_readiness import save_readiness_report


REPURPOSED_POSTS = {
    "korea_easy_guide": {
        "11543349930859767": "korea delivery address format guide",
        "5362386935147860367": "how to call a taxi without korean phone number",
    }
}

REGENERATED_POSTS = {
    "korea_easy_guide": {
        "4739302218146947058": "olive young shopping guide for tourists",
    }
}

TITLE_OVERRIDES = {
    "korea_easy_guide": {
        "7262135509196999347": "WOWPASS Korea for Tourists: Setup, T-money, Refunds, and Safer Alternatives",
        "4113221836770530106": "Korea Tax Refund Guide for Tourists: Receipts, Kiosks, and Common Mistakes",
        "8388328638384244827": "Coupang for Foreigners in Korea: Setup, Payment, Delivery, and Returns",
        "4739302218146947058": "Olive Young Shopping in Korea for Foreigners: Easy Guide for First-Time Visitors",
        "6884633981150129574": "Where to Stay in Seoul First Time: Area Guide for Foreign Visitors",
        "5360897025413624578": "Korean Convenience Store Food Guide for Foreign Visitors",
        "5362386935147860367": "How to Call a Taxi in Korea Without a Korean Phone Number",
        "4523612224310826177": "How to Use Baemin Food Delivery in Korea as a Foreigner",
        "4973057393106068154": "Korea eSIM for Tourists: Which Plan to Buy, Activate, and Troubleshoot",
        "11543349930859767": "Korea Delivery Address Format Guide for Foreigners",
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
    topic = TopicCandidate(
        keyword=keyword,
        category=str(candidate.get("category") or article.get("category") or ""),
        intent=str(candidate.get("intent") or ""),
        score=float(candidate.get("score") or 0),
        signals=[],
    )
    image_plan = build_article_image_plan(topic, title)
    (article_dir / "image_plan.json").write_text(
        json.dumps(image_plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if settings.content_domain == "windows_help":
        scene = install_windows_ai_assets(article_dir, title, keyword)
    else:
        scene = install_korea_ai_assets(article_dir, title, keyword)

    metadata["article"]["image"] = asdict(image_plan.hero_asset(article_dir))
    metadata["article"]["inline_images"] = [asdict(image) for image in image_plan.inline_assets(article_dir)]
    (article_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
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


def run(sites: list[str] | None = None, dry_run: bool = False, mode: str = "fix") -> Path | dict:
    selected_sites = sites or ["korea_easy_guide", "easy_pc_fix_guide"]
    if mode == "audit" or dry_run:
        return audit_existing_posts(selected_sites)

    by_id, by_title = build_article_index()
    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "dry_run": dry_run,
        "mode": mode,
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
                title_override = TITLE_OVERRIDES.get(site, {}).get(post_id)
                if title_override:
                    apply_title_override(article_dir, title_override)
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


def audit_existing_posts(sites: list[str]) -> dict:
    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "mode": "audit",
        "sites": {},
        "summary": {
            "total_posts": 0,
            "no_change": 0,
            "title_improvement": 0,
            "internal_links": 0,
            "image_replace": 0,
            "body_expand": 0,
            "duplicate_risk": 0,
        },
    }
    for site in sites:
        readiness = build_readiness_report(site)
        save_readiness_report(readiness)
        duplicate_titles = duplicate_title_map(readiness.get("post_audits") or [])
        post_audits = []
        for item in readiness.get("post_audits") or []:
            classification = item.get("classification", "no_change")
            if normalize_title_for_audit(item.get("title", "")) in duplicate_titles:
                classification = "duplicate_risk"
            post_audits.append({**item, "classification": classification})
            report["summary"]["total_posts"] += 1
            if classification in report["summary"]:
                report["summary"][classification] += 1
        report["sites"][site] = {
            "readiness_status": readiness.get("status"),
            "readiness_label": readiness.get("status_label"),
            "public_post_count": readiness.get("public_post_count"),
            "posts_needing_fix_count": sum(1 for item in post_audits if item.get("classification") != "no_change"),
            "post_audits": post_audits,
            "action_items": readiness.get("action_items", []),
        }
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "existing-post-audit-report.json"
    md_path = output_dir / "existing-post-audit-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_existing_post_audit_message(report) + "\n", encoding="utf-8")
    return report


def normalize_title_for_audit(title: str) -> str:
    return " ".join(title.casefold().strip().split())


def duplicate_title_map(post_audits: list[dict]) -> set[str]:
    counts: dict[str, int] = {}
    for item in post_audits:
        key = normalize_title_for_audit(item.get("title", ""))
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def build_existing_post_audit_message(report: dict) -> str:
    summary = report.get("summary") or {}
    lines = [
        "[기존 글 품질 점검]",
        "",
        f"- 전체 글: {summary.get('total_posts', 0)}개",
        f"- 수정 없음: {summary.get('no_change', 0)}개",
        f"- 제목 개선: {summary.get('title_improvement', 0)}개",
        f"- 내부 링크 보강: {summary.get('internal_links', 0)}개",
        f"- 이미지 교체: {summary.get('image_replace', 0)}개",
        f"- 본문 보강: {summary.get('body_expand', 0)}개",
        f"- 중복 위험: {summary.get('duplicate_risk', 0)}개",
    ]
    for site, site_report in (report.get("sites") or {}).items():
        lines.extend(["", f"[{site}]", f"- 애드센스 상태: {site_report.get('readiness_label')}"])
        flagged = [item for item in site_report.get("post_audits", []) if item.get("classification") != "no_change"][:8]
        if not flagged:
            lines.append("- 우선 보강 글 없음")
            continue
        for item in flagged:
            lines.append(f"- {item.get('classification')}: {item.get('title')}")
    return "\n".join(lines)


def apply_title_override(article_dir: Path, title: str) -> None:
    metadata_path = article_dir / "metadata.json"
    html_path = article_dir / "article.html"
    metadata = load_json(metadata_path)
    metadata["article"]["title"] = title
    metadata["article"]["meta_description"] = build_override_meta_description(title)

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    h1 = soup.find("h1")
    if h1:
        h1.string = title
    html = str(soup)
    html_path.write_text(html, encoding="utf-8")
    metadata["article"]["html"] = html
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def build_override_meta_description(title: str) -> str:
    return (
        f"{title} with practical steps, common mistakes, payment or app checks, official-source reminders, "
        "and backup options for foreign visitors in Korea."
    )[:155]


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh existing live Blogger posts from upgraded local article templates.")
    parser.add_argument("--site", action="append", choices=["korea_easy_guide", "easy_pc_fix_guide"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=["audit", "fix"], default="audit")
    args = parser.parse_args()
    result = run(args.site, args.dry_run, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result)


if __name__ == "__main__":
    main()
