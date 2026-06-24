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

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-search-console-sitemap-submit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    NotificationClient(settings).send(build_message(settings.site_name, result))
    return output_path


def build_message(site_name: str, result: dict) -> str:
    ok = result.get("status") == "submitted"
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
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit Blogger sitemap to Google Search Console.")
    parser.add_argument("--sitemap-url", help="Defaults to SITE_URL/sitemap.xml")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    print(run(args.sitemap_url, args.site))


if __name__ == "__main__":
    main()
