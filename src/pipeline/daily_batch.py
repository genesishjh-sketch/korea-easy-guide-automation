from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.adsense_rules import daily_publish_limit_from_env
from src.content.article_types import infer_article_type
from src.content.topic_scoring import infer_category
from src.notifications.telegram import NotificationClient
from src.pipeline.daily_draft import choose_publish_seed_candidates
from src.pipeline.daily_draft import is_duplicate_publish_result
from src.pipeline.daily_draft import is_quality_gate_failure
from src.pipeline.daily_draft import normalize_match_text
from src.pipeline.daily_draft import read_json
from src.pipeline.daily_draft import run_publish_with_duplicate_guard
from src.pipeline.daily_draft import save_daily_failure_report
from src.pipeline.daily_draft import save_daily_success_report
from src.pipeline.daily_draft import seed_quality_precheck
from src.pipeline.daily_draft import title_matches_existing
from src.pipeline.daily_draft import used_keywords
from src.pipeline.weekly_queue import today_queue_candidates
from src.publishing.blogger import BloggerPublisher
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.pipeline.publication_gate import write_github_publication_output
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
MAX_RECOVERY_ATTEMPTS = 3


def run(
    site: str | None = None,
    mode: str = "publish",
    max_posts: int = 1,
    explicit_seed: str | None = None,
    notify: bool = True,
) -> dict:
    settings = load_settings(site)
    max_posts = daily_publish_limit_from_env(str(max_posts), quality_review_enabled=True)
    if mode != "publish":
        raise ValueError("daily_batch currently supports publish mode only.")

    existing_today = count_public_posts_today(settings.site_url)
    remaining_slots = max(0, max_posts - existing_today)
    if remaining_slots == 0:
        result = build_batch_result(settings.site_key, max_posts, existing_today)
        result["status"] = "skipped_daily_limit"
        result["note"] = "오늘 공개 글 수가 목표 상한에 도달해 추가 발행하지 않았습니다."
        save_batch_report(result)
        save_recovery_report(build_recovery_report(result))
        if notify:
            notify_batch_completion(result)
        return result

    selected = select_seed_candidates(
        site=settings.site_key,
        content_domain=settings.content_domain,
        max_posts=1 if explicit_seed else recovery_candidate_limit(remaining_slots),
        explicit_seed=explicit_seed,
    )
    result = build_batch_result(settings.site_key, max_posts, existing_today)
    result["selected_candidates"] = selected

    for candidate in selected:
        if len(result["published"]) >= remaining_slots:
            break
        seed = candidate["seed"]
        article_dir: Path | None = None
        try:
            article_dir = run_stage1(seed, settings.site_key)
            result_path = run_publish_with_duplicate_guard(article_dir, settings.site_key)
        except Exception as exc:
            if is_quality_gate_failure(exc):
                result["held"].append(recover_quality_failure(candidate, exc, article_dir))
                continue
            save_daily_failure_report(seed, exc, settings.site_key, mode)
            result["failed"].append(
                {
                    "seed": seed,
                    "article_type": candidate["article_type"],
                    "category": candidate["category"],
                    "reason": "unexpected_error",
                    "error": "".join(traceback.format_exception_only(type(exc), exc)).strip(),
                }
            )
            continue

        if is_duplicate_publish_result(result_path):
            result["skipped"].append(
                {
                    "seed": seed,
                    "article_type": candidate["article_type"],
                    "category": candidate["category"],
                    "reason": "duplicate_public_post",
                    "publish_result": str(result_path),
                }
            )
            continue

        single_result = {
            "seed": seed,
            "article_dir": str(article_dir),
            "publish_result": str(result_path),
            "site": settings.site_key,
            "mode": mode,
            "skipped_duplicate_seeds": [],
            "skipped_quality_seeds": [],
        }
        save_daily_success_report(single_result)
        result["published"].append(build_published_item(single_result, candidate))

    result["status"] = "published" if result["published"] else "held_no_publishable_candidates"
    result["created_at"] = datetime.utcnow().isoformat() + "Z"
    result["post_publish_checks"] = run_post_publish_checks(settings.site_key, result.get("published") or [])
    save_batch_report(result)
    save_recovery_report(build_recovery_report(result))
    if notify:
        notify_batch_completion(result)
    return result


