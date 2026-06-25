from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient


KST = ZoneInfo("Asia/Seoul")
DEFAULT_GITHUB_REPOSITORY = "genesishjh-sketch/korea-easy-guide-automation"


def run(site: str | None = None, today: datetime | None = None, after_hour: int | None = None) -> dict:
    settings = load_settings(site)
    now = today or datetime.now(tz=KST)
    feed = fetch_public_feed(settings.site_url)
    posts = parse_posts(feed)
    cutoff = now.replace(hour=after_hour, minute=0, second=0, microsecond=0) if after_hour is not None else None
    all_todays_posts = [
        post
        for post in posts
        if post["published_kst"].date() == now.date()
    ]
    todays_posts = [
        post
        for post in all_todays_posts
        if cutoff is None or post["published_kst"] >= cutoff
    ]
    status = publication_status(todays_posts, all_todays_posts, cutoff)
    daily_workflow = check_daily_workflow_status(now)
    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "checked_at_kst": now.isoformat(),
        "cutoff_kst": cutoff.isoformat() if cutoff else "",
        "status": status,
        "today_post_count": len(todays_posts),
        "today_total_post_count": len(all_todays_posts),
        "daily_workflow": daily_workflow,
        "latest_posts": [
            {
                "title": post["title"],
                "url": post["url"],
                "published_kst": post["published_kst"].isoformat(),
            }
            for post in posts[:5]
        ],
    }
    NotificationClient(settings).send_required(build_message(result))
    return result


def save_result(result: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{result['site']}-publication-check.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def fetch_public_feed(site_url: str) -> dict:
    base = site_url.rstrip("/")
    response = requests.get(f"{base}/feeds/posts/default?alt=json&max-results=10", timeout=20)
    response.raise_for_status()
    return response.json()


def check_daily_workflow_status(now: datetime, repository: str = DEFAULT_GITHUB_REPOSITORY) -> dict:
    try:
        runs = fetch_daily_workflow_runs(repository)
    except Exception as exc:
        return {
            "status": "unknown",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "note": "GitHub Actions 실행 상태를 확인하지 못했습니다. Blogger 공개 글 기준으로 발행 여부를 판단합니다.",
        }

    today_runs = []
    for run in runs:
        created_at = parse_github_datetime(run.get("created_at", ""))
        if created_at and created_at.astimezone(KST).date() == now.date():
            today_runs.append(
                {
                    "id": run.get("id"),
                    "event": run.get("event", ""),
                    "status": run.get("status", ""),
                    "conclusion": run.get("conclusion"),
                    "created_at_kst": created_at.astimezone(KST).isoformat(),
                    "url": run.get("html_url", ""),
                    "head_sha": run.get("head_sha", "")[:7],
                }
            )

    if not today_runs:
        return {
            "status": "no_run_today",
            "today_run_count": 0,
            "note": "오늘 Easy PC Daily workflow 실행 기록이 아직 없습니다.",
        }

    latest = today_runs[0]
    latest_status = latest.get("status")
    latest_conclusion = latest.get("conclusion")
    if latest_status == "completed" and latest_conclusion == "success":
        status = "success"
    elif latest_status == "completed":
        status = "failed"
    else:
        status = "in_progress"
    return {
        "status": status,
        "today_run_count": len(today_runs),
        "latest_run": latest,
    }


def fetch_daily_workflow_runs(repository: str) -> list[dict]:
    workflow = quote("easy-pc-daily.yml", safe="")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/runs?per_page=10"
    response = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "easy-pc-fix-publication-check"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("workflow_runs", [])


def parse_github_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def publication_status(todays_posts: list[dict], all_todays_posts: list[dict], cutoff: datetime | None) -> str:
    if todays_posts:
        return "published_today"
    if cutoff is not None and all_todays_posts:
        return "published_today_before_cutoff"
    return "missing_today"


def is_success_status(status: str | None) -> bool:
    return status in {"published_today", "published_today_before_cutoff"}


def build_message(result: dict) -> str:
    ok = is_success_status(result.get("status"))
    cutoff = result.get("cutoff_kst")
    before_cutoff = result.get("status") == "published_today_before_cutoff"
    lines = [
        "[Posting Bot] 공개 발행 확인",
        "",
        f"- 블로그: {result['site_name']}",
        f"- 사이트: {result['site_url']}",
        f"- 확인시각(KST): {result['checked_at_kst']}",
        f"- 기준시각(KST): {cutoff or '오늘 전체'}",
        f"- 상태: {publication_status_label(result.get('status'))}",
        f"- 기준 이후 공개 글 수: {result['today_post_count']}",
        f"- 오늘 전체 공개 글 수: {result.get('today_total_post_count', result['today_post_count'])}",
    ]
    workflow = result.get("daily_workflow") or {}
    if workflow:
        lines.extend(
            [
                f"- Daily workflow 상태: {daily_workflow_status_label(workflow.get('status'))}",
                f"- 오늘 Daily workflow 실행 수: {workflow.get('today_run_count', 0)}",
            ]
        )
        latest_run = workflow.get("latest_run") or {}
        if latest_run:
            lines.append(f"- 최신 workflow run: {latest_run.get('created_at_kst')} | {latest_run.get('conclusion') or latest_run.get('status')}")
            if latest_run.get("url"):
                lines.append(f"  {latest_run.get('url')}")
        if workflow.get("note"):
            lines.append(f"- workflow 참고: {workflow.get('note')}")
    todays_latest = [
        post
        for post in result.get("latest_posts", [])
        if cutoff and post.get("published_kst", "") >= cutoff
    ]
    if ok and todays_latest:
        first_post = todays_latest[0]
        lines.extend(
            [
                f"- 확인된 최신 글: {first_post.get('title', '제목 없음')}",
                f"- 최신 글 URL: {first_post.get('url', 'URL 없음')}",
            ]
        )
    elif before_cutoff:
        today_latest = [
            post
            for post in result.get("latest_posts", [])
            if str(post.get("published_kst", "")).split("T", 1)[0]
            == str(result.get("checked_at_kst", "")).split("T", 1)[0]
        ]
        if today_latest:
            first_post = today_latest[0]
            lines.extend(
                [
                    f"- 확인된 오늘 글: {first_post.get('title', '제목 없음')}",
                    f"- 오늘 글 URL: {first_post.get('url', 'URL 없음')}",
                ]
            )
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
    elif workflow.get("status") in {"no_run_today", "failed", "unknown"}:
        lines.extend(
            [
                "",
                "운영 참고:",
                "- 공개 글은 확인됐지만 Daily workflow 상태 점검이 필요합니다.",
                "- GitHub Actions Easy PC Fix Daily Publish 실행 기록과 다음 백업 스케줄을 확인하세요.",
            ]
        )
    return "\n".join(lines)


def publication_status_label(status: str | None) -> str:
    if status == "published_today":
        return "기준 이후 공개 글 확인"
    if status == "published_today_before_cutoff":
        return "오늘 공개 글 확인, 기준시각 전 발행"
    return "기준 이후 공개 글 없음"


def daily_workflow_status_label(status: str | None) -> str:
    labels = {
        "success": "오늘 실행 성공",
        "failed": "오늘 실행 실패",
        "in_progress": "실행 중",
        "no_run_today": "오늘 실행 기록 없음",
        "unknown": "확인 불가",
    }
    return labels.get(status or "", status or "확인 불가")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether today's public Blogger post exists.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--after-hour", type=int, help="Only count posts published at or after this KST hour.")
    args = parser.parse_args()
    result = run(args.site, after_hour=args.after_hour)
    save_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not is_success_status(result.get("status")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
