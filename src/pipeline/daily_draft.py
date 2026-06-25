from __future__ import annotations

import argparse
from datetime import date
from datetime import datetime
import json
from pathlib import Path
import traceback
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.topic_scoring import infer_category
from src.notifications.telegram import NotificationClient
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage2_publish import run as run_stage2
from src.quality.action_guidance import quality_issue_actions
from src.quality.hades import HadesQualityGate
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import reddit_oauth_secret_label


KST = ZoneInfo("Asia/Seoul")
MAX_QUALITY_ATTEMPTS = 3


def used_keywords(site: str | None = None, include_validation: bool = True) -> set[str]:
    settings = load_settings(site)
    values = set()
    for path in Path(settings.generated_output_dir).glob("*/*/metadata.json"):
        if not include_validation and not has_publish_marker(path.parent):
            continue
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate = metadata.get("candidate", {})
        keyword = candidate.get("keyword")
        if keyword:
            values.add(keyword.lower())
    return values


def has_publish_marker(article_dir: Path) -> bool:
    return (article_dir / "blogger_publish_result.json").exists() or (article_dir / "duplicate_publish_result.json").exists()


def choose_seed(explicit_seed: str | None = None, site: str | None = None) -> str:
    settings = load_settings(site)
    if explicit_seed:
        return explicit_seed
    seeds = load_active_seed_list(site)
    if settings.app_env.lower() == "production":
        return choose_seed_for_date(seeds, settings.automation_start_date, date.today())
    used = used_keywords(site)
    for seed in seeds:
        if seed.lower() not in used:
            return seed
    return seeds[0]


def load_seed_list(site: str | None = None) -> list[str]:
    settings = load_settings(site)
    return load_seed_file(settings.seed_file)


def load_launch_seed_list(site: str | None = None) -> list[str]:
    settings = load_settings(site)
    if not settings.launch_seed_file:
        return []
    return load_seed_file(settings.launch_seed_file)


def load_active_seed_list(site: str | None = None) -> list[str]:
    settings = load_settings(site)
    seeds = load_seed_list(site)
    launch_seeds = load_launch_seed_list(site)
    if settings.app_env.lower() != "production" or not launch_seeds:
        return seeds
    days_since_start = days_since_automation_start(settings.automation_start_date, date.today())
    if days_since_start < len(launch_seeds):
        return launch_seeds
    return seeds


def load_active_seed_list_for_date(site: str | None, selected_date: date) -> tuple[list[str], str, int]:
    settings = load_settings(site)
    seeds = load_seed_list(site)
    launch_seeds = load_launch_seed_list(site)
    days_since_start = days_since_automation_start(settings.automation_start_date, selected_date)
    if settings.app_env.lower() == "production" and launch_seeds and days_since_start < len(launch_seeds):
        return launch_seeds, "launch_queue", days_since_start
    return seeds, "long_term", days_since_start


def load_seed_file(seed_file: str) -> list[str]:
    seed_path = Path(seed_file)
    if not seed_path.is_absolute():
        seed_path = ROOT_DIR / seed_path
    return json.loads(seed_path.read_text(encoding="utf-8"))


def choose_publish_seed_candidates(explicit_seed: str | None = None, site: str | None = None) -> list[str]:
    if explicit_seed:
        return [explicit_seed]
    settings = load_settings(site)
    seeds = load_active_seed_list(site)
    if settings.app_env.lower() == "production":
        first = choose_seed_for_date(seeds, settings.automation_start_date, date.today())
        first_index = seeds.index(first)
        return seeds[first_index:] + seeds[:first_index]
    selected = choose_seed(None, site)
    selected_index = seeds.index(selected)
    return seeds[selected_index:] + seeds[:selected_index]


