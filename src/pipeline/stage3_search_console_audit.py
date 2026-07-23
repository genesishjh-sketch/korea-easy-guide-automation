from __future__ import annotations

import argparse
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.config import load_settings
from src.reporting.adsense_readiness import fetch_posts
from src.reporting.search_console import SearchConsoleClient


DEFAULT_INSPECTION_COUNT = 5
FULL_FEED_LIMIT = 500
MIN_RAW_HTML_WORDS = 200


def run(
    site: str | None = None,
    inspection_count: int = DEFAULT_INSPECTION_COUNT,
    cohort_days: int | None = None,
) -> Path:
    settings = load_settings(site)
    client = SearchConsoleClient(settings)
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=89)
    posts = fetch_posts(settings.site_url, max_results=FULL_FEED_LIMIT)
    selected_posts = select_inspection_posts(posts, inspection_count, cohort_days)
    urls = [post.url for post in selected_posts if post.url]

    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "selection": {
            "mode": "cohort" if cohort_days else ("all" if inspection_count == 0 else "latest"),
            "inspection_count": len(urls),
            "available_post_count": len(posts),
            "cohort_days": cohort_days,
        },
        "sitemaps": client.list_sitemaps(),
        "url_inspections": client.inspect_urls(urls),
        "search_performance_90d": client.search_performance(start_date, end_date),
        "internal_link_audit": audit_internal_links(posts, settings.site_url),
    }
    result["current_live_checks"] = [
        check_live_indexability(item["url"])
        for item in result["url_inspections"]
        if item.get("status") == "connected" and item.get("url")
    ]
    result["summary"] = summarize_audit(result)
    result["action_items"] = action_items(result)

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-search-console-audit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    history_dir = output_dir / "search-console-audit-history" / settings.site_key
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_path = history_dir / f"{stamp}.json"
    history_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def select_inspection_posts(posts: list, inspection_count: int, cohort_days: int | None = None) -> list:
    if cohort_days:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=cohort_days)
        return [post for post in posts if published_at(post.published) >= cutoff]
    if inspection_count == 0:
        return posts
    return posts[: max(1, inspection_count)]


def published_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def summarize_audit(result: dict) -> dict:
    inspections = result.get("url_inspections", [])
    indexed = [item for item in inspections if is_indexed(item)]
    excluded = [item for item in inspections if item.get("status") == "connected" and not is_indexed(item)]
    errors = [item for item in inspections if item.get("status") == "error"]
    sitemap_items = result.get("sitemaps", {}).get("sitemaps", [])
    sitemap_errors = sum(item.get("errors", 0) for item in sitemap_items)
    sitemap_warnings = sum(item.get("warnings", 0) for item in sitemap_items)
    historical_redirects = [item for item in inspections if item.get("page_fetch_state") == "REDIRECT_ERROR"]
    live_checks = result.get("current_live_checks", [])
    live_failures = [item for item in live_checks if not item.get("ok")]
    live_by_url = {item.get("url"): item for item in live_checks}
    resolved_historical_redirects = sum(
        bool(live_by_url.get(item.get("url"), {}).get("ok")) for item in historical_redirects
    )
    link_audit = result.get("internal_link_audit", {})
    return {
        "inspected_count": len(inspections),
        "indexed_count": len(indexed),
        "not_indexed_count": len(excluded),
        "inspection_error_count": len(errors),
        "sitemap_count": len(sitemap_items),
        "sitemap_errors": sitemap_errors,
        "sitemap_warnings": sitemap_warnings,
        "historical_redirect_error_count": len(historical_redirects),
        "resolved_historical_redirect_count": resolved_historical_redirects,
        "current_live_indexability_failure_count": len(live_failures),
        "broken_internal_link_count": link_audit.get("broken_target_count", 0),
        "orphan_post_count": link_audit.get("orphan_post_count", 0),
        "structural_error": bool(
            errors
            or sitemap_errors
            or sitemap_warnings
            or live_failures
            or link_audit.get("broken_target_count", 0)
        ),
    }


def is_indexed(inspection: dict) -> bool:
    verdict = inspection.get("verdict", "").upper()
    coverage = inspection.get("coverage_state", "").casefold()
    return verdict == "PASS" or ("indexed" in coverage and "not indexed" not in coverage)


