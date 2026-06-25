from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.notifications.telegram import NotificationClient
from src.reporting.search_console import SearchConsoleClient


def run(sitemap_url: str | None = None, site: str | None = None) -> Path:
    settings = load_settings(site)
    selected_sitemap = sitemap_url or f"{settings.site_url.rstrip('/')}/sitemap.xml"
    result = SearchConsoleClient(settings).submit_sitemap(selected_sitemap)
    result["indexing_guidance"] = build_indexing_guidance(result)

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-search-console-sitemap-submit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    NotificationClient(settings).send_required(build_message(settings.site_name, result))
    return output_path


def build_message(site_name: str, result: dict) -> str:
    ok = result.get("status") == "submitted"
    guidance = result.get("indexing_guidance") or build_indexing_guidance(result)
    lines = [
        "[Posting Bot] Search Console sitemap 제출 결과",
        "",
        f"- 블로그: {site_name}",
        f"- 상태: {'제출 완료' if ok else '제출 실패'}",
        f"- Search Console 속성: {result.get('site_url', 'unknown')}",
        f"- Sitemap: {result.get('sitemap_url', 'unknown')}",
    ]
    if result.get("error"):
        lines.extend(
            [
                f"- 오류: {result.get('error')}",
                "",
                "조치 필요:",
                "- Google OAuth 토큰 또는 Search Console 권한을 확인하세요.",
                "- sitemap URL이 공개 접속 가능한지 확인하세요.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "색인 안내:",
                f"- {guidance.get('summary')}",
                f"- 예상 대기: {guidance.get('expected_wait')}",
                f"- 확인 위치: {guidance.get('check_location')}",
                f"- 다음 확인: {guidance.get('next_check')}",
            ]
        )
    return "\n".join(lines)


def build_indexing_guidance(result: dict) -> dict:
    if result.get("status") != "submitted":
        return {
            "status": "needs_fix",
            "summary": "sitemap 제출이 실패했으므로 색인 대기 전에 오류를 먼저 복구해야 합니다.",
            "expected_wait": "오류 복구 후 다시 제출",
            "check_location": "Search Console > Sitemaps",
            "next_check": "OAuth 권한과 sitemap URL을 수정한 뒤 재실행",
        }
    return {
        "status": "submitted_waiting",
        "summary": "sitemap 제출은 Google에 새 글을 알려주는 단계이며, 즉시 검색 노출을 보장하지는 않습니다.",
        "expected_wait": "보통 며칠, 새 블로그는 더 오래 걸릴 수 있음",
        "check_location": "Search Console > Sitemaps, URL 검사, 페이지 색인 생성",
        "next_check": "다음 주간 보고서에서 색인/노출 페이지 수와 오류를 확인",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit Blogger sitemap to Google Search Console.")
    parser.add_argument("--sitemap-url", help="Defaults to SITE_URL/sitemap.xml")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    path = run(args.sitemap_url, args.site)
    print(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "submitted":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
