from __future__ import annotations

import argparse
from datetime import date
from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.config import ROOT_DIR
from src.config import load_settings
from src.reporting.adsense_readiness import fetch_posts
from src.reporting.search_console import SearchConsoleClient


DEFAULT_INSPECTION_COUNT = 3


def run(site: str | None = None, inspection_count: int = DEFAULT_INSPECTION_COUNT) -> Path:
    settings = load_settings(site)
    client = SearchConsoleClient(settings)
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=89)
    posts = fetch_posts(settings.site_url, max_results=max(inspection_count, 10))
    urls = [post.url for post in posts if post.url][:inspection_count]

    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "checked_at": date.today().isoformat(),
        "sitemaps": client.list_sitemaps(),
        "url_inspections": client.inspect_urls(urls),
        "search_performance_90d": client.search_performance(start_date, end_date),
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
    return output_path


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
        "structural_error": bool(errors or sitemap_errors or sitemap_warnings or live_failures),
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
        normalized_url = response.url.rstrip("/")
        normalized_canonical = canonical.rstrip("/")
        issues = []
        if response.status_code != 200:
            issues.append(f"http_{response.status_code}")
        if len(response.history) > 1:
            issues.append("multi_hop_redirect")
        if canonical and normalized_canonical != normalized_url:
            issues.append("canonical_mismatch")
        if "noindex" in robots:
            issues.append("noindex")
        if meta_refresh:
            issues.append("meta_refresh")
        return {
            "url": url,
            "ok": not issues,
            "status_code": response.status_code,
            "final_url": response.url,
            "redirect_count": len(response.history),
            "canonical": canonical,
            "robots": robots,
            "issues": issues,
        }
    except requests.RequestException as exc:
        return {"url": url, "ok": False, "issues": ["request_error"], "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Search Console sitemaps, representative URLs, and performance.")
    parser.add_argument("--site", help="Site profile key")
    parser.add_argument("--inspection-count", type=int, default=DEFAULT_INSPECTION_COUNT)
    args = parser.parse_args()
    print(run(args.site, max(1, args.inspection_count)))


if __name__ == "__main__":
    main()
