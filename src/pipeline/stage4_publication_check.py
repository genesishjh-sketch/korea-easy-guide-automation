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
from src.reporting.daily_reports import read_daily_success_report


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
    daily_success = read_daily_success_report(settings.site_key)
    daily_success_context = classify_daily_success_context(daily_success)
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
        "daily_success": daily_success,
        "daily_success_context": daily_success_context,
        "latest_posts": [
            {
                "title": post["title"],
                "url": post["url"],
                "published_kst": post["published_kst"].isoformat(),
            }
            for post in posts[:5]
        ],
    }
    result["publication_evidence"] = assess_publication_evidence(result)
    save_result(result)
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


def classify_daily_success_context(report: dict) -> dict:
    status = report.get("status", "not_uploaded")
    mode = report.get("mode", "")
    if status == "not_uploaded":
        return {
            "status": "not_uploaded",
            "publish_related": False,
            "label": "일일 성공 리포트 없음",
            "note": "발행 확인은 Blogger 공개 피드와 Daily workflow 상태를 기준으로 판단합니다.",
        }
    if mode == "validate" or status == "validated":
        return {
            "status": "validation_only",
            "publish_related": False,
            "label": "검증 모드 리포트",
            "note": "최근 일일 성공 리포트는 validate 실행 결과이며 공개 발행 결과가 아닙니다.",
        }
    if status in {"published", "skipped_daily_limit", "skipped_duplicate", "draft_uploaded"}:
        return {
            "status": "publish_related",
            "publish_related": True,
            "label": "발행 workflow 리포트",
            "note": "",
        }
    return {
        "status": "unknown",
        "publish_related": False,
        "label": "판단 필요",
        "note": f"최근 일일 성공 리포트 상태를 해석하지 못했습니다: {status}",
    }


def assess_publication_evidence(result: dict) -> dict:
    if result.get("status") == "duplicate_today":
        return {
            "status": "duplicate_publication_detected",
            "label": "오늘 공개 글이 하루 1개 기준을 초과",
            "note": "자동 발행 중복, 수동 발행, 또는 예약 발행 충돌 가능성이 있습니다. 최신 공개 글 목록과 Daily workflow 실행 수를 확인하세요.",
            "needs_attention": True,
        }
    public_feed_ok = is_success_status(result.get("status"))
    workflow_status = (result.get("daily_workflow") or {}).get("status")
    workflow_ok = workflow_status == "success"
    workflow_problem = workflow_status in {"failed", "unknown"}
    daily_success = result.get("daily_success") or {}
    daily_context = result.get("daily_success_context") or classify_daily_success_context(daily_success)
    publish_related_report = bool(daily_context.get("publish_related"))

    if public_feed_ok and workflow_ok and publish_related_report:
        return {
            "status": "confirmed",
            "label": "공개 피드, workflow, 발행 리포트 일치",
            "note": "발행 증거가 서로 일치합니다.",
            "needs_attention": False,
        }
    if public_feed_ok and workflow_ok and daily_context.get("status") == "not_uploaded":
        return {
            "status": "feed_and_workflow_confirmed_report_unavailable",
            "label": "공개 피드와 workflow 확인, 일일 리포트 artifact 없음",
            "note": "발행 확인 workflow는 별도 실행이라 daily-success artifact가 없을 수 있습니다. 공개 피드와 Daily workflow 성공을 기준으로 확인했습니다.",
            "needs_attention": False,
        }
    if public_feed_ok and workflow_ok and not publish_related_report:
        return {
            "status": "feed_and_workflow_confirmed_report_not_publish",
            "label": "공개 피드와 workflow는 확인, 일일 리포트는 발행 리포트 아님",
            "note": daily_context.get("note") or "최근 일일 성공 리포트가 공개 발행 결과가 아닙니다.",
            "needs_attention": True,
        }
    if public_feed_ok:
        return {
            "status": "feed_confirmed_needs_workflow_check",
            "label": "공개 피드 확인, workflow/리포트 점검 필요",
            "note": "공개 글은 확인됐지만 workflow 또는 일일 리포트 증거가 완전히 일치하지 않습니다.",
            "needs_attention": True,
        }
    if workflow_ok or publish_related_report:
        return {
            "status": "workflow_or_report_without_public_feed",
            "label": "workflow/리포트는 있으나 공개 피드 글 없음",
            "note": "발행 지연, Blogger 공개 실패, feed 반영 지연 가능성을 확인하세요.",
            "needs_attention": True,
        }
    if workflow_problem:
        return {
            "status": "workflow_problem",
            "label": "workflow 상태 점검 필요",
            "note": "Daily workflow가 실패했거나 상태를 확인하지 못했습니다.",
            "needs_attention": True,
        }
    return {
        "status": "missing_publication_evidence",
        "label": "공개 발행 증거 없음",
        "note": "공개 피드, workflow, 일일 발행 리포트에서 공개 발행 증거를 찾지 못했습니다.",
        "needs_attention": True,
    }


def publication_status(todays_posts: list[dict], all_todays_posts: list[dict], cutoff: datetime | None) -> str:
    if len(all_todays_posts) > 1:
        return "duplicate_today"
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
    daily_success = result.get("daily_success") or {}
    daily_success_context = result.get("daily_success_context") or classify_daily_success_context(daily_success)
    if daily_success_context.get("status") != "not_uploaded":
        lines.append(f"- 최근 일일 리포트 구분: {daily_success_context.get('label')}")
        if daily_success_context.get("note"):
            lines.append(f"  - 참고: {daily_success_context.get('note')}")
    evidence = result.get("publication_evidence") or assess_publication_evidence(result)
    lines.append(f"- 발행 증거 판정: {evidence.get('label', '확인 필요')}")
    if evidence.get("note"):
        lines.append(f"  - 판정 참고: {evidence.get('note')}")
    if evidence.get("needs_attention"):
        lines.append("  - 추가 확인 필요: 예")
        if result.get("status") == "duplicate_today":
            lines.append("  - 중복 주의: 하루 1개 운영 기준을 초과했습니다. 오늘 공개 글 URL과 Daily workflow 실행 수를 확인하세요.")
        if before_cutoff:
            lines.append("  - 주의: 오늘 글은 확인됐지만 기준시각 이후 자동 발행 증거는 아직 부족합니다.")
        if daily_success_context.get("status") == "validation_only":
            lines.append("  - 리포트 주의: 최근 daily-success 파일은 검수 결과이며 발행 완료 리포트가 아닙니다.")
        if result.get("status") == "published_today" and not daily_success_context.get("publish_related"):
            lines.append("  - 다음 확인: 공개 URL과 오늘 Daily publish 리포트가 같은 실행에서 나온 결과인지 확인하세요.")
    operational_status = daily_success.get("operational_status") or {}
    if operational_status:
        lines.extend(
            [
                f"- 최근 일일 운영 상태: {operational_status.get('status_label', '확인 필요')}",
                "  - 발행 품질 안정성: "
                f"{'안정' if operational_status.get('publish_quality_ok') else '점검 필요'}",
                f"  - 수집 안정성: {operational_status.get('collection_status_label', '확인 필요')}",
                "  - 발행량 증량 준비: "
                f"{'예' if operational_status.get('ready_for_cadence_increase') else '아니오'}",
            ]
        )
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
    if status == "duplicate_today":
        return "오늘 공개 글 2개 이상 감지"
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
