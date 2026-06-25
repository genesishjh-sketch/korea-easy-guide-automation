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
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import REDDIT_CLIENT_ID_SECRET
from src.utils.reddit_setup import REDDIT_CLIENT_SECRET_SECRET
from src.utils.reddit_setup import github_secret_mapping
from src.utils.reddit_setup import reddit_app_field_guide
from src.utils.reddit_setup import reddit_oauth_secret_label
from src.utils.text import clean_space


DEFAULT_WINDOWS_QUERY = "wifi button missing windows 11"
DEFAULT_HEALTH_QUERIES = [
    DEFAULT_WINDOWS_QUERY,
    "windows update error",
    "windows 11 settings not opening",
    "bluetooth disappeared windows 11",
    "onedrive sync error",
]


def run(site: str | None = None, query: str | None = None, limit: int = 3, notify: bool = False) -> Path:
    settings = load_settings(site)
    selected_query = query or default_query(site)
    result = check_reddit_oauth_with_fallback_queries(settings, selected_query, limit)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_report = build_markdown_report(result)
    result = {
        **result,
        "human_summary_markdown": markdown_report,
    }
    output_path = output_dir / f"{settings.site_key}-reddit-health.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_dir / f"{settings.site_key}-reddit-health.md"
    markdown_path.write_text(markdown_report, encoding="utf-8")
    if notify:
        NotificationClient(settings).send_required(build_message(result))
    return output_path


def check_reddit_oauth_with_fallback_queries(settings: Any, query: str, limit: int = 3) -> dict:
    queries = ordered_health_queries(query)
    attempts = []
    for selected_query in queries:
        result = check_reddit_oauth(settings, selected_query, limit)
        attempts.append(
            {
                "query": selected_query,
                "status": result.get("status"),
                "oauth_signal_count": result.get("oauth_signal_count", 0),
                "tested_subreddits": result.get("tested_subreddits", []),
                "matched_subreddits": result.get("matched_subreddits", []),
                "per_subreddit_counts": result.get("per_subreddit_counts", {}),
                "error_type": result.get("error_type", ""),
            }
        )
        if result.get("status") != "oauth_connected_no_results":
            result["query_attempts"] = attempts
            result["query_attempt_count"] = len(attempts)
            return result
        if result.get("oauth_signal_count", 0):
            result["query_attempts"] = attempts
            result["query_attempt_count"] = len(attempts)
            return result

    result["query_attempts"] = attempts
    result["query_attempt_count"] = len(attempts)
    if result.get("status") == "oauth_connected_no_results":
        result["action_required"] = (
            "OAuth 연결은 됐지만 대표 Windows 검색어에서도 결과가 없습니다. subreddit 목록 또는 Reddit 검색 제한을 점검하세요."
        )
        result["remediation_steps"] = [
            "EASY_PC_FIX_GUIDE_REDDIT_SUBREDDITS에 WindowsHelp, Windows11, techsupport, pchelp가 포함되어 있는지 확인하세요.",
            "Actions > Easy PC Fix Reddit OAuth Health에서 더 일반적인 query로 수동 재실행하세요.",
            "Reddit 계정/API 제한 또는 subreddit 검색 제한이 있는지 확인하세요.",
        ]
    return result


