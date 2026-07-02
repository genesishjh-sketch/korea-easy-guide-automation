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
        "sites": [site_result(site, minimum_posts, now) for site in selected_sites],
    }
    result["missing_sites"] = [item for item in result["sites"] if item.get("status") != "ok"]
    result["status"] = "missing_publication" if result["missing_sites"] else "ok"
    result["human_summary"] = build_message(result)
    save_result(result)
    if notify and result["status"] != "ok":
        NotificationClient(load_settings(selected_sites[-1])).send_required(result["human_summary"])
    return result


def site_result(site_key: str, minimum_posts: int, now: datetime) -> dict:
    settings = load_settings(site_key)
    try:
        posts = parse_posts(fetch_public_feed(settings.site_url))
        today_posts = [post for post in posts if post["published_kst"].date() == now.date()]
        return {
            "site": settings.site_key,
            "site_name": settings.site_name,
            "site_url": settings.site_url,
            "status": "ok" if len(today_posts) >= minimum_posts else "missing_today",
            "today_post_count": len(today_posts),
            "minimum_posts": minimum_posts,
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
        }


def save_result(result: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "daily-missing-publish-alert.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_message(result: dict) -> str:
    missing = result.get("missing_sites") or []
    lines = [
        "[Posting Bot] 발행 누락 경고",
        "",
        f"- 확인 시각: {result.get('checked_at_kst')}",
        f"- 기준: 블로그별 오늘 공개 글 {result.get('minimum_posts')}개 이상",
        f"- 상태: {'정상' if not missing else '조치 필요'}",
    ]
    if not missing:
        lines.append("- 모든 블로그에서 오늘 공개 글이 확인됐습니다.")
        return "\n".join(lines)

    lines.extend(["", "누락/오류 블로그:"])
    for item in missing:
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
    lines.extend(
        [
            "",
            "다음 조치:",
            "- Daily Publish workflow 실행 여부와 실패 step을 확인하세요.",
            "- Search Console/sitemap 실패는 발행 실패로 보지 말고, Blogger 공개 피드에 오늘 글이 있는지 먼저 확인하세요.",
            "- 오늘 글이 0개면 publish workflow를 수동 실행해 누락분을 채우세요.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Alert when today's Blogger publications are missing.")
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
