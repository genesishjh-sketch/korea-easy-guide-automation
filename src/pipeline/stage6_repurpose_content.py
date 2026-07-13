from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.config import load_settings
from src.reporting.adsense_readiness import FeedPost
from src.reporting.adsense_readiness import fetch_posts


def run(site: str | None = None, post_url: str | None = None, latest: bool = False) -> dict:
    settings = load_settings(site)
    posts = fetch_posts(settings.site_url, max_results=20)
    post = select_post(posts, post_url=post_url, latest=latest)
    if post is None:
        raise ValueError("No public post found for repurpose generation.")
    slug = slug_from_post(post)
    output_dir = ROOT_DIR / "data" / "repurpose" / settings.site_key / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_repurpose_payload(settings.site_key, settings.site_name, post)

    (output_dir / "naver_draft.md").write_text(payload["naver_draft"], encoding="utf-8")
    (output_dir / "threads_x_posts.md").write_text(payload["threads_x_posts"], encoding="utf-8")
    (output_dir / "card_news_outline.md").write_text(payload["card_news_outline_md"], encoding="utf-8")
    (output_dir / "card_news_outline.json").write_text(
        json.dumps(payload["card_news_outline"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary_faq.md").write_text(payload["summary_faq"], encoding="utf-8")
    manifest = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "source_title": post.title,
        "source_url": post.url,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "output_dir": str(output_dir),
        "files": sorted(path.name for path in output_dir.iterdir()),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def select_post(posts: list[FeedPost], post_url: str | None = None, latest: bool = False) -> FeedPost | None:
    if post_url:
        return next((post for post in posts if post.url.rstrip("/") == post_url.rstrip("/")), None)
    if latest and posts:
        return posts[0]
    return posts[0] if posts else None


def build_repurpose_payload(site_key: str, site_name: str, post: FeedPost) -> dict:
    soup = BeautifulSoup(post.content_html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    headings = [heading.get_text(" ", strip=True) for heading in soup.find_all(["h2", "h3"])][:10]
    bullets = sentence_fragments(text, limit=8)
    faq_items = extract_faq_items(soup)
    slide_outline = build_card_news_outline(site_key, post.title, headings, bullets)
    return {
        "naver_draft": build_naver_draft(site_name, post, headings, bullets, faq_items),
        "threads_x_posts": build_threads_posts(site_name, post, bullets),
        "card_news_outline": slide_outline,
        "card_news_outline_md": build_card_news_markdown(slide_outline),
        "summary_faq": build_summary_faq(post, bullets, faq_items),
    }


def build_naver_draft(site_name: str, post: FeedPost, headings: list[str], bullets: list[str], faq_items: list[str]) -> str:
    lines = [
        f"# {post.title}",
        "",
        f"출처 글: {post.url}",
        "",
        "이 글은 초보자가 바로 확인할 수 있도록 핵심만 한국어로 다시 정리한 초안입니다. 자동 발행용이 아니며, 네이버에 올리기 전 실제 화면과 최신 공식 정보를 한 번 더 확인합니다.",
        "",
        "## 핵심 요약",
    ]
    lines.extend(f"- {item}" for item in bullets[:5])
    if headings:
        lines.extend(["", "## 본문 구성"])
        lines.extend(f"- {heading}" for heading in headings[:8])
    if faq_items:
        lines.extend(["", "## 자주 묻는 질문 초안"])
        lines.extend(f"- {item}" for item in faq_items[:5])
    lines.extend(
        [
            "",
            "## 발행 전 체크",
            "- 공식 사이트 링크가 현재도 열리는지 확인",
            "- 기존 블로그 글과 제목/각도가 겹치지 않는지 확인",
            f"- 원문 사이트명: {site_name}",
        ]
    )
    return "\n".join(lines) + "\n"


def build_threads_posts(site_name: str, post: FeedPost, bullets: list[str]) -> str:
    snippets = bullets[:3] or [post.title]
    lines = []
    for index, snippet in enumerate(snippets, 1):
        lines.extend(
            [
                f"{index}. {snippet}",
                f"Full guide: {post.url}",
                f"Source: {site_name}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_card_news_outline(site_key: str, title: str, headings: list[str], bullets: list[str]) -> list[dict]:
    opening = "여행자가 실제로 헷갈리는 장면" if site_key == "korea_easy_guide" else "초보자가 PC 문제를 발견한 순간"
    visual_style = "실제 장소/상황 기반 사진형 또는 고급 일러스트" if site_key == "korea_easy_guide" else "실제 책상 사진형, 추상 다이어그램, 클로즈업을 섞은 고급 AI 이미지"
    slides = [
        {"slide": 1, "title": title, "body": opening, "image_direction": f"{visual_style}, cover scene, not reused"},
        {"slide": 2, "title": "먼저 확인할 것", "body": bullets[0] if bullets else "문제를 바로 단정하지 말고 현재 상태부터 확인", "image_direction": "checklist or diagnostic scene"},
    ]
    for heading in headings[:4]:
        slides.append(
            {
                "slide": len(slides) + 1,
                "title": heading,
                "body": next((item for item in bullets if item.lower() not in heading.lower()), heading),
                "image_direction": "different angle, different subject, no repeated laptop-on-desk pattern",
            }
        )
    slides.extend(
        [
            {
                "slide": len(slides) + 1,
                "title": "주의할 점",
                "body": "공식 안내와 현재 화면을 확인한 뒤 안전한 방법부터 진행",
                "image_direction": "warning or decision moment, distinct composition",
            },
            {
                "slide": len(slides) + 1,
                "title": "마무리",
                "body": "전체 글에서 자세한 단계와 공식 링크 확인",
                "image_direction": "clean final summary visual, no generic stock feeling",
            },
        ]
    )
    return slides[:8]


def build_card_news_markdown(slides: list[dict]) -> str:
    lines = ["# 카드뉴스 구성안", ""]
    for slide in slides:
        lines.extend(
            [
                f"## {slide['slide']}. {slide['title']}",
                slide["body"],
                "",
                f"이미지 방향: {slide['image_direction']}",
                "",
            ]
        )
    return "\n".join(lines)


def build_summary_faq(post: FeedPost, bullets: list[str], faq_items: list[str]) -> str:
    lines = [f"# 재활용 요약 / FAQ", "", f"- 원문: {post.title}", f"- URL: {post.url}", "", "## 짧은 요약"]
    lines.extend(f"- {item}" for item in bullets[:5])
    lines.extend(["", "## FAQ 소재"])
    if faq_items:
        lines.extend(f"- {item}" for item in faq_items[:8])
    else:
        lines.extend(["- 이 문제를 먼저 확인해야 하는 이유는?", "- 초보자가 실수하기 쉬운 부분은?", "- 공식 정보는 어디서 확인해야 하나요?"])
    return "\n".join(lines) + "\n"


def extract_faq_items(soup: BeautifulSoup) -> list[str]:
    items = []
    faq_heading = soup.find(string=re.compile(r"FAQ|자주 묻는 질문", re.I))
    if not faq_heading:
        return items
    for heading in soup.find_all(["h3", "strong"]):
        text = heading.get_text(" ", strip=True)
        if text and "?" in text:
            items.append(text)
    return items


def sentence_fragments(text: str, limit: int = 8) -> list[str]:
    clean = re.sub(r"\s+", " ", text)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", clean) if len(item.strip()) >= 45]
    return [sentence[:180].rstrip() for sentence in sentences[:limit]]


def slug_from_post(post: FeedPost) -> str:
    path = urlparse(post.url).path.strip("/")
    candidate = path.rsplit("/", 1)[-1].replace(".html", "") if path else post.title
    slug = re.sub(r"[^a-z0-9-]+", "-", candidate.casefold()).strip("-")
    return slug or "latest-post"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create no-publish repurpose drafts for a Blogger post.")
    parser.add_argument("--site", help="Site profile key.")
    parser.add_argument("--post-url", help="Specific public Blogger post URL.")
    parser.add_argument("--latest", action="store_true", help="Use the latest public post.")
    args = parser.parse_args()
    result = run(args.site, post_url=args.post_url, latest=args.latest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