def ordered_health_queries(primary_query: str) -> list[str]:
    seen = set()
    queries = []
    for query in [primary_query, *DEFAULT_HEALTH_QUERIES]:
        normalized = clean_space(query)
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            queries.append(normalized)
    return queries


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
        "tested_subreddits": [],
        "matched_subreddits": [],
        "first_successful_subreddit": "",
        "error_type": "",
        "error": "",
        "action_required": "",
        "remediation_steps": [],
        "setup_links": setup_links(settings),
    }
    if not settings.reddit_user_agent:
        return {
            **base,
            "status": "missing_user_agent",
            **reddit_health_metadata("missing_user_agent"),
            "action_required": "REDDIT_USER_AGENT를 설정하세요.",
            "remediation_steps": [
                "GitHub Variables에 REDDIT_USER_AGENT 또는 EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT를 설정하세요.",
                "예: easy-pc-fix-guide/0.1 by your-reddit-username",
            ],
        }
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return {
            **base,
            "status": "missing_credentials",
            **reddit_health_metadata("missing_credentials"),
            "action_required": f"{reddit_oauth_secret_label()}을 GitHub Secrets 또는 .env에 설정하세요.",
            "remediation_steps": [
                "Reddit 앱을 script 타입으로 만들고 client id와 secret을 확인하세요.",
                f"GitHub Secrets에 {REDDIT_CLIENT_ID_SECRET}를 추가하세요.",
                f"GitHub Secrets에 {REDDIT_CLIENT_SECRET_SECRET}을 추가하세요.",
                "Actions > Easy PC Fix Reddit OAuth Health에서 수동 재실행하세요.",
            ],
        }
    try:
        import praw
    except Exception as exc:
        return {
            **base,
            "status": "missing_praw",
            **reddit_health_metadata("missing_praw"),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "action_required": "requirements.txt 설치 상태를 확인하세요. praw 패키지가 필요합니다.",
            "remediation_steps": [
                "requirements.txt에 praw가 포함되어 있는지 확인하세요.",
                "GitHub Actions의 Install dependencies 단계 로그를 확인하세요.",
            ],
        }

    try:
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        samples = []
        tested_subreddits = []
        matched_subreddits = []
        per_subreddit_counts = {}
        for subreddit in settings.reddit_subreddits:
            tested_subreddits.append(subreddit)
            subreddit_samples = []
            for submission in reddit.subreddit(subreddit).search(query, sort="relevance", limit=limit):
                title = clean_space(submission.title)
                if not title:
                    continue
                subreddit_samples.append(
                    {
                        "title": title,
                        "url": f"https://www.reddit.com{submission.permalink}",
                        "subreddit": subreddit,
                        "score": int(getattr(submission, "score", 0) or 0),
                        "num_comments": int(getattr(submission, "num_comments", 0) or 0),
                    }
                )
            per_subreddit_counts[subreddit] = len(subreddit_samples)
            if subreddit_samples:
                matched_subreddits.append(subreddit)
                samples.extend(subreddit_samples)
    except Exception as exc:
        return {
            **base,
            "status": "oauth_error",
            **reddit_health_metadata("oauth_error"),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "action_required": "Reddit 앱 유형, client id/secret, user agent, Reddit API 권한을 확인하세요.",
            "remediation_steps": [
                "Reddit 앱 타입이 script인지 확인하세요.",
                f"GitHub Secrets의 {reddit_oauth_secret_label()} 오타를 확인하세요.",
                "REDDIT_USER_AGENT가 비어 있거나 너무 일반적인 값인지 확인하세요.",
                "Reddit API 또는 계정 제한 메시지가 있는지 오류 내용을 확인하세요.",
            ],
        }

    if not samples:
        return {
            **base,
            "status": "oauth_connected_no_results",
            **reddit_health_metadata("oauth_connected_no_results"),
            "tested_subreddits": tested_subreddits,
            "per_subreddit_counts": per_subreddit_counts,
            "action_required": "OAuth 연결은 됐지만 검색 결과가 없습니다. query와 subreddit 목록을 점검하세요.",
            "remediation_steps": [
                "더 일반적인 Windows 오류 검색어로 재실행하세요.",
                "EASY_PC_FIX_GUIDE_REDDIT_SUBREDDITS 목록을 점검하세요.",
            ],
        }

    return {
        **base,
        "status": "oauth_connected",
        **reddit_health_metadata("oauth_connected"),
        "oauth_signal_count": len(samples),
        "sample_titles": [sample["title"] for sample in samples],
        "sample_urls": [sample["url"] for sample in samples],
        "tested_subreddits": tested_subreddits,
        "matched_subreddits": matched_subreddits,
        "first_successful_subreddit": matched_subreddits[0] if matched_subreddits else "",
        "per_subreddit_counts": per_subreddit_counts,
        "samples": samples,
        "action_required": "없음",
        "remediation_steps": [],
    }