def recovery_candidate_limit(remaining_slots: int) -> int:
    return max(remaining_slots, remaining_slots * MAX_RECOVERY_ATTEMPTS)


def select_seed_candidates(
    site: str,
    content_domain: str,
    max_posts: int,
    explicit_seed: str | None = None,
) -> list[dict]:
    if not explicit_seed:
        queued = today_queue_candidates(site, max_posts=max_posts)
        if queued:
            return queued

    publish_used = used_keywords(site, include_validation=False)
    generated_used = used_keywords(site, include_validation=True)
    selected: list[dict] = []
    selected_types: set[str] = set()
    selected_categories: set[str] = set()
    max_precheck = int(os.getenv("DAILY_BATCH_MAX_PRECHECK", "12"))
    existing_titles = public_post_titles(site)
    recent_categories = set(public_recent_categories(site, content_domain, limit=max(6, max_posts * 2)))
    candidates: list[dict] = []

    for seed in choose_publish_seed_candidates(explicit_seed, site)[:max_precheck]:
        normalized = seed.casefold()
        category = infer_category(seed, content_domain)
        article_type = infer_article_type(seed, category, content_domain)
        precheck = seed_quality_precheck(seed, content_domain)
        precheck_status = precheck.get("status")
        if normalized in publish_used or normalized in generated_used:
            continue
        if seed_matches_existing_public_title(seed, existing_titles):
            continue
        if precheck_status not in {"ready", "not_applicable"}:
            continue
        candidates.append(
            {
                "seed": seed,
                "category": category,
                "article_type": article_type,
                "quality_precheck": precheck,
                "recent_category": category in recent_categories,
            }
        )

    for candidate in sorted(candidates, key=lambda item: (item["recent_category"], item["category"] in selected_categories)):
        category = candidate["category"]
        article_type = candidate["article_type"]
        if not explicit_seed and article_type in selected_types:
            continue
        if not explicit_seed and category in selected_categories:
            continue
        selected.append(candidate)
        selected_types.add(article_type)
        selected_categories.add(category)
        if len(selected) >= max_posts:
            break
    if len(selected) < max_posts:
        selected_seeds = {item["seed"] for item in selected}
        for candidate in candidates:
            if candidate["seed"] in selected_seeds:
                continue
            selected.append(candidate)
            selected_seeds.add(candidate["seed"])
            if len(selected) >= max_posts:
                break
    return selected


def public_recent_categories(site: str, content_domain: str, limit: int = 6) -> list[str]:
    try:
        settings = load_settings(site)
        posts = BloggerPublisher(settings).list_live_posts()
    except Exception:
        return []
    sorted_posts = sorted(posts, key=lambda post: post.get("published", ""), reverse=True)
    return [infer_category(post.get("title", ""), content_domain) for post in sorted_posts[:limit]]


def public_post_titles(site: str) -> list[str]:
    try:
        settings = load_settings(site)
        return [post.get("title", "") for post in BloggerPublisher(settings).list_live_posts()]
    except Exception:
        return []


def seed_matches_existing_public_title(seed: str, existing_titles: list[str]) -> bool:
    normalized_seed = normalize_match_text(seed)
    return any(title_matches_existing(normalized_seed, title) for title in existing_titles)


def count_public_posts_today(site_url: str) -> int:
    today = datetime.now(tz=KST).date()
    posts = parse_posts(fetch_public_feed(site_url))
    return sum(1 for post in posts if post["published_kst"].date() == today)


def build_published_item(single_result: dict, candidate: dict) -> dict:
    article_dir = Path(single_result["article_dir"])
    metadata = read_json(article_dir / "metadata.json")
    quality = read_json(article_dir / "quality_report.json")
    publish_result = read_json(Path(single_result["publish_result"]))
    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    return {
        "seed": single_result["seed"],
        "title": article.get("title", ""),
        "url": blogger.get("url", ""),
        "category": candidate.get("category", ""),
        "article_type": candidate.get("article_type", ""),
        "quality_score": quality.get("score"),
        "word_count": (quality.get("metrics") or {}).get("word_count"),
        "image_count": (quality.get("metrics") or {}).get("image_count"),
        "article_dir": single_result["article_dir"],
    }