def has_live_fetch_failure(inspections: list[dict]) -> bool:
    failing_states = {"SERVER_ERROR", "SOFT_404", "BLOCKED_ROBOTS_TXT", "REDIRECT_ERROR", "ACCESS_DENIED"}
    return any(item.get("page_fetch_state", "").upper() in failing_states for item in inspections)


def action_items(result: dict) -> list[str]:
    items: list[str] = []
    summary = result.get("summary", {})
    inspections = result.get("url_inspections", [])
    sitemap_result = result.get("sitemaps", {})

    if sitemap_result.get("status") != "connected":
        items.append("Search Console OAuth 권한 또는 속성 연결을 복구한 뒤 sitemap 상태를 다시 확인합니다.")
    elif summary.get("sitemap_errors") or summary.get("sitemap_warnings"):
        items.append("오류 또는 경고가 있는 sitemap만 제거 후 canonical /sitemap.xml을 다시 제출합니다.")

    live_checks = result.get("current_live_checks", [])
    live_failures = [item for item in live_checks if not item.get("ok")]
    historical_redirects = [item for item in inspections if item.get("page_fetch_state") == "REDIRECT_ERROR"]
    if live_failures:
        content_failures = [
            item
            for item in live_failures
            if any(
                issue in item.get("issues", [])
                for issue in {"missing_h1", "missing_article_body", "raw_html_body_too_short", "javascript_dependent_content"}
            )
        ]
        if content_failures:
            items.append("원본 HTML에 H1과 본문이 없는 URL은 JavaScript 피드 주입을 제거하고 Blogger 서버 렌더링을 복구합니다.")
        else:
            items.append("가져오기 실패 URL은 공개 200, canonical, robots, 모바일 리디렉션을 먼저 수정합니다.")
    elif historical_redirects:
        items.append("Search Console의 Redirect error는 현재 재현되지 않는 과거 기록입니다. 대표 URL만 실제 URL 테스트 후 재검증을 요청합니다.")

    discovered = [
        item
        for item in inspections
        if item.get("status") == "connected"
        and not is_indexed(item)
        and not item.get("last_crawl_time")
    ]
    crawled = [
        item
        for item in inspections
        if item.get("status") == "connected"
        and not is_indexed(item)
        and item.get("last_crawl_time")
        and not has_live_fetch_failure([item])
    ]
    if discovered:
        items.append("아직 크롤링되지 않은 대표 URL은 직접 내부 링크와 sitemap 발견 경로를 유지하고 7~14일 관찰합니다.")
    if crawled:
        items.append("정상 크롤링 후 미색인 URL은 새 요청을 반복하지 말고 원문 고유성·검색 의도 충족도를 보강합니다.")
    link_audit = result.get("internal_link_audit", {})
    if link_audit.get("broken_target_count"):
        items.append(f"404 내부 링크 {link_audit['broken_target_count']}개를 현재 공개 글 URL로 교체합니다.")
    if link_audit.get("orphan_post_count"):
        items.append(f"본문 유입 링크가 없는 글 {link_audit['orphan_post_count']}개에 문맥상 관련된 공개 글 링크를 연결합니다.")
    if not items:
        items.append("구조 오류는 없습니다. 발행량을 늘리지 말고 Search Console 반영을 기다리며 주간 추세를 확인합니다.")
    return items