def reddit_health_metadata(status: str) -> dict:
    mapping = {
        "oauth_connected": {
            "collection_status": "stable_oauth",
            "health_score": 100,
            "blocks_cadence_increase": False,
            "status_label": "Reddit OAuth 수집 안정",
        },
        "oauth_connected_no_results": {
            "collection_status": "oauth_no_results",
            "health_score": 70,
            "blocks_cadence_increase": True,
            "status_label": "OAuth 연결됨, 검색어/서브레딧 조정 필요",
        },
        "missing_credentials": {
            "collection_status": "missing_credentials",
            "health_score": 0,
            "blocks_cadence_increase": True,
            "status_label": "Reddit OAuth 키 없음",
        },
        "missing_user_agent": {
            "collection_status": "missing_user_agent",
            "health_score": 0,
            "blocks_cadence_increase": True,
            "status_label": "Reddit User-Agent 없음",
        },
        "missing_praw": {
            "collection_status": "missing_dependency",
            "health_score": 0,
            "blocks_cadence_increase": True,
            "status_label": "Reddit 수집 패키지 없음",
        },
        "oauth_error": {
            "collection_status": "oauth_error",
            "health_score": 20,
            "blocks_cadence_increase": True,
            "status_label": "Reddit OAuth 오류",
        },
    }
    return mapping.get(
        status,
        {
            "collection_status": "unknown",
            "health_score": 0,
            "blocks_cadence_increase": True,
            "status_label": "Reddit 상태 확인 필요",
        },
    )


def default_query(site: str | None = None) -> str:
    try:
        seeds = load_seed_list(site)
    except Exception:
        return DEFAULT_WINDOWS_QUERY
    return seeds[0] if seeds else DEFAULT_WINDOWS_QUERY


def setup_links(settings: Any) -> dict:
    recommended_app_name = f"{settings.site_name} Automation"
    recommended_user_agent = settings.reddit_user_agent or "easy-pc-fix-guide/0.1 by your-reddit-username"
    return {
        "reddit_apps_url": REDDIT_APPS_URL,
        "github_actions_secrets_url": GITHUB_SECRETS_URL,
        "recommended_app_type": "script",
        "recommended_app_name": recommended_app_name,
        "recommended_redirect_uri": "http://localhost:8080",
        "recommended_user_agent": recommended_user_agent,
        "reddit_app_field_guide": reddit_app_field_guide(recommended_app_name, recommended_user_agent),
        "github_secret_mapping": github_secret_mapping(),
    }


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
        f"- 테스트한 subreddit: {', '.join(result.get('tested_subreddits') or []) or '없음'}",
        f"- 신호 발견 subreddit: {', '.join(result.get('matched_subreddits') or []) or '없음'}",
        f"- 수집 상태: {result.get('status_label') or result.get('collection_status') or '확인 필요'}",
        f"- 상태 점수: {result.get('health_score', 0)}/100",
        f"- 발행량 증량 차단: {'예' if result.get('blocks_cadence_increase', True) else '아니오'}",
        f"- 조치: {result.get('action_required') or '확인 필요'}",
    ]
    if result.get("remediation_steps"):
        lines.extend(["", "다음 조치:"])
        for step in result.get("remediation_steps", [])[:6]:
            lines.append(f"- {step}")
    if result.get("query_attempts"):
        lines.extend(["", "검색어 재시도 기록:"])
        for attempt in result.get("query_attempts", [])[:6]:
            lines.append(
                f"- {attempt.get('query')}: {attempt.get('status')} "
                f"/ OAuth 신호 {attempt.get('oauth_signal_count', 0)}개"
            )
    setup = result.get("setup_links") or {}
    if setup and result.get("status") in {"missing_credentials", "missing_user_agent", "oauth_error"}:
        lines.extend(
            [
                "",
                "설정 링크:",
                f"- Reddit 앱 생성/확인: {setup.get('reddit_apps_url')}",
                f"- GitHub Secrets 입력: {setup.get('github_actions_secrets_url')}",
                f"- Reddit 앱 타입: {setup.get('recommended_app_type')}",
                f"- Redirect URI: {setup.get('recommended_redirect_uri')}",
                f"- 권장 User-Agent: {setup.get('recommended_user_agent')}",
            ]
        )
        if setup.get("reddit_app_field_guide"):
            lines.extend(["", "Reddit 앱 입력값:"])
            for step in setup.get("reddit_app_field_guide", [])[:7]:
                lines.append(f"- {step}")
        if setup.get("github_secret_mapping"):
            lines.extend(["", "GitHub에 넣을 값:"])
            for step in setup.get("github_secret_mapping", [])[:3]:
                lines.append(f"- {step}")
    if result.get("error"):
        lines.append(f"- 오류: {result.get('error_type')}: {result.get('error')}")
    if result.get("sample_titles"):
        lines.extend(["", "샘플 Reddit 신호:"])
        for title in result.get("sample_titles", [])[:5]:
            lines.append(f"- {title}")
    return "\n".join(lines)