def build_batch_result(site: str, max_posts: int, existing_today: int) -> dict:
    return {
        "site": site,
        "mode": "publish_batch",
        "max_posts": max_posts,
        "existing_today_count": existing_today,
        "published": [],
        "held": [],
        "skipped": [],
        "failed": [],
        "selected_candidates": [],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def recover_quality_failure(candidate: dict, exc: Exception, article_dir: Path | None = None) -> dict:
    classification = classify_recovery_issue(str(exc), article_dir)
    return {
        "seed": candidate.get("seed"),
        "article_type": candidate.get("article_type"),
        "category": candidate.get("category"),
        "reason": "quality_gate_failed",
        "recovery_status": classification["recovery_status"],
        "recovery_issue_type": classification["issue_type"],
        "error": str(exc),
        "article_dir": str(article_dir) if article_dir else "",
        "quality_issue_codes": classification["quality_issue_codes"],
        "attempts": classification["attempts"],
        "next_action": classification["next_action"],
    }


def classify_recovery_issue(error: str, article_dir: Path | None = None) -> dict:
    issue_codes = quality_issue_codes(article_dir)
    text = " ".join([error, " ".join(issue_codes)]).casefold()

    if any(token in text for token in [
        "required codex-generated image assets are missing",
        "ai image assets are missing for scene",
        "image assets are missing for scene",
        "generate fresh article-specific codex images",
        "generate fresh codex images",
        "reusable image library assets",
        "fresh article-specific images are required",
        "not svg fallback assets",
        "data:image",
        "general fallback",
        "image_plan",
        "missing_required_image_assets",
        "missing_images",
        "weak_image_plan",
        "weak_image_alt_text",
        "weak_image_caption",
        "unsafe_windows_image_label",
        "unsafe_windows_image_prompt",
        "reused_image_url",
        "svg",
    ]):
        return recovery_classification(
            "image_issue",
            "codex_image_required",
            issue_codes,
            "Codex에서 주제별 새 JPG 이미지를 생성해 hosted assets에 저장한 뒤 Hades 재검수를 실행하세요.",
            attempts=0,
        )
    if any(token in text for token in [
        "dead_microsoft",
        "weak_sources",
        "weak_microsoft_sources",
        "missing_microsoft_source",
        "shallow_microsoft_sources",
        "official_link",
        "research_report",
    ]):
        return recovery_classification(
            "source_issue",
            "candidate_replaced",
            issue_codes,
            "직접 공식/플랫폼 출처를 보강하고 Hades 재검수를 실행하세요. 자동 배치는 다음 후보로 보정 발행을 시도합니다.",
        )
    if any(token in text for token in [
        "duplicate",
        "near_duplicate",
        "title_pattern",
        "topic_overlap",
    ]):
        return recovery_classification(
            "duplicate_issue",
            "candidate_replaced",
            issue_codes,
            "중복 각도는 발행하지 말고 주간 큐의 다음 비중복 후보로 교체하세요.",
        )
    if any(token in text for token in [
        "topic_alignment",
        "intent",
        "category_mismatch",
    ]):
        return recovery_classification(
            "topic_issue",
            "candidate_replaced",
            issue_codes,
            "주제와 본문 각도를 맞추거나 다음 검색 의도 후보로 교체하세요.",
        )
    if any(token in text for token in [
        "oauth",
        "credentials",
        "unauthorized",
        "forbidden",
        "blogger",
        "api",
    ]):
        return recovery_classification(
            "auth_or_api_issue",
            "human_action_required",
            issue_codes,
            "Google/Blogger 인증과 API 응답을 확인해야 합니다. 약한 글로 대체하지 마세요.",
            attempts=0,
        )
    return recovery_classification(
        "content_issue",
        "candidate_replaced",
        issue_codes,
        "본문, FAQ, 내부 링크, 안전 경고를 보강하고 Hades 재검수를 실행하세요. 자동 배치는 다음 후보로 보정 발행을 시도합니다.",
    )


def recovery_classification(
    issue_type: str,
    status: str,
    issue_codes: list[str],
    next_action: str,
    attempts: int = MAX_RECOVERY_ATTEMPTS,
) -> dict:
    return {
        "issue_type": issue_type,
        "recovery_status": status,
        "quality_issue_codes": issue_codes,
        "attempts": attempts,
        "next_action": next_action,
    }


def quality_issue_codes(article_dir: Path | None) -> list[str]:
    if not article_dir:
        return []
    report_path = article_dir / "quality_report.json"
    if not report_path.exists():
        return []
    report = read_json(report_path)
    return [str(issue.get("code", "")) for issue in report.get("issues", []) if issue.get("code")]


def build_recovery_report(result: dict) -> dict:
    held = result.get("held") or []
    failed = result.get("failed") or []
    skipped = result.get("skipped") or []
    published = result.get("published") or []
    target = int(result.get("max_posts") or 0)
    existing_today = int(result.get("existing_today_count") or 0)
    public_total = existing_today + len(published)
    missing_count = max(0, target - public_total)
    issue_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for item in held:
        issue_type = item.get("recovery_issue_type") or "unknown"
        status = item.get("recovery_status") or "unknown"
        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1

    if missing_count == 0:
        status = "recovered" if held or failed or skipped else "not_needed"
    elif status_counts.get("codex_image_required"):
        status = "codex_image_required"
    elif failed:
        status = "recovery_failed"
    else:
        status = "partial_recovery" if published else "recovery_failed"

    return {
        "site": result.get("site"),
        "checked_at_kst": datetime.now(tz=KST).isoformat(),
        "target_posts": target,
        "existing_today_count": existing_today,
        "published_count": len(published),
        "public_total_after_batch": public_total,
        "missing_count": missing_count,
        "status": status,
        "issue_counts": issue_counts,
        "status_counts": status_counts,
        "published": published,
        "held": held,
        "skipped": skipped,
        "failed": failed,
        "attempted_candidates": result.get("selected_candidates") or [],
        "next_actions": recovery_next_actions(status, held, failed, missing_count),
    }


def recovery_next_actions(status: str, held: list[dict], failed: list[dict], missing_count: int) -> list[str]:
    if status in {"not_needed", "recovered"}:
        return ["오늘 목표 발행 수가 공개 피드 기준으로 충족됐습니다."]
    actions = []
    if missing_count:
        actions.append(f"아직 {missing_count}개 슬롯이 부족합니다. 약한 글을 발행하지 말고 복구 원인을 먼저 처리하세요.")
    if any(item.get("recovery_status") == "codex_image_required" for item in held):
        actions.append("Codex 이미지 복구 필요: 주제별 새 JPG 이미지를 생성하고 hosted assets에 저장한 뒤 재검수/보정 발행하세요.")
    if any(item.get("recovery_issue_type") == "source_issue" for item in held):
        actions.append("공식 출처 보강 필요: shortcut/dead/generic 링크를 직접 공식 문서 링크로 교체하세요.")
    if any(item.get("recovery_issue_type") == "content_issue" for item in held):
        actions.append("본문 보강 필요: 얇은 섹션, FAQ, 내부 링크, 안전 경고를 보강하세요.")
    if any(item.get("recovery_issue_type") == "auth_or_api_issue" for item in held) or failed:
        actions.append("인증/API 실패는 자동 대체 발행으로 해결하지 말고 Google/Blogger 권한과 workflow 로그를 확인하세요.")
    return actions


def save_recovery_report(report: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report['site']}-daily-recovery-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_batch_report(result: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result['site']}-daily-batch-success.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_post_publish_checks(site: str, published: list[dict]) -> dict:
    checks: dict = {"adsense_readiness": {}, "repurpose": []}
    try:
        from src.reporting.adsense_readiness import run as run_adsense_readiness

        readiness = run_adsense_readiness(site, notify=False)
        checks["adsense_readiness"] = {
            "status": readiness.get("status"),
            "status_label": readiness.get("status_label"),
            "posts_needing_fix_count": readiness.get("posts_needing_fix_count"),
        }
    except Exception as exc:
        checks["adsense_readiness"] = {"status": "error", "error": str(exc)}

    if not published:
        return checks
    try:
        from src.pipeline.stage6_repurpose_content import run as run_repurpose

        for item in published:
            url = item.get("url")
            if not url:
                continue
            manifest = run_repurpose(site, post_url=url)
            checks["repurpose"].append(
                {
                    "title": manifest.get("source_title"),
                    "url": manifest.get("source_url"),
                    "output_dir": manifest.get("output_dir"),
                }
            )
    except Exception as exc:
        checks["repurpose_error"] = str(exc)
    return checks


def notify_batch_completion(result: dict) -> None:
    settings = load_settings(result.get("site"))
    if is_scheduled_github_run():
        if settings.site_key == "korea_easy_guide":
            NotificationClient(settings).send_required(build_combined_morning_message())
        return
    NotificationClient(settings).send_required(build_batch_message(result))


def build_batch_message(result: dict) -> str:
    settings = load_settings(result.get("site"))
    lines = [
        "[Posting Bot] 일일 배치 포스팅 결과",
        "",
        f"- 블로그: {settings.site_name}",
        f"- 최대 목표: {result.get('max_posts')}개",
        f"- 기존 오늘 공개 글: {result.get('existing_today_count')}개",
        f"- 신규 발행: {len(result.get('published') or [])}개",
        f"- 보류: {len(result.get('held') or [])}개",
        f"- 중복 스킵: {len(result.get('skipped') or [])}개",
        f"- 실패: {len(result.get('failed') or [])}개",
        f"- 상태: {result.get('status', 'unknown')}",
    ]
    published = result.get("published") or []
    if published:
        lines.extend(["", "발행 목록:"])
        for index, item in enumerate(published, 1):
            lines.extend(
                [
                    f"{index}. {item.get('title')}",
                    f"- 타입/카테고리: {item.get('article_type')} / {item.get('category')}",
                    f"- 품질: {item.get('quality_score')}/100, 단어 {item.get('word_count')}, 이미지 {item.get('image_count')}",
                    f"- URL: {item.get('url')}",
                ]
            )
    held = result.get("held") or []
    if held:
        lines.extend(["", "보류 사유:"])
        for item in held[:5]:
            lines.append(f"- {item.get('seed')} / {item.get('reason')}")
    failed = result.get("failed") or []
    if failed:
        lines.extend(["", "실패 사유:"])
        for item in failed[:3]:
            lines.append(f"- {item.get('seed')}: {item.get('error')}")
    if not published:
        lines.extend(["", "메모:", "- 조건을 통과한 후보가 부족하면 3개를 억지로 채우지 않습니다."])
    return "\n".join(lines)


def is_scheduled_github_run() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true" and os.getenv("GITHUB_EVENT_NAME") == "schedule"


def build_combined_morning_message(now: datetime | None = None) -> str:
    selected_now = now or datetime.now(tz=KST)
    target_per_site = int(os.getenv("COMBINED_DAILY_TARGET_PER_SITE", "3"))
    site_keys = ["easy_pc_fix_guide", "korea_easy_guide"]
    site_results = [combined_site_result(site_key, target_per_site, now) for site_key in site_keys]
    total_published = sum(len(item.get("posts") or []) for item in site_results)
    total_target = target_per_site * len(site_results)
    recovery_summary = combined_recovery_summary(site_keys, selected_now)

    lines = [
        "[Posting Bot] 매일 아침 통합 포스팅 결과",
        "",
        f"- 전체 목표: {total_target}개",
        f"- 공개 확인: {total_published}개",
        f"- 복구: 성공 {recovery_summary['recovered']}개 / 이미지 필요 {recovery_summary['codex_image_required']}개 / 실패 {recovery_summary['failed']}개",
        f"- 상태: {'목표 달성' if total_published >= total_target else '목표 미달 또는 피드 반영 대기'}",
        "",
        "블로그별 결과:",
    ]
    for item in site_results:
        count = len(item.get("posts") or [])
        lines.extend(
            [
                "",
                f"[{item['site_name']}] {count}/{item['target']}개",
                f"- 사이트: {item['site_url']}",
                f"- 애드센스 준비: {readiness_line(item['site'])}",
                f"- 복구 상태: {recovery_line(item['site'], selected_now)}",
            ]
        )
        if item.get("error"):
            lines.append(f"- 확인 오류: {item['error']}")
            continue
        posts = item.get("posts") or []
        if not posts:
            lines.append("- 오늘 공개 피드에서 확인된 글 없음")
            continue
        for index, post in enumerate(posts, 1):
            lines.extend(
                [
                    f"{index}. {post.get('title')}",
                    f"   {post.get('url')}",
                ]
            )

    lines.extend(
        [
            "",
            "운영 규칙:",
            "- 중복 주제는 발행하지 않고 건너뜁니다.",
            "- 품질/공식출처/이미지 기준 미달 글은 3개를 억지로 채우지 않습니다.",
            "- Search Console 색인과 실제 검색 노출은 며칠 지연될 수 있습니다.",
        ]
    )
    return "\n".join(lines)


def combined_recovery_summary(site_keys: list[str], now: datetime | None = None) -> dict:
    summary = {"recovered": 0, "codex_image_required": 0, "failed": 0}
    for site_key in site_keys:
        report = read_recovery_report(site_key, now)
        status = report.get("status")
        if status == "recovered":
            summary["recovered"] += int(report.get("published_count") or 0)
        elif status == "codex_image_required":
            summary["codex_image_required"] += int(report.get("missing_count") or 1)
        elif status in {"recovery_failed", "partial_recovery"}:
            summary["failed"] += int(report.get("missing_count") or 1)
    return summary


def recovery_line(site: str, now: datetime | None = None) -> str:
    report = read_recovery_report(site, now)
    if not report:
        return "미점검"
    status = report.get("status", "unknown")
    missing = report.get("missing_count", 0)
    if status in {"not_needed", "recovered"}:
        return f"{status} / 부족 {missing}개"
    actions = report.get("next_actions") or []
    suffix = f" / {actions[0]}" if actions else ""
    return f"{status} / 부족 {missing}개{suffix}"


def read_recovery_report(site: str, now: datetime | None = None) -> dict:
    path = ROOT_DIR / "reports" / f"{site}-daily-recovery-report.json"
    if not path.exists():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unreadable"}
    if now is not None:
        checked_at = str(report.get("checked_at_kst") or "")
        try:
            checked_date = datetime.fromisoformat(checked_at).astimezone(KST).date()
        except (TypeError, ValueError):
            return {}
        selected_date = (now if now.tzinfo else now.replace(tzinfo=KST)).astimezone(KST).date()
        if checked_date != selected_date:
            return {}
    return report


def combined_site_result(site_key: str, target: int, now: datetime | None = None) -> dict:
    settings = load_settings(site_key)
    try:
        posts = today_public_posts(settings.site_url, now)
        return {
            "site": settings.site_key,
            "site_name": settings.site_name,
            "site_url": settings.site_url,
            "target": target,
            "posts": posts,
            "error": "",
        }
    except Exception as exc:
        return {
            "site": settings.site_key,
            "site_name": settings.site_name,
            "site_url": settings.site_url,
            "target": target,
            "posts": [],
            "error": str(exc),
        }


def readiness_line(site: str) -> str:
    path = ROOT_DIR / "reports" / f"{site}-adsense-readiness-report.json"
    if not path.exists():
        return "미점검"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "점검 리포트 읽기 실패"
    label = report.get("status_label") or report.get("status") or "unknown"
    needs_fix = report.get("posts_needing_fix_count", 0)
    return f"{label} / 보강 필요 {needs_fix}개"


def today_public_posts(site_url: str, now: datetime | None = None) -> list[dict]:
    selected_now = now or datetime.now(tz=KST)
    posts = parse_posts(fetch_public_feed(site_url))
    today = selected_now.date()
    return [post for post in posts if post["published_kst"].date() == today]


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the reviewed daily limit without filling weak slots.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--mode", choices=["publish"], default="publish")
    parser.add_argument("--max-posts", type=int, default=daily_publish_limit_from_env(os.getenv("DAILY_BATCH_MAX_POSTS"), quality_review_enabled=True))
    parser.add_argument("--seed", help="Optional explicit seed. Publishes at most one post.")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    result = run(args.site, args.mode, args.max_posts, args.seed, notify=not args.no_notify)
    write_github_publication_output(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
