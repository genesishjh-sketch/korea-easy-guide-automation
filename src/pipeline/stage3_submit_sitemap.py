from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.notifications.telegram import NotificationClient
from src.reporting.daily_reports import read_daily_success_report
from src.reporting.search_console import SearchConsoleClient


def run(sitemap_url: str | None = None, site: str | None = None) -> Path:
    settings = load_settings(site)
    selected_sitemap = sitemap_url or f"{settings.site_url.rstrip('/')}/sitemap.xml"
    result = SearchConsoleClient(settings).submit_sitemap(selected_sitemap)
    result["submitted_at"] = datetime.utcnow().isoformat() + "Z"
    result["daily_publish_context"] = build_daily_publish_context(settings.site_key)
    result["indexing_guidance"] = build_indexing_guidance(result)
    result["action_items"] = sitemap_action_items(result)
    result["human_summary"] = build_message(settings.site_name, result)

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-search-console-sitemap-submit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    NotificationClient(settings).send_required(result["human_summary"])
    return output_path


def build_message(site_name: str, result: dict) -> str:
    ok = result.get("status") == "submitted"
    guidance = result.get("indexing_guidance") or build_indexing_guidance(result)
    daily_context = result.get("daily_publish_context") or {}
    lines = [
        "[Posting Bot] Search Console sitemap 제출 결과",
        "",
        f"- 블로그: {site_name}",
        f"- 상태: {'제출 완료' if ok else '제출 실패'}",
        f"- Search Console 속성: {result.get('site_url', 'unknown')}",
        f"- Sitemap: {result.get('sitemap_url', 'unknown')}",
    ]
    if daily_context:
        lines.extend(
            [
                f"- 연결된 일일 발행 상태: {daily_context.get('status_label', daily_context.get('status', 'unknown'))}",
                f"- 연결된 글 제목: {daily_context.get('title') or '확인 필요'}",
                f"- 연결된 글 URL: {daily_context.get('url') or '확인 필요'}",
                f"- 연결된 글 품질점수: {daily_context.get('quality_score') if daily_context.get('quality_score') is not None else 'n/a'}",
            ]
        )
    if result.get("error"):
        action_items = result.get("action_items") or sitemap_action_items(result)
        lines.extend(
            [
                f"- 오류: {result.get('error')}",
                "",
                "조치 필요:",
                *[f"- {item}" for item in action_items],
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


def sitemap_action_items(result: dict) -> list[str]:
    if result.get("status") == "submitted":
        return [
            "Search Console > Sitemaps에서 제출 상태를 확인하세요.",
            "URL 검사에서 최신 글 URL이 발견되는지 다음 주간 보고서와 함께 확인하세요.",
            "색인은 즉시 보장되지 않으므로 노출/색인 데이터는 며칠 단위로 확인하세요.",
        ]
    return [
        "Google OAuth 토큰 또는 Search Console 권한을 확인하세요.",
        "sitemap URL이 공개 접속 가능한지 확인하세요.",
        "권한 또는 URL을 수정한 뒤 Easy PC Fix Daily Publish 또는 sitemap 제출 단계를 다시 실행하세요.",
    ]


def build_daily_publish_context(site_key: str) -> dict:
    report = read_daily_success_report(site_key, ROOT_DIR / "reports")
    status = report.get("status", "not_uploaded")
    return {
        "status": status,
        "status_label": daily_publish_status_label(status),
        "mode": report.get("mode", ""),
        "seed": report.get("seed", ""),
        "title": report.get("title", ""),
        "url": report.get("url", ""),
        "quality_score": report.get("quality_score"),
        "quality_passed": report.get("quality_passed"),
        "created_at": report.get("created_at", ""),
        "daily_limit_skipped": bool(report.get("daily_limit_skipped")),
    }


def daily_publish_status_label(status: str) -> str:
    labels = {
        "published": "공개 발행 완료",
        "draft_uploaded": "초안 업로드",
        "skipped_duplicate": "중복 감지로 발행 건너뜀",
        "skipped_daily_limit": "오늘 공개 글 이미 있어 추가 발행 건너뜀",
        "validated": "검증 완료",
        "not_uploaded": "일일 발행 리포트 없음",
    }
    return labels.get(status, status or "확인 필요")


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