def build_console_summary(result: dict) -> str:
    metadata = reddit_health_metadata(result.get("status", "unknown"))
    payload = {
        "site": result.get("site"),
        "site_name": result.get("site_name"),
        "status": result.get("status"),
        "query": result.get("query"),
        "oauth_signal_count": result.get("oauth_signal_count", 0),
        "collection_status": result.get("collection_status") or metadata["collection_status"],
        "health_score": result.get("health_score", metadata["health_score"]),
        "blocks_cadence_increase": result.get("blocks_cadence_increase", metadata["blocks_cadence_increase"]),
        "action_required": result.get("action_required"),
        "remediation_steps": result.get("remediation_steps", []),
        "setup_links": result.get("setup_links", {}),
        "tested_subreddits": result.get("tested_subreddits", []),
        "matched_subreddits": result.get("matched_subreddits", []),
        "first_successful_subreddit": result.get("first_successful_subreddit", ""),
        "sample_titles": result.get("sample_titles", [])[:3],
        "query_attempt_count": result.get("query_attempt_count", 0),
        "query_attempts": result.get("query_attempts", [])[:5],
    }
    if result.get("error_type"):
        payload["error_type"] = result.get("error_type")
    if result.get("error"):
        payload["error"] = result.get("error")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_markdown_report(result: dict) -> str:
    status_label = result.get("status_label") or result.get("collection_status") or result.get("status", "unknown")
    lines = [
        f"# Reddit OAuth Health: {result.get('site_name', result.get('site', 'Unknown Site'))}",
        "",
        f"- Status: {result.get('status', 'unknown')}",
        f"- Status label: {status_label}",
        f"- Query: {result.get('query', '')}",
        f"- OAuth signal count: {result.get('oauth_signal_count', 0)}",
        f"- Health score: {result.get('health_score', 0)}/100",
        f"- Blocks cadence increase: {'yes' if result.get('blocks_cadence_increase', True) else 'no'}",
        f"- Tested subreddits: {', '.join(result.get('tested_subreddits') or []) or 'none'}",
        f"- Matched subreddits: {', '.join(result.get('matched_subreddits') or []) or 'none'}",
        "",
        "## Action Required",
        "",
        result.get("action_required") or "None",
    ]
    if result.get("remediation_steps"):
        lines.extend(["", "## Remediation Steps", ""])
        lines.extend(f"- {step}" for step in result.get("remediation_steps", []))
    if result.get("query_attempts"):
        lines.extend(["", "## Query Attempts", ""])
        for attempt in result.get("query_attempts", []):
            lines.append(
                f"- {attempt.get('query')}: {attempt.get('status')} "
                f"({attempt.get('oauth_signal_count', 0)} OAuth signals)"
            )
    setup = result.get("setup_links") or {}
    if setup:
        lines.extend(
            [
                "",
                "## Setup Links",
                "",
                f"- Reddit apps: {setup.get('reddit_apps_url', '')}",
                f"- GitHub Actions secrets: {setup.get('github_actions_secrets_url', '')}",
                f"- Recommended app type: {setup.get('recommended_app_type', '')}",
                f"- Recommended redirect URI: {setup.get('recommended_redirect_uri', '')}",
                f"- Recommended user agent: {setup.get('recommended_user_agent', '')}",
            ]
        )
    if result.get("sample_titles"):
        lines.extend(["", "## Sample Signals", ""])
        lines.extend(f"- {title}" for title in result.get("sample_titles", [])[:10])
    if result.get("error"):
        lines.extend(["", "## Error", "", f"{result.get('error_type')}: {result.get('error')}"])
    return "\n".join(lines) + "\n"


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
    print(build_console_summary(result))
    if result.get("status") not in {"oauth_connected", "oauth_connected_no_results"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
