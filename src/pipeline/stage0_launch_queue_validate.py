from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import json
from pathlib import Path
import sys

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.topic_scoring import infer_category
from src.content.windows_generator import _sources_for_topic
from src.pipeline.daily_draft import load_launch_seed_list
from src.pipeline.daily_draft import load_seed_list
from src.pipeline.daily_draft import run_stage1
from src.pipeline.daily_draft import run_validation
from src.pipeline.daily_draft import used_keywords


MIN_LAUNCH_QUEUE_SIZE = 7
MIN_MICROSOFT_SOURCES = 6
MIN_DIRECT_MICROSOFT_SOURCES = 5
MAX_SEARCH_RESULT_SOURCES = 1


@dataclass(frozen=True)
class LaunchSeedValidation:
    seed: str
    status: str
    category: str
    source_count: int
    direct_microsoft_source_count: int
    search_result_source_count: int
    issues: list[str]
    article_dir: str = ""
    quality_score: int | None = None


def run(site: str | None = None, generate: bool = False, limit: int | None = None) -> Path:
    settings = load_settings(site)
    launch_seeds = load_launch_seed_list(site)
    main_seeds = set(load_seed_list(site))
    used = used_keywords(site, include_validation=False)

    selected_seeds = launch_seeds[:limit] if limit is not None else launch_seeds
    items = [
        validate_seed(seed, main_seeds, used, site=site, generate=generate)
        for seed in selected_seeds
    ]
    global_issues = global_launch_queue_issues(launch_seeds, main_seeds)
    status = "pass" if not global_issues and all(item.status == "pass" for item in items) else "fail"
    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "status": status,
        "mode": "generate" if generate else "static",
        "seed_count": len(launch_seeds),
        "validated_seed_count": len(items),
        "passed_seed_count": sum(1 for item in items if item.status == "pass"),
        "global_issues": global_issues,
        "items": [asdict(item) for item in items],
    }
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-launch-queue-validation.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def validate_seed(
    seed: str,
    main_seeds: set[str],
    used: set[str],
    site: str | None = None,
    generate: bool = False,
) -> LaunchSeedValidation:
    issues = static_seed_issues(seed, main_seeds, used)
    article_dir = ""
    quality_score: int | None = None
    if generate and not issues:
        try:
            generated_dir = run_stage1(seed, site)
            article_dir = str(generated_dir)
            result_path = run_validation(generated_dir, site)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            quality_score = result.get("score")
            if result.get("passed") is not True:
                issues.append("hades_validation_failed")
        except Exception as exc:
            issues.append(f"generation_failed: {exc}")
    sources = _sources_for_topic(seed)
    search_result_source_count = sum(1 for source in sources if is_search_result_url(source.get("url", "")))
    return LaunchSeedValidation(
        seed=seed,
        status="pass" if not issues else "fail",
        category=infer_category(seed, "windows_help"),
        source_count=len(sources),
        direct_microsoft_source_count=sum(1 for source in sources if is_direct_microsoft_url(source.get("url", ""))),
        search_result_source_count=search_result_source_count,
        issues=issues,
        article_dir=article_dir,
        quality_score=quality_score,
    )


def global_launch_queue_issues(launch_seeds: list[str], main_seeds: set[str]) -> list[str]:
    issues = []
    if len(launch_seeds) < MIN_LAUNCH_QUEUE_SIZE:
        issues.append(f"launch_queue_too_short: at least {MIN_LAUNCH_QUEUE_SIZE} topics are required")
    duplicates = sorted({seed for seed in launch_seeds if launch_seeds.count(seed) > 1})
    if duplicates:
        issues.append(f"duplicate_launch_topics: {', '.join(duplicates)}")
    missing = [seed for seed in launch_seeds if seed not in main_seeds]
    if missing:
        issues.append(f"launch_topics_missing_from_main_seed_file: {', '.join(missing)}")
    return issues


def static_seed_issues(seed: str, main_seeds: set[str], used: set[str]) -> list[str]:
    issues = []
    if seed not in main_seeds:
        issues.append("missing_from_main_seed_file")
    if seed.casefold() in used:
        issues.append("already_used")
    category = infer_category(seed, "windows_help")
    if category == "Computer Help":
        issues.append("generic_computer_help_category")
    sources = _sources_for_topic(seed)
    if len(sources) < MIN_MICROSOFT_SOURCES:
        issues.append("weak_microsoft_sources")
    direct_sources = [source for source in sources if is_direct_microsoft_url(source.get("url", ""))]
    if len(direct_sources) < MIN_DIRECT_MICROSOFT_SOURCES:
        issues.append("shallow_microsoft_sources")
    search_result_sources = [source for source in sources if is_search_result_url(source.get("url", ""))]
    if len(search_result_sources) > MAX_SEARCH_RESULT_SOURCES:
        issues.append("too_many_microsoft_search_result_sources")
    return issues


def is_direct_microsoft_url(url: str) -> bool:
    if not any(domain in url for domain in ("microsoft.com", "learn.microsoft.com", "support.microsoft.com")):
        return False
    blocked_fragments = (
        "support.microsoft.com/search/results",
        "support.microsoft.com/search?",
        "bing.com/search",
    )
    return not any(fragment in url for fragment in blocked_fragments)


def is_search_result_url(url: str) -> bool:
    return "support.microsoft.com/search/results" in url or "support.microsoft.com/search?" in url or "bing.com/search" in url


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Easy PC Fix launch queue readiness.")
    parser.add_argument("--site", default=None)
    parser.add_argument("--generate", action="store_true", help="Also generate articles and run Hades validation.")
    parser.add_argument("--limit", type=int, default=None, help="Validate only the first N launch queue topics.")
    args = parser.parse_args()

    output_path = run(args.site, generate=args.generate, limit=args.limit)
    print(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if payload.get("status") != "pass":
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