def build_seed_plan(
    explicit_seed: str | None = None,
    site: str | None = None,
    now: datetime | None = None,
) -> dict:
    settings = load_settings(site)
    selected_date = (now or datetime.now(KST)).astimezone(KST).date()
    active_seeds, active_seed_source, days_since_start = load_active_seed_list_for_date(site, selected_date)
    if not active_seeds and not explicit_seed:
        raise ValueError("Seed file must contain at least one topic seed.")
    publish_used = used_keywords(site, include_validation=False)
    generated_used = used_keywords(site, include_validation=True)
    if explicit_seed:
        selected_seed = explicit_seed
        date_selected_seed = explicit_seed
        candidates = [explicit_seed]
        active_seed_source = "explicit"
    elif settings.app_env.lower() == "production":
        date_selected_seed = choose_seed_for_date(active_seeds, settings.automation_start_date, selected_date)
        selected_seed = date_selected_seed
        selected_index = active_seeds.index(selected_seed)
        candidates = active_seeds[selected_index:] + active_seeds[:selected_index]
    else:
        date_selected_seed = active_seeds[0]
        selected_seed = next((seed for seed in active_seeds if seed.lower() not in generated_used), active_seeds[0])
        selected_index = active_seeds.index(selected_seed)
        candidates = active_seeds[selected_index:] + active_seeds[:selected_index]

    candidate_preview = [
        {
            "seed": seed,
            "category": infer_category(seed, settings.content_domain),
            "already_published_or_duplicate": seed.lower() in publish_used,
            "already_generated_or_validated": seed.lower() in generated_used,
        }
        for seed in candidates[:10]
    ]
    unused_count = sum(1 for seed in active_seeds if seed.lower() not in generated_used)
    plan = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "mode": "plan",
        "app_env": settings.app_env,
        "content_domain": settings.content_domain,
        "today_kst": selected_date.isoformat(),
        "automation_start_date": settings.automation_start_date,
        "days_since_automation_start": days_since_start,
        "active_seed_source": active_seed_source,
        "active_seed_count": len(active_seeds),
        "main_seed_count": len(load_seed_list(site)),
        "launch_seed_count": len(load_launch_seed_list(site)),
        "date_selected_seed": date_selected_seed,
        "selected_seed": selected_seed,
        "candidate_count": len(candidates),
        "candidate_preview": candidate_preview,
        "used_publish_seed_count": len(publish_used),
        "used_generated_seed_count": len(generated_used),
        "unused_active_seed_count": unused_count,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if active_seed_source == "launch_queue":
        plan["note"] = "Launch queue is still active; long-term seeds will resume after the launch queue window."
    elif unused_count == 0 and not explicit_seed:
        plan["note"] = "All active seeds already have generated artifacts; production mode can still rotate by date."
    else:
        plan["note"] = "Seed plan is ready."
    return plan


def choose_seed_for_date(seeds: list[str], start_date: str, today: date) -> str:
    if not seeds:
        raise ValueError("Seed file must contain at least one topic seed.")
    index = days_since_automation_start(start_date, today) % len(seeds)
    return seeds[index]


def days_since_automation_start(start_date: str, today: date) -> int:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        start = today
    return max(0, (today - start).days)


def run(
    seed: str | None = None,
    site: str | None = None,
    publish_mode: str = "draft",
    notify: bool = True,
) -> dict[str, str]:
    settings = load_settings(site)
    selected_seed = seed or ""
    try:
        if publish_mode == "plan":
            seed_plan = build_seed_plan(seed, site)
            result_path = save_seed_plan_report(seed_plan)
            result = {
                "seed": seed_plan.get("selected_seed", ""),
                "article_dir": "",
                "publish_result": str(result_path),
                "site": settings.site_key,
                "mode": publish_mode,
                "status": "planned",
                "candidate_count": seed_plan.get("candidate_count", 0),
                "active_seed_source": seed_plan.get("active_seed_source", ""),
            }
            if notify:
                notify_seed_plan(seed_plan, site)
            return result
        if publish_mode == "publish" and seed is None:
            existing_today = find_public_post_published_today(settings.site_url)
            if existing_today:
                result = {
                    "seed": "",
                    "article_dir": "",
                    "publish_result": "",
                    "site": settings.site_key,
                    "mode": publish_mode,
                    "skipped_duplicate_seeds": [],
                    "skipped_quality_seeds": [],
                    "daily_limit_skipped": True,
                    "existing_post": existing_today,
                }
                save_daily_success_report(result)
                if notify:
                    notify_daily_completion(result)
                return result
        selected_seed = choose_seed(seed, site)
        skipped_duplicate_seeds: list[str] = []
        skipped_quality_seeds: list[str] = []
        if publish_mode == "publish":
            selected_seed, article_dir, result_path, skipped_duplicate_seeds, skipped_quality_seeds = (
                run_publish_with_seed_fallback(seed, site)
            )
        else:
            article_dir = run_stage1(selected_seed, site)
            if publish_mode == "validate":
                result_path = run_validation(article_dir, site)
            else:
                result_path = run_stage2(article_dir=article_dir, mode=publish_mode, site=site)
        result = {
            "seed": selected_seed,
            "article_dir": str(article_dir),
            "publish_result": str(result_path),
            "site": load_settings(site).site_key,
            "mode": publish_mode,
            "skipped_duplicate_seeds": skipped_duplicate_seeds,
            "skipped_quality_seeds": skipped_quality_seeds,
        }
        save_daily_success_report(result)
        if notify:
            notify_daily_completion(result)
        return result
    except Exception as exc:
        save_daily_failure_report(selected_seed, exc, site, publish_mode)
        if notify:
            notify_daily_failure(selected_seed, exc, site, publish_mode)
        raise


