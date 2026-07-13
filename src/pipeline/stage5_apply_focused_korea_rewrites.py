from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import ROOT_DIR, load_settings
from src.content.focused_korea_profiles import KOREA_FOCUSED_PROFILES
from src.content.internal_links import is_direct_post_url
from src.publishing.blogger import BloggerPublisher
from src.quality.hades import OFFICIAL_SOURCE_DOMAINS
from src.quality.originality import MAX_BODY_SIMILARITY, shingle_similarity


KST = ZoneInfo("Asia/Seoul")
MIN_WORDS = 800


def run(apply: bool = False) -> Path:
    settings = load_settings("korea_easy_guide")
    publisher = BloggerPublisher(settings)
    posts = publisher.list_live_posts(fetch_bodies=True)
    stamp = datetime.now(tz=KST).strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT_DIR / "data" / "backups" / "live_posts" / stamp
    preview_dir = ROOT_DIR / "data" / "previews" / "focused_korea" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "korea_easy_guide.json"
    backup.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")

    rendered: dict[str, str] = {}
    prepared: dict[str, dict] = {}
    for post in posts:
        post_id = str(post.get("id") or "")
        original = str(post.get("content") or "")
        profile = KOREA_FOCUSED_PROFILES.get(post_id)
        if not profile:
            rendered[post_id] = original
            continue
        html = render_post(str(post.get("title") or ""), original, profile, settings.site_url)
        rendered[post_id] = html
        preview = preview_dir / f"{post_id}.html"
        preview.write_text(html, encoding="utf-8")
        prepared[post_id] = {"post": post, "preview": preview}

    similarities = body_similarities(rendered)
    report = {
        "created_at_kst": datetime.now(tz=KST).isoformat(),
        "apply": apply,
        "backup": str(backup),
        "updated": [],
        "held": [],
        "missing_profiles": [],
    }
    for post_id, item in prepared.items():
        post = item["post"]
        html = rendered[post_id]
        word_count = english_word_count(html)
        similarity, similar_id = similarities[post_id]
        issues = validate(html, settings.site_url, word_count, similarity)
        record = {
            "id": post_id,
            "title": post.get("title"),
            "url": post.get("url"),
            "preview": str(item["preview"]),
            "word_count": word_count,
            "max_similarity": round(similarity, 4),
            "most_similar_post_id": similar_id,
            "issues": issues,
        }
        if issues:
            report["held"].append(record)
            continue
        if apply:
            publisher.update_post(
                post_id,
                str(post.get("title") or ""),
                html,
                list(post.get("labels") or []),
            )
        report["updated"].append(record)

    live_ids = {str(post.get("id") or "") for post in posts}
    report["missing_profiles"] = sorted(set(KOREA_FOCUSED_PROFILES) - live_ids)
    output = ROOT_DIR / "reports" / "focused-korea-rewrite-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def render_post(title: str, original_html: str, profile: dict, site_url: str) -> str:
    soup = BeautifulSoup(original_html or "", "html.parser")
    images = [
        {"src": str(image.get("src") or ""), "alt": str(image.get("alt") or title)}
        for image in soup.find_all("img")[:2]
    ]
    if len(images) < 2:
        return original_html
    related_links = extract_section_links(soup, {"related guides"})
    related_links = [link for link in related_links if is_direct_post_url(link["url"], site_url)][:3]
    source_links = extract_section_links(soup, {"official links to check", "sources"})
    source_links = [
        link for link in source_links if any(domain in link["url"] for domain in OFFICIAL_SOURCE_DOMAINS)
    ][:8]
    env = Environment(
        loader=FileSystemLoader(ROOT_DIR / "src" / "content" / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("focused_korea_article.html.j2").render(
        title=title,
        profile=profile,
        images=images,
        related_links=related_links,
        source_links=source_links,
        last_checked=datetime.now(tz=KST).date().isoformat(),
    )


def extract_section_links(soup: BeautifulSoup, names: set[str]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for heading in soup.find_all("h2"):
        if heading.get_text(" ", strip=True).casefold() not in names:
            continue
        cursor = heading.find_next_sibling()
        while cursor and not (isinstance(cursor, Tag) and cursor.name == "h2"):
            if isinstance(cursor, Tag):
                for anchor in cursor.find_all("a", href=True):
                    links.append({"title": anchor.get_text(" ", strip=True), "url": str(anchor.get("href") or "")})
            cursor = cursor.find_next_sibling()
    deduplicated = []
    seen = set()
    for link in links:
        if not link["url"] or link["url"] in seen:
            continue
        seen.add(link["url"])
        deduplicated.append(link)
    return deduplicated


def validate(html: str, site_url: str, word_count: int, similarity: float) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = [str(anchor.get("href") or "") for anchor in soup.find_all("a", href=True)]
    issues = []
    if word_count < MIN_WORDS:
        issues.append("thin_content")
    if similarity >= MAX_BODY_SIMILARITY:
        issues.append("content_similarity_high")
    if len(soup.find_all("img")) < 2:
        issues.append("image_count_low")
    if len(soup.find_all("h3")) < 5:
        issues.append("faq_count_low")
    if sum(is_direct_post_url(link, site_url) for link in links) < 3:
        issues.append("direct_internal_links_low")
    if sum(any(domain in link for domain in OFFICIAL_SOURCE_DOMAINS) for link in links) < 4:
        issues.append("official_sources_low")
    return issues


def body_similarities(rendered: dict[str, str]) -> dict[str, tuple[float, str]]:
    result = {}
    for post_id, html in rendered.items():
        matches = [
            (shingle_similarity(html, other), other_id)
            for other_id, other in rendered.items()
            if other_id != post_id
        ]
        result[post_id] = max(matches, default=(0.0, ""), key=lambda item: item[0])
    return result


def english_word_count(html: str) -> int:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(["style", "script", "noscript"]):
        node.decompose()
    return len(re.findall(r"[A-Za-z0-9']+", soup.get_text(" ", strip=True)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render and optionally apply focused rewrites for repetitive Korea posts.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(run(args.apply))


if __name__ == "__main__":
    main()
