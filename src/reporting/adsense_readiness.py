from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.internal_links import is_direct_post_url
from src.notifications.telegram import NotificationClient
from src.quality.hades import MIN_OFFICIAL_LINKS
from src.quality.hades import MIN_WORD_COUNT
from src.quality.hades import OFFICIAL_SOURCE_DOMAINS
from src.quality.originality import MAX_BODY_SIMILARITY
from src.quality.originality import REWRITE_BODY_SIMILARITY
from src.quality.originality import generic_title_ending
from src.quality.originality import shingle_similarity


REQUIRED_PAGES = ["About", "Contact", "Privacy Policy", "Disclaimer", "Terms"]
MIN_PUBLIC_POSTS_FOR_APPROVAL = 10
MIN_INTERNAL_LINKS = 2
MIN_IMAGES = 2
REPEATED_TITLE_PATTERN_LIMIT = 3


@dataclass(frozen=True)
class FeedPost:
    title: str
    url: str
    published: str
    content_html: str


def run(site: str | None = None, notify: bool = False) -> dict:
    settings = load_settings(site)
    result = build_readiness_report(settings.site_key)
    save_readiness_report(result)
    if notify and result["status"] in {"not_ready", "needs_fix"}:
        NotificationClient(settings).send(build_readiness_message(result))
    return result


def build_readiness_report(site: str) -> dict:
    settings = load_settings(site)
    checked_at = datetime.now(tz=timezone.utc).isoformat()
    pages = fetch_pages(settings.site_url)
    posts = fetch_posts(settings.site_url, max_results=50)
    post_audits = audit_posts(settings.site_key, settings.site_url, posts)
    missing_pages = [page for page in REQUIRED_PAGES if page.casefold() not in pages]
    posts_needing_fix = [post for post in post_audits if post["classification"] != "no_change"]
    action_items = readiness_action_items(missing_pages, posts, posts_needing_fix)
    status = readiness_status(missing_pages, posts, posts_needing_fix)
    newest_post = max((post.published for post in posts), default="")
    return {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "checked_at": checked_at,
        "status": status,
        "status_label": readiness_status_label(status),
        "required_pages": {
            "required": REQUIRED_PAGES,
            "found": sorted(pages.values()),
            "missing": missing_pages,
            "passed": not missing_pages,
        },
        "public_post_count": len(posts),
        "minimum_public_posts": MIN_PUBLIC_POSTS_FOR_APPROVAL,
        "latest_public_post": newest_post,
        "posts_needing_fix_count": len(posts_needing_fix),
        "post_audits": post_audits,
        "action_items": action_items,
    }


def audit_posts(site: str, site_url: str, posts: list[FeedPost]) -> list[dict]:
    title_pattern_counts = Counter(generic_title_ending(post.title) or title_pattern_key(post.title) for post in posts)
    image_url_counts = Counter(
        image
        for post in posts
        for image in extract_image_urls(post.content_html)
        if image and not image.startswith("data:")
    )
    similarities: dict[str, tuple[float, str, str]] = {}
    for post in posts:
        matches = [
            (shingle_similarity(post.content_html, other.content_html), other.title, other.url)
            for other in posts
            if other.url != post.url
        ]
        similarities[post.url] = max(matches, default=(0.0, "", ""), key=lambda item: item[0])
    audits = []
    for post in posts:
        soup = BeautifulSoup(post.content_html or "", "html.parser")
        text = soup.get_text(" ", strip=True)
        words = re.findall(r"[A-Za-z0-9']+", text)
        links = [a.get("href", "") for a in soup.find_all("a")]
        image_urls = extract_image_urls(post.content_html)
        issue_codes: list[str] = []

        if len(words) < MIN_WORD_COUNT:
            issue_codes.append("thin_content")
        if count_official_links(links) < MIN_OFFICIAL_LINKS:
            issue_codes.append("official_sources_low")
        direct_internal_links = count_internal_links(links, site_url)
        if direct_internal_links < MIN_INTERNAL_LINKS:
            issue_codes.append("internal_links_low")
        if any("/search" in link and urlparse(link).netloc == urlparse(site_url).netloc for link in links):
            issue_codes.append("blocked_search_internal_links")
        if len(image_urls) < MIN_IMAGES:
            issue_codes.append("image_count_low")
        if any(url.startswith("data:") or url.endswith(".svg") for url in image_urls):
            issue_codes.append("image_replace_needed")
        if any(image_url_counts[url] > 1 for url in image_urls if url in image_url_counts):
            issue_codes.append("reused_image_url")
        title_key = generic_title_ending(post.title) or title_pattern_key(post.title)
        if title_pattern_counts[title_key] >= REPEATED_TITLE_PATTERN_LIMIT:
            issue_codes.append("repeated_title_pattern")
        similarity, similar_title, similar_url = similarities[post.url]
        if similarity >= MAX_BODY_SIMILARITY:
            issue_codes.append("content_similarity_high")
        elif similarity >= REWRITE_BODY_SIMILARITY:
            issue_codes.append("content_similarity_warning")

        classification = classify_post_issues(issue_codes)
        audits.append(
            {
                "title": post.title,
                "url": post.url,
                "published": post.published,
                "classification": classification,
                "issues": issue_codes,
                "metrics": {
                    "word_count": len(words),
                    "official_link_count": count_official_links(links),
                    "direct_internal_link_count": direct_internal_links,
                    "image_count": len(image_urls),
                    "max_body_similarity": round(similarity, 4),
                },
                "most_similar_post": {"title": similar_title, "url": similar_url},
            }
        )
    return audits