def run_publish_with_seed_fallback(
    seed: str | None = None, site: str | None = None
) -> tuple[str, Path, Path, list[str], list[str]]:
    skipped_duplicate_seeds: list[str] = []
    skipped_quality_seeds: list[str] = []
    last_attempt: tuple[str, Path, Path] | None = None
    last_quality_error: Exception | None = None
    for candidate_seed in choose_publish_seed_candidates(seed, site):
        article_dir = run_stage1(candidate_seed, site)
        try:
            result_path = run_publish_with_duplicate_guard(article_dir, site)
        except Exception as exc:
            if seed or not is_quality_gate_failure(exc) or len(skipped_quality_seeds) >= MAX_QUALITY_ATTEMPTS - 1:
                raise
            skipped_quality_seeds.append(candidate_seed)
            last_quality_error = exc
            continue
        last_attempt = (candidate_seed, article_dir, result_path)
        if is_duplicate_publish_result(result_path):
            skipped_duplicate_seeds.append(candidate_seed)
            if seed:
                break
            continue
        return candidate_seed, article_dir, result_path, skipped_duplicate_seeds, skipped_quality_seeds

    if last_attempt is None:
        if last_quality_error:
            raise last_quality_error
        raise ValueError("No topic seeds are available for publishing.")
    selected_seed, article_dir, result_path = last_attempt
    return selected_seed, article_dir, result_path, skipped_duplicate_seeds, skipped_quality_seeds


def is_quality_gate_failure(exc: Exception) -> bool:
    message = str(exc)
    return (
        isinstance(exc, (ValueError, FileNotFoundError))
        and (
            "Hades quality gate failed" in message
            or "Hades validation failed" in message
            or "image_plan.json is required" in message
            or "Required Codex-generated image assets are missing" in message
            or "At least two required image assets" in message
        )
    )


def is_duplicate_publish_result(result_path: Path) -> bool:
    result = read_json(result_path)
    return result.get("skipped") is True and result.get("blogger", {}).get("status") == "SKIPPED_DUPLICATE"


