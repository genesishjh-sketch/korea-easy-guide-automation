from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts


KST = ZoneInfo("Asia/Seoul")
DEFAULT_SITES = ["easy_pc_fix_guide", "korea_easy_guide"]


def run(
    sites: list[str] | None = None,
    minimum_posts: int = 1,
    today: datetime | None = None,
    notify: bool = True,
) -> dict:
    selected_sites = sites or DEFAULT_SITES
    now = today or datetime.now(tz=KST)
    result = {
        "checked_at_kst": now.isoformat(),
        "minimum_posts": minimum_posts,
        "expected_posts": minimum_posts,
        "sites": [site_result(site, minimum_posts, now) for site in selected_sites],
    }
    result["missing_sites"] = [
        item
        for item in result["sites"]
        if item.get("status") in {"missing_today", "feed_error"}
    ]
    result["duplicate_sites"] = [
        item
        for item in result["sites"]
        if item.get("status") == "duplicate_today"
    ]
    result["attention_sites"] = [
        item
        for item in result["sites"]
        if item.get("status") != "ok"
    ]
    if result["missing_sites"] and result["duplicate_sites"]:
        result["status"] = "publication_count_anomaly"
    elif result["duplicate_sites"]:
        result["status"] = "duplicate_publication"
    elif result["missing_sites"]:
        result["status"] = "missing_publication"
    else:
        result["status"] = "ok"
    result["human_summary"] = build_message(result)
    save_result(result)
    if notify and result["status"] != "ok":
        NotificationClient(load_settings(selected_sites[-1])).send_required(result["human_summary"])
    return result


def site_result(site_key: str, minimum_posts: int, now: datetime) -> dict:
    settings = load_settings(site_key)
    recovery = load_recovery_report(settings.site_key)
    try:
        posts = parse_posts(fetch_public_feed(settings.site_url))
        today_posts = [post for post in posts if post["published_kst"].date() == now.date()]
        if len(today_posts) < minimum_posts:
            status = "missing_today"
        elif len(today_posts) > minimum_posts:
            status = "duplicate_today"
        else:
            status = "ok"
        return {
            "site": settings.site_key,
            "site_name": settings.site_name,
            "site_url": settings.site_url,
            "status": status,
            "today_post_count": len(today_posts),
            "minimum_posts": minimum_posts,
            "expected_posts": minimum_posts,
            "today_posts": [
                {
                    "title": post["title"],
                    "url": post["url"],
                    "published_kst": post["published_kst"].isoformat(),
                }
                for post in today_posts
            ],
            "latest_post": {
                "title": posts[0]["title"],
                "url": posts[0]["url"],
                "published_kst": posts[0]["published_kst"].isoformat(),
            }
            if posts
            else {},
            "recovery": recovery,
        }
    except Exception as exc:
        return {
            "site": settings.site_key,
            "site_name": settings.site_name,
            "site_url": settings.site_url,
            "status": "feed_error",
            "today_post_count": 0,
            "minimum_posts": minimum_posts,
            "error": str(exc),
            "recovery": recovery,
        }


def save_result(result: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "daily-missing-publish-alert.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_recovery_report(site_key: str) -> dict:
    path = ROOT_DIR / "reports" / f"{site_key}-daily-recovery-report.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unreadable", "path": str(path)}


def build_message(result: dict) -> str:
    attention = result.get("attention_sites")
    if attention is None:
        attention = result.get("missing_sites") or []
    statuses = {item.get("status") for item in attention}
    if statuses == {"duplicate_today"}:
        title = "[Posting Bot] 중복 발행 경고"
    elif "duplicate_today" in statuses:
        title = "[Posting Bot] 발행 수량 경고"
    else:
        title = "[Posting Bot] 발행 누락 경고"
    lines = [
        title,
        "",
        f"- 확인 시각: {result.get('checked_at_kst')}",
        f"- 기준: 블로그별 오늘 공개 글 정확히 {result.get('expected_posts', result.get('minimum_posts'))}개",
        f"- 상태: {'정상' if not attention else '조치 필요'}",
    ]
    if not attention:
        lines.append("- 모든 블로그에서 오늘 목표 수와 일치하는 공개 글이 확인됐습니다.")
        return "\n".join(lines)

    lines.extend(["", "발행 수량 이상/오류 블로그:"])
    for item in attention:
        lines.extend(
            [
                f"- {item.get('site_name')}: {item.get('today_post_count', 0)}/{item.get('minimum_posts')}개, 상태 {item.get('status')}",
                f"  사이트: {item.get('site_url')}",
            ]
        )
        if item.get("latest_post"):
            latest = item["latest_post"]
            lines.append(f"  최신 공개 글: {latest.get('published_kst')} / {latest.get('title')}")
        if item.get("error"):
            lines.append(f"  오류: {item.get('error')}")
        recovery = item.get("recovery") or {}
        if recovery:
            lines.extend(
                [
                    f"  복구 상태: {recovery.get('status', 'unknown')}",
                    f"  복구 후 공개 수: {recovery.get('public_total_after_batch', 'n/a')}/{recovery.get('target_posts', 'n/a')}",
                ]
            )
            if recovery.get("next_actions"):
                lines.append("  복구 조치:")
                for action in recovery.get("next_actions", [])[:3]:
                    lines.append(f"  - {action}")
    if "duplicate_today" in statuses:
        lines.extend(
            [
                "",
                "중복 발행 조치:",
                "- 추가 발행을 즉시 중지하고 오늘 공개된 글의 주제·검색 의도·URL을 비교하세요.",
                "- 중복 글을 자동 삭제하지 말고, 색인 상태와 본문 차이를 확인한 뒤 통합·리디렉션 여부를 결정하세요.",
                "- 수동 seed 실행과 primary/backup 실행에서 일일 발행 상한이 모두 적용됐는지 확인하세요.",
            ]
        )
    if statuses == {"duplicate_today"}:
        return "\n".join(lines)
    lines.extend(
        [
            "",
            "다음 조치:",
            "- 누락은 알림으로 끝내지 말고 복구 대상으로 처리하세요.",
            "- Daily Publish workflow 실행 여부와 실패 step을 확인하고, latest daily batch / quality_report / image_plan / research_report를 확인하세요.",
            "- 원인이 이미지/출처/본문/중복/주제 문제인지 먼저 분류하세요.",
            "- 원인을 고친 뒤 Hades 품질검수를 다시 실행하고, 점수 90 이상 및 이슈 0개일 때 같은 날 보정 발행하세요.",
            "- Search Console/sitemap 실패는 발행 실패로 보지 말고, Blogger 공개 피드에 오늘 글이 있는지 먼저 확인하세요.",
            "- 3회 보강 또는 3개 후보가 모두 실패하면 약한 글을 올리지 말고 복구 실패 사유만 보고하세요.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alert when today's Blogger publication count is missing or duplicated."
    )
    parser.add_argument("--site", action="append", help="Site profile key. Repeat to check multiple sites.")
    parser.add_argument("--minimum-posts", type=int, default=1)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    result = run(args.site, args.minimum_posts, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
