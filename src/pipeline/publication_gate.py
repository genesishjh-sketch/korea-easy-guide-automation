from __future__ import annotations

import json
import os
from pathlib import Path
import time
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from bs4 import BeautifulSoup
import requests


LIVE_CHECK_TIMEOUT_SECONDS = 15
LIVE_CHECK_ATTEMPTS = 3
LIVE_CHECK_RETRY_SECONDS = 5
TRANSIENT_LIVE_STATUSES = {404, 408, 425, 429, 500, 502, 503, 504}
LIVE_CHECK_USER_AGENT = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; "
    "+http://www.google.com/bot.html)"
)


def new_publication_created(result: dict) -> bool:
    return verify_new_publication(result)["verified"]


def verify_new_publication(result: dict) -> dict:
    candidates = publication_candidates(result)
    checks = [verify_publication_candidate(candidate) for candidate in candidates]
    verified_count = sum(1 for check in checks if check["verified"])
    all_verified = bool(candidates) and verified_count == len(candidates)
    if not candidates:
        status = "no_new_publication"
    elif all_verified:
        status = "verified"
    elif verified_count:
        status = "verification_partial"
    else:
        status = "verification_failed"
    return {
        "verified": all_verified,
        "status": status,
        "candidate_count": len(candidates),
        "verified_count": verified_count,
        "candidates": checks,
    }


def publication_candidates(result: dict) -> list[dict]:
    if isinstance(result.get("published"), list):
        return [
            publication_candidate(item)
            for item in result["published"]
            if isinstance(item, dict)
        ]
    if result.get("mode") != "publish" or result.get("daily_limit_skipped"):
        return []
    result_path_value = str(result.get("publish_result") or "").strip()
    if not result_path_value:
        return [invalid_publication_candidate("publish_result_missing")]
    result_path = Path(result_path_value)
    if not result_path.is_file():
        return [
            invalid_publication_candidate(
                "publish_result_missing",
                result_path_value,
            )
        ]
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [
            invalid_publication_candidate(
                "publish_result_unreadable",
                result_path_value,
            )
        ]
    if not isinstance(payload, dict):
        return [
            invalid_publication_candidate(
                "publish_result_unreadable",
                result_path_value,
            )
        ]
    return [publication_candidate(payload)]


def invalid_publication_candidate(reason: str, result_path: str = "") -> dict:
    return {
        "url": "",
        "blogger_status": "",
        "draft": False,
        "skipped": False,
        "resolution_error": reason,
        "publish_result": result_path,
    }


def publication_candidate(payload: dict) -> dict:
    blogger = payload.get("blogger") or {}
    return {
        "url": str(blogger.get("url") or payload.get("url") or "").strip(),
        "blogger_status": str(
            blogger.get("status")
            or payload.get("blogger_status")
            or ""
        ).upper(),
        "draft": bool(payload.get("draft", False)),
        "skipped": bool(payload.get("skipped", False)),
    }


def verify_publication_candidate(candidate: dict) -> dict:
    url = str(candidate.get("url") or "").strip()
    result = {
        "url": url,
        "blogger_status": str(candidate.get("blogger_status") or ""),
        "verified": False,
        "reason": "",
    }
    if candidate.get("resolution_error"):
        result["reason"] = str(candidate["resolution_error"])
        if candidate.get("publish_result"):
            result["publish_result"] = str(candidate["publish_result"])
        return result
    if candidate.get("draft"):
        result["reason"] = "draft"
        return result
    if candidate.get("skipped"):
        result["reason"] = "skipped"
        return result
    if result["blogger_status"] != "LIVE":
        result["reason"] = "blogger_status_not_live"
        return result
    if not is_https_url(url):
        result["reason"] = "invalid_or_non_https_url"
        return result

    response = None
    fetch_error = None
    for attempt in range(LIVE_CHECK_ATTEMPTS):
        response = None
        try:
            response = requests.get(
                url,
                headers={"User-Agent": LIVE_CHECK_USER_AGENT},
                timeout=LIVE_CHECK_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
            fetch_error = None
        except requests.RequestException as exc:
            fetch_error = exc
        should_retry = (
            attempt < LIVE_CHECK_ATTEMPTS - 1
            and (
                fetch_error is not None
                or (
                    response is not None
                    and response.status_code in TRANSIENT_LIVE_STATUSES
                )
            )
        )
        if not should_retry:
            break
        time.sleep(LIVE_CHECK_RETRY_SECONDS)

    if response is None:
        result["reason"] = "live_fetch_error"
        result["error"] = str(fetch_error or "No HTTP response")
        return result

    result["http_status"] = response.status_code
    result["final_url"] = response.url
    if response.status_code != 200:
        result["reason"] = f"http_{response.status_code}"
        return result
    if response.history or normalize_url(response.url) != normalize_url(url):
        result["reason"] = "redirected_url"
        return result

    content_type = str(response.headers.get("Content-Type") or "").casefold()
    if content_type and "html" not in content_type:
        result["reason"] = "non_html_response"
        return result

    soup = BeautifulSoup(response.text or "", "html.parser")
    canonical_tag = soup.select_one("link[rel~='canonical']")
    canonical = (
        urljoin(response.url, str(canonical_tag.get("href") or "").strip())
        if canonical_tag
        else ""
    )
    result["canonical"] = canonical
    if not canonical:
        result["reason"] = "canonical_missing"
        return result
    if normalize_url(canonical) != normalize_url(response.url):
        result["reason"] = "canonical_mismatch"
        return result

    robots = " ".join(
        str(tag.get("content") or "")
        for tag in soup.select("meta[name='robots'], meta[name='googlebot']")
    ).casefold()
    if "noindex" in robots:
        result["reason"] = "noindex"
        return result

    result["verified"] = True
    result["reason"] = "live_indexable_url"
    return result


def is_https_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.casefold() == "https" and bool(parsed.netloc)


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            parsed.query,
            "",
        )
    )


def write_github_publication_output(result: dict) -> None:
    verification = verify_new_publication(result)
    result["publication_verification"] = verification
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        value = "true" if verification["verified"] else "false"
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"new_publication={value}\n")
            handle.write(f"publication_verification={verification['status']}\n")
    if verification["candidate_count"] and not verification["verified"]:
        reasons = ", ".join(
            f"{item.get('url') or 'missing-url'}={item.get('reason') or 'unknown'}"
            for item in verification["candidates"]
            if not item.get("verified")
        )
        raise RuntimeError(
            "Published URL failed live indexability verification: "
            f"{reasons or verification['status']}"
        )
