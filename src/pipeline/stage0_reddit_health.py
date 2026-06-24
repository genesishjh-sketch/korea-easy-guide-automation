from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.pipeline.daily_draft import load_seed_list
from src.utils.text import clean_space


DEFAULT_WINDOWS_QUERY = "wifi button missing windows 11"


def run(site: str | None = None, query: str | None = None, limit: int = 3, notify: bool = False) -> Path:
    settings = load_settings(site)
    selected_query = query or default_query(site)
    result = check_reddit_oauth(settings, selected_query, limit)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-reddit-health.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if notify:
        NotificationClient(settings).send_required(build_message(result))
    return output_path


def check_reddit_oauth(settings: Any, query: str, limit: int = 3) -> dict:
    base = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "query": query,
        "subreddits": settings.reddit_subreddits,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "oauth_signal_count": 0,
        "sample_titles": [],
        "sample_urls": [],
        "error_type": "",
        "error": "",
        "action_required": "",
    }
    if not settings.reddit_user_agent:
        return {
            **base,
            "status": "missing_user_agent",
            "action_required": "REDDIT_USER_AGENT를 설정하세요.",
        }
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return {
            **base,
            "status": "missing_credentials",
            "action_required": "REDDIT_CLIENT_ID와 REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
        }
    try:
        import praw
    except Exception as exc:
        return {
            **base,
            "status": "missing_praw",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "action_required": "requirements.txt 설치 상태를 확인하세요. praw 패키지가 필요합니다.",
        }

    try:
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        samples = []
        for subreddit in settings.reddit_subreddits:
            for submission in reddit.subreddit(subreddit).search(query, sort="relevance", limit=limit):
                title = clean_space(submission.title)
                if not title:
                    continue
                samples.append(
                    {
                        "title": title,
                        "url": f"https://www.reddit.com{submission.permalink}",
                        "subreddit": subreddit,
                        "score": int(getattr(submission, "score", 0) or 0),
                        "num_comments": int(getattr(submission, "num_comments", 0) or 0),
                    }
                )
            if samples:
                break
    except Exception as exc:
        return {
            **base,
            "status": "oauth_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "action_required": "Reddit 앱 유형, client id/secret, user agent, Reddit API 권한을 확인하세요.",
        }

    if not samples:
        return {
            **base,
            "status": "oauth_connected_no_results",
            "action_required": "OAuth 연결은 됐지만 검색 결과가 없습니다. query와 subreddit 목록을 점검하세요.",
        }

    return {
        **base,
        "status": "oauth_connected",
        "oauth_signal_count": len(samples),
        "sample_titles": [sample["title"] for sample in samples],
        "sample_urls": [sample["url"] for sample in samples],
        "samples": samples,
        "action_required": "없음",
    }


def default_query(site: str | None = None) -> str:
    try:
        seeds = load_seed_list(site)
    except Exception:
        return DEFAULT_WINDOWS_QUERY
    return seeds[0] if seeds else DEFAULT_WINDOWS_QUERY


def build_message(result: dict) -> str:
    status_kr = {
        "oauth_connected": "OAuth 연결 확인",
        "oauth_connected_no_results": "OAuth 연결됨, 결과 없음",
        "missing_credentials": "Reddit OAuth 키 없음",
        "missing_user_agent": "Reddit User-Agent 없음",
        "missing_praw": "PRAW 패키지 없음",
        "oauth_error": "OAuth 오류",
    }.get(result.get("status"), result.get("status", "unknown"))
    lines = [
        "[Posting Bot] Reddit OAuth 상태 점검",
        "",
        f"- 블로그: {result.get('site_name')}",
        f"- 상태: {status_kr}",
        f"- 검색어: {result.get('query')}",
        f"- subreddit: {', '.join(result.get('subreddits') or [])}",
        f"- OAuth 신호 수: {result.get('oauth_signal_count', 0)}",
        f"- 조치: {result.get('action_required') or '확인 필요'}",
    ]
    if result.get("error"):
        lines.append(f"- 오류: {result.get('error_type')}: {result.get('error')}")
    if result.get("sample_titles"):
        lines.extend(["", "샘플 Reddit 신호:"])
        for title in result.get("sample_titles", [])[:5]:
            lines.append(f"- {title}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether Reddit OAuth can collect live Reddit signals.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--query", help="Search query to test.")
    parser.add_argument("--limit", type=int, default=3, help="Maximum submissions to collect from the first matching subreddit.")
    parser.add_argument("--notify", action="store_true", help="Send the health result to Posting Bot.")
    args = parser.parse_args()
    path = run(args.site, args.query, args.limit, args.notify)
    print(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") not in {"oauth_connected", "oauth_connected_no_results"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