def run_validation(article_dir: Path, site: str | None = None) -> Path:
    settings = load_settings(site)
    report = HadesQualityGate(settings.content_domain).review_article_dir(article_dir)
    report_path = article_dir / "quality_report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    result_path = article_dir / "validation_result.json"
    result_path.write_text(
        json.dumps(
            {
                "mode": "validate",
                "published": False,
                "passed": report.passed,
                "score": report.score,
                "min_score": report.min_score,
                "issues": [issue.__dict__ for issue in report.issues],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not report.passed:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"Hades validation failed with score {report.score}/{report.min_score}: {issues}")
    return result_path


def run_publish_with_duplicate_guard(article_dir: Path, site: str | None = None) -> Path:
    settings = load_settings(site)
    metadata = read_json(article_dir / "metadata.json")
    article = metadata.get("article", {})
    slug = article.get("slug", "")
    title = article.get("title", "")
    duplicate = find_public_post(settings.site_url, slug, title) if slug or title else None
    if duplicate:
        result_path = article_dir / "duplicate_publish_result.json"
        result_path.write_text(
            json.dumps(
                {
                    "draft": False,
                    "skipped": True,
                    "reason": "duplicate_public_post",
                    "blogger": {
                        "id": None,
                        "url": duplicate.get("url"),
                        "selfLink": None,
                        "status": "SKIPPED_DUPLICATE",
                        "published": duplicate.get("published_kst"),
                        "updated": None,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        validate_existing_article(article_dir, site)
        return result_path
    return run_stage2(article_dir=article_dir, mode="publish", site=site)


def validate_existing_article(article_dir: Path, site: str | None = None) -> None:
    settings = load_settings(site)
    report = HadesQualityGate(settings.content_domain).review_article_dir(article_dir)
    (article_dir / "quality_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_public_post(site_url: str, slug: str = "", title: str = "") -> dict | None:
    posts = parse_posts(fetch_public_feed(site_url))
    normalized_title = normalize_match_text(title)
    for post in posts:
        if normalized_title and normalize_match_text(post.get("title", "")) == normalized_title:
            return duplicate_post_payload(post)
        if slug and public_url_matches_slug(post.get("url", ""), slug):
            return duplicate_post_payload(post)
    return None


def find_public_post_published_today(site_url: str, now: datetime | None = None) -> dict | None:
    selected_now = now or datetime.now(tz=KST)
    posts = parse_posts(fetch_public_feed(site_url))
    for post in posts:
        if post["published_kst"].date() == selected_now.date():
            return duplicate_post_payload(post)
    return None


def public_url_matches_slug(url: str, slug: str) -> bool:
    public_slug = Path(url.split("?", 1)[0]).stem
    if not public_slug:
        return False
    return public_slug == slug or slug.startswith(f"{public_slug}-")


def duplicate_post_payload(post: dict) -> dict:
    published = post.get("published_kst")
    return {
        "title": post.get("title"),
        "url": post.get("url"),
        "published_kst": published.isoformat() if published else "",
    }


def normalize_match_text(value: str) -> str:
    return " ".join(value.casefold().split())


def notify_daily_completion(result: dict[str, str]) -> None:
    settings = load_settings(result.get("site"))
    NotificationClient(settings).send_required(build_daily_success_message(result))


def notify_daily_failure(seed: str, exc: Exception, site: str | None = None, mode: str = "draft") -> None:
    settings = load_settings(site)
    NotificationClient(settings).send_required(build_daily_failure_message(seed, exc, site, mode))


def notify_seed_plan(seed_plan: dict, site: str | None = None) -> None:
    settings = load_settings(site)
    NotificationClient(settings).send_required(build_seed_plan_message(seed_plan))


def build_seed_plan_message(seed_plan: dict) -> str:
    preview = seed_plan.get("candidate_preview") or []
    preview_lines = []
    for index, item in enumerate(preview[:5], 1):
        flags = []
        if item.get("already_published_or_duplicate"):
            flags.append("공개/중복 이력 있음")
        if item.get("already_generated_or_validated"):
            flags.append("생성/검증 이력 있음")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        preview_lines.append(f"- {index}. {item.get('seed')} / {item.get('category')}{flag_text}")
    if not preview_lines:
        preview_lines.append("- 후보 없음")
    return "\n".join(
        [
            "[Posting Bot] 일일 포스팅 시드 계획",
            "",
            f"- 블로그: {seed_plan.get('site_name')}",
            f"- 사이트: {seed_plan.get('site_url')}",
            f"- 기준일: {seed_plan.get('today_kst')} KST",
            f"- 실행환경: {seed_plan.get('app_env')}",
            f"- 시드 소스: {seed_plan.get('active_seed_source')}",
            f"- 오늘 선택 시드: {seed_plan.get('selected_seed')}",
            f"- 후보 수: {seed_plan.get('candidate_count')}",
            f"- 미사용 활성 시드 수: {seed_plan.get('unused_active_seed_count')}",
            f"- 메모: {seed_plan.get('note')}",
            "",
            "후보 미리보기:",
            *preview_lines,
        ]
    )


def build_daily_failure_message(seed: str, exc: Exception, site: str | None = None, mode: str = "draft") -> str:
    settings = load_settings(site)
    error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    action_items = daily_failure_action_items(error, mode, settings.site_key)
    report_path = ROOT_DIR / "reports" / daily_failure_report_name(settings.site_key, mode)
    return "\n".join(
        [
            "[Posting Bot] 일일 포스팅 실패",
            "",
            f"- 블로그: {settings.site_name}",
            f"- 사이트: {settings.site_url}",
            f"- 주제 시드: {seed}",
            f"- 오류 유형: {type(exc).__name__}",
            f"- 오류: {error}",
            f"- 실패 리포트: {report_path}",
            "",
            "우선 조치:",
            *[f"- {item}" for item in action_items],
            "",
            "재실행:",
            "- GitHub Actions > Easy PC Fix Validate Smoke Test에서 같은 seed로 검증 실행",
            "- 검증 통과 후 Easy PC Fix Daily Publish를 수동 실행",
        ]
    )


def daily_failure_action_items(error: str, mode: str = "draft", site_key: str = "easy_pc_fix_guide") -> list[str]:
    error_lower = error.casefold()
    if "hades quality gate failed" in error_lower or "quality" in error_lower:
        return [
            "Hades 품질검수 실패입니다. quality_report.json의 issue code를 먼저 확인하세요.",
            "공식 Microsoft 출처, 이미지 계획, 안전 경고, 명령어 경고, 본문 길이를 보강하세요.",
        ]
    if "oauth" in error_lower or "credentials" in error_lower or "unauthorized" in error_lower:
        return [
            "인증 문제 가능성이 큽니다. Google OAuth 토큰과 GitHub Secrets 값을 확인하세요.",
            "Blogger, Search Console, Analytics 권한이 같은 Google 계정에 연결되어 있는지 확인하세요.",
        ]
    if "image" in error_lower or "asset" in error_lower:
        return [
            "이미지 또는 image_plan 문제입니다. assets 폴더와 image_plan.json의 required 파일명을 확인하세요.",
            "유료 이미지 API 없이 local SVG fallback 또는 Codex 생성 이미지가 들어갔는지 확인하세요.",
        ]
    if "duplicate" in error_lower:
        return [
            "중복 글 감지입니다. 같은 주제가 이미 공개됐는지 Blogger 공개 피드를 확인하세요.",
            "topic seed 목록에서 사용된 시드를 제거하거나 더 구체적인 새 오류 주제로 바꾸세요.",
        ]
    if "reddit" in error_lower:
        return [
            "Reddit 수집 문제입니다. Reddit OAuth Health workflow와 research_report.json의 수집 진단을 확인하세요.",
            "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET 설정 여부를 확인하세요.",
        ]
    return [
        f"reports 폴더의 {daily_failure_report_name(site_key, mode)} traceback을 확인하세요.",
        "같은 seed로 validate mode를 먼저 재실행해 발행 전 단계에서 원인을 좁히세요.",
    ]


def save_daily_failure_report(seed: str, exc: Exception, site: str | None = None, mode: str = "draft") -> Path:
    settings = load_settings(site)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / daily_failure_report_name(settings.site_key, mode)
    payload = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "mode": mode,
        "seed": seed,
        "status": "failed",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def save_seed_plan_report(seed_plan: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{seed_plan['site']}-daily-seed-plan.json"
    output_path.write_text(json.dumps(seed_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def save_daily_success_report(result: dict[str, str]) -> Path:
    settings = load_settings(result.get("site"))
    mode = result.get("mode", "draft")
    article_dir_raw = result.get("article_dir", "")
    publish_result_raw = result.get("publish_result", "")
    metadata = read_json(Path(article_dir_raw) / "metadata.json") if article_dir_raw else {}
    publish_result = read_json(Path(publish_result_raw)) if publish_result_raw else {}
    quality_report = read_json(Path(article_dir_raw) / "quality_report.json") if article_dir_raw else {}
    research_report = read_json(Path(article_dir_raw) / "research_report.json") if article_dir_raw else {}
    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    existing_post = result.get("existing_post") or {}
    if result.get("daily_limit_skipped"):
        reddit_signal_quality = {}
        google_signal_quality = {}
        operational_status = build_daily_limit_operational_status()
    else:
        reddit_signal_quality = build_reddit_signal_quality(research_report)
        google_signal_quality = build_google_signal_quality(research_report)
        operational_status = build_operational_status(quality_report, reddit_signal_quality)
    seed_attempt_summary = build_seed_attempt_summary(result)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / daily_success_report_name(settings.site_key, mode)
    failure_path = output_dir / daily_failure_report_name(settings.site_key, mode)
    payload = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "mode": mode,
        "status": daily_result_status(result, publish_result),
        "seed": result.get("seed", ""),
        "article_dir": result.get("article_dir", ""),
        "publish_result": result.get("publish_result", ""),
        "title": article.get("title", "") or existing_post.get("title", ""),
        "category": article.get("category", ""),
        "blogger_status": blogger.get("status", ""),
        "url": blogger.get("url", "") or existing_post.get("url", ""),
        "quality_score": quality_report.get("score"),
        "quality_passed": quality_report.get("passed"),
        "quality_metrics": quality_report.get("metrics", {}),
        "reddit_signal_quality": reddit_signal_quality,
        "google_signal_quality": google_signal_quality,
        "operational_status": operational_status,
        "seed_attempt_summary": seed_attempt_summary,
        "existing_post": existing_post,
        "daily_limit_skipped": result.get("daily_limit_skipped", False),
        "skipped_duplicate_seeds": result.get("skipped_duplicate_seeds") or [],
        "skipped_quality_seeds": result.get("skipped_quality_seeds") or [],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    remove_stale_report(failure_path)
    return output_path


def daily_success_report_name(site_key: str, mode: str) -> str:
    if mode == "validate":
        return f"{site_key}-daily-validation-success.json"
    return f"{site_key}-daily-success.json"


def daily_failure_report_name(site_key: str, mode: str) -> str:
    if mode == "validate":
        return f"{site_key}-daily-validation-failure.json"
    return f"{site_key}-daily-failure.json"


def remove_stale_report(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def daily_result_status(result: dict, publish_result: dict) -> str:
    mode = result.get("mode", "draft")
    if result.get("daily_limit_skipped"):
        return "skipped_daily_limit"
    if mode == "validate":
        return "validated"
    if publish_result.get("skipped"):
        return "skipped_duplicate"
    if publish_result.get("draft", True):
        return "draft_uploaded"
    return "published"


def build_daily_success_message(result: dict[str, str]) -> str:
    settings = load_settings(result.get("site"))
    article_dir_raw = result.get("article_dir", "")
    publish_result_raw = result.get("publish_result", "")
    metadata = read_json(Path(article_dir_raw) / "metadata.json") if article_dir_raw else {}
    publish_result = read_json(Path(publish_result_raw)) if publish_result_raw else {}
    quality_report = read_json(Path(article_dir_raw) / "quality_report.json") if article_dir_raw else {}
    research_report = read_json(Path(article_dir_raw) / "research_report.json") if article_dir_raw else {}
    mode = result.get("mode", "draft")

    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    existing_post = result.get("existing_post") or {}
    skipped = publish_result.get("skipped", False)
    draft = publish_result.get("draft", True)
    daily_limit_skipped = bool(result.get("daily_limit_skipped"))
    quality_score = quality_report.get("score", "n/a")
    quality_passed = quality_report.get("passed", False)
    quality_metrics = quality_report.get("metrics", {})
    issues = quality_report.get("issues", [])
    if daily_limit_skipped:
        reddit_signal_quality = {}
        google_signal_quality = {}
        operational_status = build_daily_limit_operational_status()
    else:
        reddit_signal_quality = build_reddit_signal_quality(research_report)
        google_signal_quality = build_google_signal_quality(research_report)
        operational_status = build_operational_status(quality_report, reddit_signal_quality)
    if mode == "validate":
        status = "검증 완료"
    elif daily_limit_skipped:
        status = "오늘 공개 글 이미 있음, 추가 발행 건너뜀"
    elif skipped:
        status = "중복 공개 글 감지, 발행 건너뜀"
    else:
        status = "초안 업로드 완료" if draft else "공개 발행 완료"
    blogger_status = "existing_public_post" if daily_limit_skipped else blogger.get("status") or "unknown"
    blogger_url = blogger.get("url") or existing_post.get("url") or "발행 없음"
    title = article.get("title", "") or existing_post.get("title", "제목 없음")
    seed_attempt_summary = build_seed_attempt_summary(result)
    if daily_limit_skipped:
        quality_lines = [
            f"- 기존 공개 시각: {existing_post.get('published_kst', '') or '확인 필요'}",
            "- 품질검수: 오늘 이미 공개된 글이 있어 새 글 생성/검수 없음",
            "- 수집 상태: 새 수집 없음",
            f"- 운영 상태: {operational_status.get('status_label')}",
            f"- 발행 품질 안정성: {'안정' if operational_status.get('publish_quality_ok') else '점검 필요'}",
            f"- 수집 안정성: {operational_status.get('collection_status_label')}",
        ]
    else:
        quality_lines = [
            f"- 품질점수: {quality_score}/100",
            f"- 품질통과: {'예' if quality_passed else '아니오'}",
            f"- 단어 수: {quality_metrics.get('word_count', 'n/a')}",
            f"- 이미지 수: {quality_metrics.get('image_count', 'n/a')}",
            f"- 공식 링크 수: {quality_metrics.get('official_link_count', 'n/a')}",
            f"- FAQ 수: {quality_metrics.get('faq_question_count', 'n/a')}",
            f"- Reddit 실제 신호 수: {reddit_signal_quality.get('live_reddit_signal_count', 0)}",
            f"- Reddit OAuth 신호 수: {reddit_signal_quality.get('reddit_oauth_signal_count', 0)}",
            f"- Reddit public JSON 신호 수: {reddit_signal_quality.get('reddit_public_json_signal_count', 0)}",
            f"- Reddit fallback 신호 수: {reddit_signal_quality.get('fallback_reddit_signal_count', 0)}",
            f"- Google Suggest 신호 수: {google_signal_quality.get('google_suggest_signal_count', 0)}",
            f"- Google Suggest live 신호 수: {google_signal_quality.get('google_suggest_live_signal_count', 0)}",
            f"- Google Suggest fallback 신호 수: {google_signal_quality.get('google_suggest_fallback_signal_count', 0)}",
            f"- 운영 상태: {operational_status.get('status_label')}",
            f"- 발행 품질 안정성: {'안정' if operational_status.get('publish_quality_ok') else '점검 필요'}",
            f"- 수집 안정성: {operational_status.get('collection_status_label')}",
        ]

    lines = [
        "[Posting Bot] 매일 아침 포스팅 결과 보고",
        "",
        f"- 블로그: {settings.site_name}",
        f"- 사이트: {settings.site_url}",
        f"- 실행모드: {mode}",
        f"- 상태: {status}",
        f"- Blogger 상태: {blogger_status}",
        f"- 제목: {title}",
        f"- 카테고리: {article.get('category', '미분류')}",
        f"- 주제 시드: {result.get('seed', '')}",
        f"- 시드 시도 수: {seed_attempt_summary.get('attempted_seed_count', 0)}",
        f"- 최종 선택 시드: {seed_attempt_summary.get('selected_seed') or '없음'}",
        f"- 중복 스킵 수: {seed_attempt_summary.get('duplicate_skip_count', 0)}",
        f"- 품질 재시도 수: {seed_attempt_summary.get('quality_retry_count', 0)}",
        *quality_lines,
        f"- URL: {blogger_url}",
        f"- 생성 폴더: {result.get('article_dir', '')}",
    ]
    reddit_warning = reddit_signal_quality.get("warning")
    google_warning = google_signal_quality.get("warning")
    if reddit_warning or google_warning:
        lines.extend(["", "수집 품질 경고:"])
    if reddit_warning:
        lines.append(f"- {reddit_warning}")
        reddit_diagnostics = build_reddit_diagnostics_summary(research_report)
        if reddit_diagnostics:
            lines.extend(reddit_diagnostics)
        lines.extend(
            [
                f"- Reddit 앱 생성: {REDDIT_APPS_URL}",
                f"- GitHub Secrets에 {reddit_oauth_secret_label()} 저장: {GITHUB_SECRETS_URL}",
                "- 저장 후 Actions > Easy PC Fix Reddit OAuth Health를 수동 실행하세요.",
            ]
        )
    if google_warning:
        lines.append(f"- {google_warning}")
        google_diagnostics = build_google_diagnostics_summary(research_report)
        if google_diagnostics:
            lines.extend(google_diagnostics)
    skipped_duplicate_seeds = result.get("skipped_duplicate_seeds") or []
    if skipped_duplicate_seeds:
        lines.append(f"- 중복으로 건너뛴 시드 수: {len(skipped_duplicate_seeds)}")
        lines.append(f"- 중복 시드: {', '.join(skipped_duplicate_seeds[:5])}")
    skipped_quality_seeds = result.get("skipped_quality_seeds") or []
    if skipped_quality_seeds:
        lines.append(f"- 품질검수 실패로 재시도한 시드 수: {len(skipped_quality_seeds)}")
        lines.append(f"- 품질 재시도 시드: {', '.join(skipped_quality_seeds[:5])}")

    if issues:
        lines.extend(["", "품질 이슈:"])
        for issue in issues[:5]:
            lines.append(f"- {issue.get('code')}: {issue.get('message')}")
        issue_actions = quality_issue_actions(issues)
        if issue_actions:
            lines.extend(["", "품질 조치:"])
            lines.extend(f"- {action}" for action in issue_actions)

    if result.get("daily_limit_skipped"):
        lines.extend(
            [
                "",
                "운영 메모:",
                "- 하루 1개 발행 원칙에 따라 오늘 추가 발행을 중단했습니다.",
                "- 내일 09:10 KST 자동 발행은 정상 대기합니다.",
            ]
        )

    lines.extend(
        [
            "",
            "다음 확인:",
            "- 검증 모드면 Blogger에는 글이 생성되지 않습니다.",
            "- 공개 발행 전이면 이미지/링크/본문 품질을 최종 확인하세요.",
            "- 공개 발행 후에는 Search Console 색인 요청과 Analytics 수집 여부를 확인하세요.",
        ]
    )
    return "\n".join(lines)


def build_seed_attempt_summary(result: dict) -> dict:
    if result.get("daily_limit_skipped"):
        return {
            "attempted_seed_count": 0,
            "selected_seed": "",
            "duplicate_skip_count": 0,
            "quality_retry_count": 0,
            "attempted_seeds": [],
            "skipped_duplicate_seeds": [],
            "skipped_quality_seeds": [],
        }

    skipped_duplicate_seeds = list(result.get("skipped_duplicate_seeds") or [])
    skipped_quality_seeds = list(result.get("skipped_quality_seeds") or [])
    selected_seed = result.get("seed", "")
    attempted_seeds = []
    for seed in [*skipped_quality_seeds, *skipped_duplicate_seeds, selected_seed]:
        if seed and seed not in attempted_seeds:
            attempted_seeds.append(seed)
    return {
        "attempted_seed_count": len(attempted_seeds),
        "selected_seed": selected_seed,
        "duplicate_skip_count": len(skipped_duplicate_seeds),
        "quality_retry_count": len(skipped_quality_seeds),
        "attempted_seeds": attempted_seeds,
        "skipped_duplicate_seeds": skipped_duplicate_seeds,
        "skipped_quality_seeds": skipped_quality_seeds,
    }


def build_reddit_diagnostics_summary(research_report: dict) -> list[str]:
    diagnostics = research_report.get("reddit_collection_diagnostics") or {}
    if not diagnostics:
        return []
    lines = []
    status = diagnostics.get("status")
    if status:
        lines.append(f"- Reddit 수집 진단 상태: {status}")
    if diagnostics.get("public_json_skipped"):
        lines.append("- Reddit public JSON 스킵: 예")
        if diagnostics.get("public_json_skip_reason"):
            lines.append(f"- Reddit public JSON 스킵 이유: {diagnostics.get('public_json_skip_reason')}")
    public_json_error_count = int(diagnostics.get("public_json_error_count", 0) or 0)
    if public_json_error_count:
        lines.append(f"- Reddit public JSON 실패 수: {public_json_error_count}")
    failed_subreddits = [
        item.get("subreddit", "")
        for item in diagnostics.get("public_json_failed_subreddits", [])
        if item.get("subreddit")
    ]
    if failed_subreddits:
        lines.append(f"- 실패 subreddit: {', '.join(failed_subreddits[:6])}")
    if diagnostics.get("fallback_reason"):
        lines.append(f"- fallback 이유: {diagnostics.get('fallback_reason')}")
    if diagnostics.get("oauth_error"):
        lines.append(f"- Reddit OAuth 오류: {diagnostics.get('oauth_error')}")
    return lines


def build_reddit_signal_quality(research_report: dict) -> dict:
    live_count = int(research_report.get("live_reddit_signal_count", 0) or 0)
    oauth_count = int(research_report.get("reddit_oauth_signal_count", 0) or 0)
    public_json_count = int(research_report.get("reddit_public_json_signal_count", 0) or 0)
    fallback_count = int(research_report.get("fallback_reddit_signal_count", 0) or 0)
    method_counts = research_report.get("reddit_collection_method_counts", {}) or {}
    warning = ""
    if fallback_count and not live_count:
        warning = "Reddit 실제 신호 없이 fallback 질문만 사용했습니다. Reddit OAuth 설정을 점검하세요."
    elif public_json_count and not oauth_count:
        warning = "Reddit 실제 신호가 public JSON 경로에만 의존합니다. 403 차단 가능성을 줄이려면 Reddit OAuth 수집을 점검하세요."
    return {
        "live_reddit_signal_count": live_count,
        "reddit_oauth_signal_count": oauth_count,
        "reddit_public_json_signal_count": public_json_count,
        "fallback_reddit_signal_count": fallback_count,
        "reddit_collection_method_counts": method_counts,
        "warning": warning,
    }


def build_google_diagnostics_summary(research_report: dict) -> list[str]:
    diagnostics = research_report.get("google_suggest_diagnostics") or {}
    if not diagnostics:
        return []
    lines = []
    status = diagnostics.get("status")
    if status:
        lines.append(f"- Google Suggest 수집 진단 상태: {status}")
    lines.append(f"- Google Suggest live 제안 수: {int(diagnostics.get('live_suggestion_count', 0) or 0)}")
    lines.append(f"- Google Suggest fallback 제안 수: {int(diagnostics.get('fallback_suggestion_count', 0) or 0)}")
    if diagnostics.get("fallback_reason"):
        lines.append(f"- Google Suggest fallback 이유: {diagnostics.get('fallback_reason')}")
    if diagnostics.get("error"):
        lines.append(f"- Google Suggest 오류: {diagnostics.get('error')}")
    return lines


def build_google_signal_quality(research_report: dict) -> dict:
    total_count = int(research_report.get("google_suggest_signal_count", 0) or 0)
    live_count = int(research_report.get("google_suggest_live_signal_count", 0) or 0)
    fallback_count = int(research_report.get("google_suggest_fallback_signal_count", 0) or 0)
    method_counts = research_report.get("google_suggest_method_counts", {}) or {}
    warning = ""
    if fallback_count and not live_count:
        warning = "Google Suggest live 신호 없이 fallback 검색 의도만 사용했습니다. 네트워크 또는 Google Suggest 응답 상태를 확인하세요."
    elif not total_count:
        warning = "Google Suggest 신호가 없습니다. 글 주제 확장 신호가 부족할 수 있습니다."
    return {
        "google_suggest_signal_count": total_count,
        "google_suggest_live_signal_count": live_count,
        "google_suggest_fallback_signal_count": fallback_count,
        "google_suggest_method_counts": method_counts,
        "warning": warning,
    }


def build_operational_status(quality_report: dict, reddit_signal_quality: dict) -> dict:
    score = int(quality_report.get("score") or 0)
    passed = bool(quality_report.get("passed"))
    issues = quality_report.get("issues") or []
    publish_quality_ok = passed and score >= 90 and not issues
    if reddit_signal_quality.get("reddit_oauth_signal_count", 0) > 0:
        collection_status = "stable_oauth"
        collection_label = "안정: Reddit OAuth 신호 사용"
    elif reddit_signal_quality.get("reddit_public_json_signal_count", 0) > 0:
        collection_status = "public_json_only"
        collection_label = "주의: Reddit public JSON 의존"
    elif reddit_signal_quality.get("fallback_reddit_signal_count", 0) > 0:
        collection_status = "fallback_only"
        collection_label = "주의: fallback 질문 의존"
    else:
        collection_status = "no_reddit_signals"
        collection_label = "주의: Reddit 신호 없음"
    ready_for_cadence_increase = publish_quality_ok and collection_status == "stable_oauth"
    if publish_quality_ok and ready_for_cadence_increase:
        status_label = "품질/수집 안정"
    elif publish_quality_ok:
        status_label = "발행 품질 OK, 수집 안정성 점검 필요"
    else:
        status_label = "품질 점검 필요"
    return {
        "publish_quality_ok": publish_quality_ok,
        "collection_status": collection_status,
        "collection_status_label": collection_label,
        "ready_for_cadence_increase": ready_for_cadence_increase,
        "status_label": status_label,
    }


def build_daily_limit_operational_status() -> dict:
    return {
        "publish_quality_ok": True,
        "collection_status": "not_run_daily_limit",
        "collection_status_label": "정상: 하루 1개 제한으로 새 수집 없음",
        "ready_for_cadence_increase": False,
        "status_label": "오늘 공개 글 확인, 추가 발행 정상 스킵",
    }


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily pipeline: collect, generate, and upload a Blogger draft.")
    parser.add_argument("--seed", help="Optional explicit topic seed")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--mode", choices=["plan", "validate", "draft", "publish"], default="draft")
    parser.add_argument("--no-notify", action="store_true", help="Skip Posting Bot notifications for local smoke checks.")
    args = parser.parse_args()
    result = run(args.seed, args.site, args.mode, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
