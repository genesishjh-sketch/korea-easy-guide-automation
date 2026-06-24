from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timezone
import json
from zoneinfo import ZoneInfo

import requests

from src.config import load_settings
from src.notifications.telegram import NotificationClient


KST = ZoneInfo("Asia/Seoul")


def run(site: str | None = None, today: datetime | None = None, after_hour: int | None = None) -> dict:
    settings = load_settings(site)
    now = today or datetime.now(tz=KST)
    feed = fetch_public_feed(settings.site_url)
    posts = parse_posts(feed)
    cutoff = now.replace(hour=after_hour, minute=0, second=0, microsecond=0) if after_hour is not None else None
    todays_posts = [
        post
        for post in posts
        if post["published_kst"].date() == now.date()
        and (cutoff is None or post["published_kst"] >= cutoff)
    ]
    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "checked_at_kst": now.isoformat(),
        "cutoff_kst": cutoff.isoformat() if cutoff else "",
        "status": "published_today" if todays_posts else "missing_today",
        "today_post_count": len(todays_posts),
        "latest_posts": [
            {
                "title": post["title"],
                "url": post["url"],
                "published_kst": post["published_kst"].isoformat(),
            }
            for post in posts[:5]
        ],
    }
    NotificationClient(settings).send(build_message(result))
    return result


def fetch_public_feed(site_url: str) -> dict:
    base = site_url.rstrip("/")
    response = requests.get(f"{base}/feeds/posts/default?alt=json&max-results=10", timeout=20)
    response.raise_for_status()
    return response.json()


def parse_posts(feed: dict) -> list[dict]:
    entries = feed.get("feed", {}).get("entry", [])
    posts = []
    for entry in entries:
        published_raw = entry.get("published", {}).get("$t", "")
        try:
            published_utc = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_utc = datetime.fromtimestamp(0, tz=timezone.utc)
        links = entry.get("link", [])
        url = ""
        for link in links:
            if link.get("rel") == "alternate":
                url = link.get("href", "")
                break
        posts.append(
            {
                "title": entry.get("title", {}).get("$t", "Untitled"),
                "url": url,
                "published_kst": published_utc.astimezone(KST),
            }
        )
    return sorted(posts, key=lambda post: post["published_kst"], reverse=True)


def build_message(result: dict) -> str:
    ok = result["status"] == "published_today"
    cutoff = result.get("cutoff_kst")
    lines = [
        "[Posting Bot] 공개 발행 확인",
        "",
        f"- 블로그: {result['site_name']}",
        f"- 사이트: {result['site_url']}",
        f"- 확인시각(KST): {result['checked_at_kst']}",
        f"- 기준시각(KST): {cutoff or '오늘 전체'}",
        f"- 상태: {'기준 이후 공개 글 확인' if ok else '기준 이후 공개 글 없음'}",
        f"- 기준 이후 공개 글 수: {result['today_post_count']}",
    ]
    latest = result.get("latest_posts", [])
    if latest:
        lines.extend(["", "최근 공개 글:"])
        for post in latest[:3]:
            lines.append(f"- {post['published_kst']} | {post['title']}")
            if post.get("url"):
                lines.append(f"  {post['url']}")
    if not ok:
        lines.extend(
            [
                "",
                "조치 필요:",
                "- GitHub Actions daily publish 실행 결과를 확인하세요.",
                "- Blogger 인증 또는 Hades 품질검수 실패가 있었는지 확인하세요.",
                "- 글이 발행됐지만 feed 반영이 늦는 경우 10~20분 후 다시 확인하세요.",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether today's public Blogger post exists.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--after-hour", type=int, help="Only count posts published at or after this KST hour.")
    args = parser.parse_args()
    print(json.dumps(run(args.site, after_hour=args.after_hour), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
