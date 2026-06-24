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
from src.notifications.telegram import NotificationClient
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage2_publish import run as run_stage2
from src.quality.hades import HadesQualityGate


KST = ZoneInfo("Asia/Seoul")


def used_keywords(site: str | None = None) -> set[str]:
    settings = load_settings(site)
    values = set()
    for path in Path(settings.generated_output_dir).glob("*/*/metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate = metadata.get("candidate", {})
        keyword = candidate.get("keyword")
        if keyword:
            values.add(keyword.lower())
    return values


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


def run(seed: str | None = None, site: str | None = None, publish_mode: str = "draft") -> dict[str, str]:
    settings = load_settings(site)
    selected_seed = seed or ""
    try:
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
                    "daily_limit_skipped": True,
                    "existing_post": existing_today,
                }
                save_daily_success_report(result)
                notify_daily_completion(result)
                return result
        selected_seed = choose_seed(seed, site)
        skipped_duplicate_seeds: list[str] = []
        if publish_mode == "publish":
            selected_seed, article_dir, result_path, skipped_duplicate_seeds = run_publish_with_seed_fallback(seed, site)
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
        }
        save_daily_success_report(result)
        notify_daily_completion(result)
        return result
    except Exception as exc:
        save_daily_failure_report(selected_seed, exc, site, publish_mode)
        notify_daily_failure(selected_seed, exc, site)
        raise


def run_publish_with_seed_fallback(seed: str | None = None, site: str | None = None) -> tuple[str, Path, Path, list[str]]:
    skipped_duplicate_seeds: list[str] = []
    last_attempt: tuple[str, Path, Path] | None = None
    for candidate_seed in choose_publish_seed_candidates(seed, site):
        article_dir = run_stage1(candidate_seed, site)
        result_path = run_publish_with_duplicate_guard(article_dir, site)
        last_attempt = (candidate_seed, article_dir, result_path)
        if is_duplicate_publish_result(result_path):
            skipped_duplicate_seeds.append(candidate_seed)
            if seed:
                break
            continue
        return candidate_seed, article_dir, result_path, skipped_duplicate_seeds

    if last_attempt is None:
        raise ValueError("No topic seeds are available for publishing.")
    selected_seed, article_dir, result_path = last_attempt
    return selected_seed, article_dir, result_path, skipped_duplicate_seeds


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
    NotificationClient(settings).send(build_daily_success_message(result))


def notify_daily_failure(seed: str, exc: Exception, site: str | None = None) -> None:
    settings = load_settings(site)
    error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    NotificationClient(settings).send(
        "\n".join(
            [
                "[Posting Bot] 일일 포스팅 실패",
                "",
                f"- 블로그: {settings.site_name}",
                f"- 사이트: {settings.site_url}",
                f"- 주제 시드: {seed}",
                f"- 오류: {error}",
                "",
                "조치 필요:",
                "- 품질검수 실패면 글/이미지/출처를 보강해야 합니다.",
                "- Blogger 인증 실패면 OAuth 토큰을 갱신해야 합니다.",
                "- 이미지 누락이면 Codex 이미지 생성 후 다시 실행해야 합니다.",
            ]
        )
    )


def save_daily_failure_report(seed: str, exc: Exception, site: str | None = None, mode: str = "draft") -> Path:
    settings = load_settings(site)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-daily-failure.json"
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


def save_daily_success_report(result: dict[str, str]) -> Path:
    settings = load_settings(result.get("site"))
    article_dir_raw = result.get("article_dir", "")
    publish_result_raw = result.get("publish_result", "")
    metadata = read_json(Path(article_dir_raw) / "metadata.json") if article_dir_raw else {}
    publish_result = read_json(Path(publish_result_raw)) if publish_result_raw else {}
    quality_report = read_json(Path(article_dir_raw) / "quality_report.json") if article_dir_raw else {}
    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    existing_post = result.get("existing_post") or {}
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-daily-success.json"
    failure_path = output_dir / f"{settings.site_key}-daily-failure.json"
    payload = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "mode": result.get("mode", "draft"),
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
        "existing_post": existing_post,
        "daily_limit_skipped": result.get("daily_limit_skipped", False),
        "skipped_duplicate_seeds": result.get("skipped_duplicate_seeds") or [],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    remove_stale_report(failure_path)
    return output_path


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
    mode = result.get("mode", "draft")

    article = metadata.get("article", {})
    blogger = publish_result.get("blogger", {})
    existing_post = result.get("existing_post") or {}
    skipped = publish_result.get("skipped", False)
    draft = publish_result.get("draft", True)
    quality_score = quality_report.get("score", "n/a")
    quality_passed = quality_report.get("passed", False)
    quality_metrics = quality_report.get("metrics", {})
    issues = quality_report.get("issues", [])
    if mode == "validate":
        status = "검증 완료"
    elif result.get("daily_limit_skipped"):
        status = "오늘 공개 글 이미 있음, 추가 발행 건너뜀"
    elif skipped:
        status = "중복 공개 글 감지, 발행 건너뜀"
    else:
        status = "초안 업로드 완료" if draft else "공개 발행 완료"
    blogger_status = blogger.get("status") or "unknown"
    blogger_url = blogger.get("url") or existing_post.get("url") or "발행 없음"
    title = article.get("title", "") or existing_post.get("title", "제목 없음")

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
        f"- 품질점수: {quality_score}/100",
        f"- 품질통과: {'예' if quality_passed else '아니오'}",
        f"- 단어 수: {quality_metrics.get('word_count', 'n/a')}",
        f"- 이미지 수: {quality_metrics.get('image_count', 'n/a')}",
        f"- 공식 링크 수: {quality_metrics.get('official_link_count', 'n/a')}",
        f"- FAQ 수: {quality_metrics.get('faq_question_count', 'n/a')}",
        f"- URL: {blogger_url}",
        f"- 생성 폴더: {result.get('article_dir', '')}",
    ]
    skipped_duplicate_seeds = result.get("skipped_duplicate_seeds") or []
    if skipped_duplicate_seeds:
        lines.append(f"- 중복으로 건너뛴 시드 수: {len(skipped_duplicate_seeds)}")
        lines.append(f"- 중복 시드: {', '.join(skipped_duplicate_seeds[:5])}")

    if issues:
        lines.extend(["", "품질 이슈:"])
        for issue in issues[:5]:
            lines.append(f"- {issue.get('code')}: {issue.get('message')}")

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


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily pipeline: collect, generate, and upload a Blogger draft.")
    parser.add_argument("--seed", help="Optional explicit topic seed")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--mode", choices=["validate", "draft", "publish"], default="draft")
    args = parser.parse_args()
    result = run(args.seed, args.site, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
