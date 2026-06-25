from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.reporting.weekly import WeeklyReporter


def run(site: str | None = None) -> Path:
    settings = load_settings(site)
    try:
        path = WeeklyReporter(settings).generate()
        NotificationClient(settings).send_required(path.read_text(encoding="utf-8"))
        remove_stale_weekly_failure_report(settings.site_key)
        return path
    except Exception as exc:
        save_weekly_failure_report(site, exc)
        NotificationClient(settings).send_required(build_weekly_failure_message(site, exc))
        raise


def build_weekly_failure_message(site: str | None, exc: Exception) -> str:
    settings = load_settings(site)
    error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    report_path = ROOT_DIR / "reports" / f"{settings.site_key}-weekly-failure.json"
    return "\n".join(
        [
            "[Posting Bot] 주간 리포트 실패",
            "",
            f"- 블로그: {settings.site_name}",
            f"- 사이트: {settings.site_url}",
            f"- 오류 유형: {type(exc).__name__}",
            f"- 오류: {error}",
            f"- 실패 리포트: {report_path}",
            "",
            "우선 조치:",
            *[f"- {item}" for item in weekly_failure_action_items(error)],
            "",
            "재실행:",
            "- GitHub Actions > Easy PC Fix Weekly Report를 수동 실행",
            "- 실패가 Search Console/Analytics 권한이면 Google OAuth 토큰을 갱신한 뒤 재실행",
        ]
    )


def weekly_failure_action_items(error: str) -> list[str]:
    error_lower = error.casefold()
    if "telegram" in error_lower or "notification" in error_lower:
        return [
            "텔레그램 전송 문제입니다. TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID GitHub Secrets를 확인하세요.",
            "봇이 차단되었거나 채팅방에서 제거되지 않았는지 확인하세요.",
        ]
    if "search console" in error_lower or "analytics" in error_lower or "oauth" in error_lower or "credentials" in error_lower:
        return [
            "Google 보고서 권한 문제 가능성이 큽니다. Search Console/GA4 OAuth 토큰과 권한을 확인하세요.",
            "속성 URL이 Blogger URL과 일치하는지 확인하세요.",
        ]
    if "feed" in error_lower or "blogger" in error_lower:
        return [
            "Blogger 공개 피드 또는 Blogger API 확인 문제입니다. 블로그 공개 URL과 Blogger 권한을 확인하세요.",
            "최근 글이 공개 상태인지 Blogger 대시보드와 공개 피드를 함께 확인하세요.",
        ]
    return [
        "reports 폴더의 weekly-failure.json traceback을 확인하세요.",
        "일일 성공/실패 리포트, publication-check, sitemap 제출 리포트가 있는지 확인하세요.",
    ]


def save_weekly_failure_report(site: str | None, exc: Exception) -> Path:
    settings = load_settings(site)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-weekly-failure.json"
    payload = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "status": "failed",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def remove_stale_weekly_failure_report(site_key: str) -> None:
    output_path = ROOT_DIR / "reports" / f"{site_key}-weekly-failure.json"
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a weekly automation report.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    path = run(args.site)
    print(path)


if __name__ == "__main__":
    main()