def check_live_indexability(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
    try:
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        soup = BeautifulSoup(response.text, "html.parser")
        canonical_tag = soup.select_one("link[rel~='canonical']")
        canonical = urljoin(response.url, canonical_tag.get("href", "")) if canonical_tag else ""
        robots = " ".join(
            tag.get("content", "")
            for tag in soup.select("meta[name='robots'], meta[name='googlebot']")
        ).casefold()
        meta_refresh = soup.select_one("meta[http-equiv='refresh' i]")
        article_body = soup.select_one("[itemprop='articleBody'], .post-body")
        body_text = article_body.get_text(" ", strip=True) if article_body else ""
        raw_html_word_count = len(re.findall(r"[A-Za-z0-9']+", body_text))
        h1_count = len(article_body.select("h1")) if article_body else 0
        article_schema = soup.select_one(
            "[itemtype='https://schema.org/Article'], [itemtype='https://schema.org/BlogPosting']"
        )
        feed_script_present = "/feeds/posts/default/" in response.text
        normalized_url = response.url.rstrip("/")
        normalized_canonical = canonical.rstrip("/")
        issues = []
        if response.status_code != 200:
            issues.append(f"http_{response.status_code}")
        if len(response.history) > 1:
            issues.append("multi_hop_redirect")
        if not canonical:
            issues.append("canonical_missing")
        elif normalized_canonical != normalized_url:
            issues.append("canonical_mismatch")
        if "noindex" in robots:
            issues.append("noindex")
        if meta_refresh:
            issues.append("meta_refresh")
        if not article_body:
            issues.append("missing_article_body")
        elif raw_html_word_count < MIN_RAW_HTML_WORDS:
            issues.append("raw_html_body_too_short")
        if h1_count == 0:
            issues.append("missing_h1")
        if feed_script_present and raw_html_word_count < MIN_RAW_HTML_WORDS:
            issues.append("javascript_dependent_content")
        if not article_schema:
            issues.append("missing_article_schema")
        return {
            "url": url,
            "ok": not issues,
            "status_code": response.status_code,
            "final_url": response.url,
            "redirect_count": len(response.history),
            "canonical": canonical,
            "robots": robots,
            "raw_html_word_count": raw_html_word_count,
            "h1_count": h1_count,
            "article_schema": bool(article_schema),
            "feed_script_present": feed_script_present,
            "issues": issues,
        }
    except requests.RequestException as exc:
        return {"url": url, "ok": False, "issues": ["request_error"], "error": str(exc)}


def audit_internal_links(posts: list, site_url: str) -> dict:
    site_host = urlparse(site_url).netloc.casefold()
    published_urls = {normalize_url(post.url) for post in posts if post.url}
    references: dict[str, list[dict[str, str]]] = {}
    incoming_counts = {url: 0 for url in published_urls}
    for post in posts:
        source_url = normalize_url(post.url)
        soup = BeautifulSoup(post.content_html or "", "html.parser")
        for link in soup.select("a[href]"):
            target = normalize_url(urljoin(site_url.rstrip("/") + "/", link.get("href", "")))
            parsed = urlparse(target)
            if parsed.netloc.casefold() != site_host or not parsed.path.endswith(".html"):
                continue
            if target == source_url:
                continue
            references.setdefault(target, []).append(
                {"source_title": post.title, "source_url": post.url, "anchor": link.get_text(" ", strip=True)}
            )
            if target in incoming_counts:
                incoming_counts[target] += 1

    checks = [check_internal_target(target, refs) for target, refs in sorted(references.items())]
    broken = [item for item in checks if not item["ok"]]
    redirects = [item for item in checks if item.get("redirect_count", 0)]
    orphan_urls = sorted(url for url, count in incoming_counts.items() if count == 0)
    titles_by_url = {normalize_url(post.url): post.title for post in posts}
    return {
        "published_post_count": len(published_urls),
        "checked_target_count": len(checks),
        "broken_target_count": len(broken),
        "broken_reference_count": sum(item["reference_count"] for item in broken),
        "redirect_target_count": len(redirects),
        "orphan_post_count": len(orphan_urls),
        "broken_targets": broken,
        "redirect_targets": redirects,
        "orphan_posts": [{"title": titles_by_url.get(url, ""), "url": url} for url in orphan_urls],
    }


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def check_internal_target(target: str, references: list[dict[str, str]]) -> dict:
    try:
        response = requests.get(
            target,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IndexabilityAudit/1.0)"},
            timeout=20,
            allow_redirects=True,
        )
        return {
            "url": target,
            "ok": response.status_code == 200,
            "status_code": response.status_code,
            "final_url": response.url,
            "redirect_count": len(response.history),
            "reference_count": len(references),
            "references": references,
        }
    except requests.RequestException as exc:
        return {
            "url": target,
            "ok": False,
            "status_code": 0,
            "final_url": "",
            "redirect_count": 0,
            "reference_count": len(references),
            "references": references,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Search Console sitemaps, representative URLs, and performance.")
    parser.add_argument("--site", help="Site profile key")
    parser.add_argument(
        "--inspection-count",
        type=int,
        default=DEFAULT_INSPECTION_COUNT,
        help="Inspect the latest N posts. Use 0 for every public post.",
    )
    parser.add_argument("--cohort-days", type=int, help="Inspect every post published in the last N days.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the audit finds a structural error.")
    args = parser.parse_args()
    path = run(args.site, max(0, args.inspection_count), args.cohort_days)
    print(path)
    if args.strict:
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("summary", {}).get("structural_error"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
