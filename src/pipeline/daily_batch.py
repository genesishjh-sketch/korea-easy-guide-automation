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
from src.pipeline.daily_draft import read_json
from src.pipeline.daily_draft import run_publish_with_duplicate_guard
from src.pipeline.daily_draft import save_daily_failure_report
from src.pipeline.daily_draft import save_daily_success_report
from src.pipeline.daily_draft import seed_quality_precheck
from src.pipeline.daily_draft import used_keywords
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def run(
    site: str | None = None,
    mode: str = "publish",
    max_posts: int = 3,
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
        if notify:
            notify_batch_completion(result)
        return result

    selected = select_seed_candidates(
        site=settings.site_key,
        content_domain=settings.content_domain,
        max_posts=remaining_slots,
        explicit_seed=explicit_seed,
    )
    result = build_batch_result(settings.site_key, max_posts, existing_today)
    result["selected_candidates"] = selected

    for candidate in selected:
        if len(result["published"]) >= remaining_slots:
            break
        seed = candidate["seed"]
        try:
            article_dir = run_stage1(seed, settings.site_key)
            result_path = run_publish_with_duplicate_guard(article_dir, settings.site_key)
        except Exception as exc:
            if is_quality_gate_failure(exc):
                result["held"].append(
                    {
                        "seed": seed,
                        "article_type": candidate["article_type"],
                        "category": candidate["category"],
                        "reason": "quality_gate_failed",
                        "error": str(exc),
                    }
                )
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
    save_batch_report(result)
    if notify:
        notify_batch_completion(result)
    return result


def select_seed_candidates(
    site: str,
    content_domain: str,
    max_posts: int,
    explicit_seed: str | None = None,
) -> list[dict]:
    publish_used = used_keywords(site, include_validation=False)
    generated_used = used_keywords(site, include_validation=True)
    selected: list[dict] = []
    selected_types: set[str] = set()
    selected_categories: set[str] = set()
    max_precheck = int(os.getenv("DAILY_BATCH_MAX_PRECHECK", "12"))

    for seed in choose_publish_seed_candidates(explicit_seed, site)[:max_precheck]:
        normalized = seed.casefold()
        category = infer_category(seed, content_domain)
        article_type = infer_article_type(seed, category, content_domain)
        precheck = seed_quality_precheck(seed, content_domain)
        precheck_status = precheck.get("status")
        if normalized in publish_used or normalized in generated_used:
            continue
        if precheck_status not in {"ready", "not_applicable"}:
            continue
        if not explicit_seed and article_type in selected_types:
            continue
        if not explicit_seed and category in selected_categories and len(selected) < max_posts - 1:
            continue
        selected.append(
            {
                "seed": seed,
                "category": category,
                "article_type": article_type,
                "quality_precheck": precheck,
            }
        )
        selected_types.add(article_type)
        selected_categories.add(category)
        if len(selected) >= max_posts:
            break
    return selected


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


def save_batch_report(result: dict) -> Path:
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result['site']}-daily-batch-success.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def notify_batch_completion(result: dict) -> None:
    settings = load_settings(result.get("site"))
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish up to three meaningful daily posts without filling weak slots.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    parser.add_argument("--mode", choices=["publish"], default="publish")
    parser.add_argument("--max-posts", type=int, default=daily_publish_limit_from_env(os.getenv("DAILY_BATCH_MAX_POSTS"), quality_review_enabled=True))
    parser.add_argument("--seed", help="Optional explicit seed. Publishes at most one post.")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    result = run(args.site, args.mode, args.max_posts, args.seed, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