def classify_post_issues(issue_codes: list[str]) -> str:
    if not issue_codes:
        return "no_change"
    if any(code in issue_codes for code in {"content_similarity_high", "content_similarity_warning"}):
        return "duplicate_risk"
    if "repeated_title_pattern" in issue_codes:
        return "title_improvement"
    if "internal_links_low" in issue_codes:
        return "internal_links"
    if any(code in issue_codes for code in {"image_count_low", "image_replace_needed", "reused_image_url"}):
        return "image_replace"
    if any(code in issue_codes for code in {"thin_content", "official_sources_low"}):
        return "body_expand"
    return "body_expand"


def readiness_status(missing_pages: list[str], posts: list[FeedPost], posts_needing_fix: list[dict]) -> str:
    if missing_pages or len(posts) < MIN_PUBLIC_POSTS_FOR_APPROVAL:
        return "not_ready"
    if posts_needing_fix:
        return "needs_fix"
    return "ready_to_apply"


def readiness_status_label(status: str) -> str:
    return {
        "not_ready": "신청 보류",
        "needs_fix": "보강 후 신청 권장",
        "ready_to_apply": "신청 가능",
    }.get(status, status)


def readiness_action_items(missing_pages: list[str], posts: list[FeedPost], posts_needing_fix: list[dict]) -> list[str]:
    actions = []
    if missing_pages:
        actions.append(f"필수 페이지 보강: {', '.join(missing_pages)}")
    if len(posts) < MIN_PUBLIC_POSTS_FOR_APPROVAL:
        actions.append(f"공개 글을 최소 {MIN_PUBLIC_POSTS_FOR_APPROVAL}개까지 안정적으로 쌓기")
    if posts_needing_fix:
        actions.append(f"보강 필요 글 {len(posts_needing_fix)}개: 얇은 본문, 공식 출처, 내부 링크, 이미지 반복 순서로 수정")
    if not actions:
        actions.append("현재 기준에서는 애드센스 신청 전 필수 구조가 충족됨")
    return actions


def fetch_posts(site_url: str, max_results: int = 50) -> list[FeedPost]:
    feed = fetch_feed(site_url, "posts", max_results)
    entries = feed.get("feed", {}).get("entry", [])
    posts = []
    for entry in entries:
        links = entry.get("link", [])
        url = next((link.get("href", "") for link in links if link.get("rel") == "alternate"), "")
        posts.append(
            FeedPost(
                title=entry.get("title", {}).get("$t", "Untitled"),
                url=url,
                published=entry.get("published", {}).get("$t", ""),
                content_html=(entry.get("content") or entry.get("summary") or {}).get("$t", ""),
            )
        )
    return posts


def fetch_pages(site_url: str) -> dict[str, str]:
    try:
        feed = fetch_feed(site_url, "pages", 50)
    except requests.RequestException:
        return {}
    pages = {}
    for entry in feed.get("feed", {}).get("entry", []):
        title = entry.get("title", {}).get("$t", "").strip()
        if title:
            pages[title.casefold()] = title
    return pages


def fetch_feed(site_url: str, feed_type: str, max_results: int) -> dict:
    base = site_url.rstrip("/")
    response = requests.get(f"{base}/feeds/{feed_type}/default?alt=json&max-results={max_results}", timeout=20)
    response.raise_for_status()
    return response.json()


def count_official_links(links: list[str]) -> int:
    return sum(1 for link in links if any(domain in link for domain in OFFICIAL_SOURCE_DOMAINS))


def count_internal_links(links: list[str], site_url: str) -> int:
    return sum(1 for link in links if is_direct_post_url(link, site_url))


def extract_image_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    return [img.get("src", "") for img in soup.find_all("img") if img.get("src")]


def title_pattern_key(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", title.casefold())
    normalized = re.sub(r"\b(0x[a-f0-9]+|\d+)\b", " ", normalized)
    words = [word for word in normalized.split() if word not in {"a", "an", "the", "your"}]
    return " ".join(words[:4])


def save_readiness_report(result: dict) -> tuple[str, str]:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{result['site']}-adsense-readiness-report.json"
    md_path = output_dir / f"{result['site']}-adsense-readiness-report.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_readiness_message(result) + "\n", encoding="utf-8")
    return str(json_path), str(md_path)


def build_readiness_message(result: dict) -> str:
    missing_pages = result.get("required_pages", {}).get("missing") or []
    lines = [
        f"[{result.get('site_name')}] 애드센스 준비 점검",
        "",
        f"- 상태: {result.get('status_label')} ({result.get('status')})",
        f"- 공개 글: {result.get('public_post_count')}개 / 기준 {result.get('minimum_public_posts')}개",
        f"- 필수 페이지: {'통과' if not missing_pages else '누락 ' + ', '.join(missing_pages)}",
        f"- 보강 필요 글: {result.get('posts_needing_fix_count')}개",
        "",
        "다음 조치:",
    ]
    lines.extend(f"- {item}" for item in result.get("action_items", []))
    audits = result.get("post_audits") or []
    flagged = [item for item in audits if item.get("classification") != "no_change"][:8]
    if flagged:
        lines.extend(["", "우선 점검 글:"])
        for item in flagged:
            lines.append(f"- {item.get('classification')}: {item.get('title')}")
    return "\n".join(lines)
