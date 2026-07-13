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
from src.content.focused_windows_profiles import WINDOWS_FOCUSED_PROFILES
from src.content.internal_links import is_direct_post_url
from src.publishing.blogger import BloggerPublisher
from src.quality.originality import REWRITE_BODY_SIMILARITY, shingle_similarity


KST = ZoneInfo("Asia/Seoul")
MIN_WORDS = 800
MICROSOFT_DOMAINS = ("support.microsoft.com", "learn.microsoft.com", "microsoft.com")
DIRECT_MICROSOFT_DOMAINS = ("support.microsoft.com", "learn.microsoft.com")


def run(apply: bool = False, post_ids: set[str] | None = None) -> Path:
    settings = load_settings("easy_pc_fix_guide")
    publisher = BloggerPublisher(settings)
    posts = publisher.list_live_posts(fetch_bodies=True)
    stamp = datetime.now(tz=KST).strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT_DIR / "data" / "backups" / "live_posts" / stamp
    preview_dir = ROOT_DIR / "data" / "previews" / "focused_windows" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "easy_pc_fix_guide.json"
    backup.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")

    rendered: dict[str, str] = {}
    prepared: dict[str, dict] = {}
    for post in posts:
        post_id = str(post.get("id") or "")
        original = str(post.get("content") or "")
        profile = WINDOWS_FOCUSED_PROFILES.get(post_id)
        if not profile or (post_ids and post_id not in post_ids):
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
    report["missing_profiles"] = sorted(set(WINDOWS_FOCUSED_PROFILES) - live_ids)
    output = ROOT_DIR / "reports" / "focused-windows-rewrite-report.json"
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
    source_links = extract_source_links(soup)
    source_links = [link for link in source_links if is_microsoft_url(link["url"])][:8]
    facts = extract_safety_facts(soup)
    env = Environment(
        loader=FileSystemLoader(ROOT_DIR / "src" / "content" / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("focused_windows_article.html.j2").render(
        title=title,
        profile=profile,
        facts=facts,
        images=images,
        related_links=related_links,
        source_links=source_links,
        last_checked=datetime.now(tz=KST).date().isoformat(),
    )


def extract_safety_facts(soup: BeautifulSoup) -> dict[str, str]:
    aliases = {
        "applies to": "applies_to",
        "risk level": "risk_level",
        "data loss risk": "data_loss_risk",
        "estimated time": "estimated_time",
    }
    values: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).casefold().rstrip(":")
        key = aliases.get(label)
        if key:
            values[key] = cells[1].get_text(" ", strip=True)
    return {
        "applies_to": values.get("applies_to") or "Windows 11 and supported Windows 10 systems",
        "risk_level": values.get("risk_level") or "Low",
        "data_loss_risk": values.get("data_loss_risk") or "Possible",
        "estimated_time": values.get("estimated_time") or "15-30 minutes for the basic checks",
    }


def extract_source_links(soup: BeautifulSoup) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for heading in soup.find_all("h2"):
        name = heading.get_text(" ", strip=True).casefold()
        if "source" not in name and "official link" not in name:
            continue
        cursor = heading.find_next_sibling()
        while cursor and not (isinstance(cursor, Tag) and cursor.name == "h2"):
            if isinstance(cursor, Tag):
                for anchor in cursor.find_all("a", href=True):
                    links.append({"title": anchor.get_text(" ", strip=True), "url": str(anchor.get("href") or "")})
            cursor = cursor.find_next_sibling()
    return deduplicate_links(links)


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
    return deduplicate_links(links)


def deduplicate_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for link in links:
        url = link["url"]
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(link)
    return result


def is_microsoft_url(url: str) -> bool:
    lowered = url.casefold()
    return any(domain in lowered for domain in MICROSOFT_DOMAINS)


def validate(html: str, site_url: str, word_count: int, similarity: float) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = [str(anchor.get("href") or "") for anchor in soup.find_all("a", href=True)]
    microsoft_links = [link for link in links if is_microsoft_url(link)]
    issues = []
    if word_count < MIN_WORDS:
        issues.append("thin_content")
    if similarity >= REWRITE_BODY_SIMILARITY:
        issues.append("content_similarity_high")
    if len(soup.find_all("img")) < 2:
        issues.append("image_count_low")
    if len(soup.find_all("h3")) < 5:
        issues.append("faq_count_low")
    if sum(is_direct_post_url(link, site_url) for link in links) < 3:
        issues.append("direct_internal_links_low")
    if len(microsoft_links) < 4:
        issues.append("official_sources_low")
    if sum(any(domain in link.casefold() for domain in DIRECT_MICROSOFT_DOMAINS) for link in microsoft_links) < 2:
        issues.append("direct_microsoft_sources_low")
    required_facts = ("Applies to", "Risk level", "Data loss risk", "Estimated time", "Last checked")
    page_text = soup.get_text(" ", strip=True)
    if any(fact not in page_text for fact in required_facts):
        issues.append("safety_facts_missing")
    if "Do not run commands you do not understand" not in page_text:
        issues.append("advanced_warning_missing")
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
    parser = argparse.ArgumentParser(description="Render and optionally apply focused rewrites for repetitive Windows posts.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--post-id", action="append", default=[], help="Limit the rewrite to one or more Blogger post IDs.")
    args = parser.parse_args()
    print(run(args.apply, set(args.post_id) or None))


if __name__ == "__main__":
    main()
