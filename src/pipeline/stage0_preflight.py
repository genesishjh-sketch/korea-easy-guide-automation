from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from src.config import ROOT_DIR
from src.config import load_settings
from src.google_auth import ANALYTICS_READONLY_SCOPE
from src.google_auth import SEARCH_CONSOLE_SUBMIT_SCOPE
from src.google_auth import resolve_path
from src.google_auth import token_path_for_scopes
from src.pipeline.daily_draft import load_launch_seed_list
from src.pipeline.daily_draft import load_seed_list
from src.pipeline.daily_draft import used_keywords
from src.pipeline.stage0_launch_queue_validate import global_launch_queue_issues
from src.pipeline.stage0_launch_queue_validate import validate_seed
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import REDDIT_DATA_ACCESS_REQUEST_URL
from src.utils.reddit_setup import REDDIT_RESPONSIBLE_BUILDER_POLICY_URL
from src.utils.reddit_setup import reddit_data_access_request_guide
from src.utils.reddit_setup import reddit_oauth_secret_label
from src.utils.reddit_setup import user_action_checklist


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


def run(site: str | None = None) -> Path:
    settings = load_settings(site)
    checks = [
        check_python_runtime(),
        check_site_settings(site),
        check_seed_file(site),
        check_seed_inventory(site),
        check_all_seed_quality(site),
        check_seed_plan_source_quality_reporting(),
        check_launch_queue(site),
        check_launch_queue_quality(site),
        check_reddit_collection_settings(site),
        check_zero_cost_image_policy(),
        check_daily_workflow(),
        check_validate_workflow(),
        check_publication_check_workflow(),
        check_weekly_report_workflow(),
        check_cadence_alert_workflow(),
        check_reddit_health_workflow(),
        check_reddit_health_report_persistence(),
        check_publication_check_report_persistence(),
        check_sitemap_submit_report_persistence(),
        check_daily_failure_report_persistence(),
        check_weekly_failure_report_persistence(),
        check_critical_notifications(),
        check_public_feed(settings.site_url),
        check_local_google_files(settings.google_oauth_client_secret_file, settings.google_oauth_token_file),
        check_reporting_google_files(settings.google_oauth_client_secret_file, settings.google_oauth_token_file),
        check_telegram_settings(settings.notification_provider, settings.telegram_bot_token, settings.telegram_chat_id),
    ]
    setup_actions = build_setup_actions(checks)
    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "status": overall_status(checks),
        "readiness": build_readiness_summary(checks, setup_actions),
        "setup_actions": setup_actions,
        "checks": [asdict(check) for check in checks],
    }
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-preflight.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_dir / f"{settings.site_key}-preflight.md"
    markdown_path.write_text(build_preflight_markdown(result), encoding="utf-8")
    return output_path


def check_site_settings(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    missing = []
    if not settings.site_url:
        missing.append("SITE_URL")
    if not settings.site_name:
        missing.append("SITE_NAME")
    if settings.site_key == "easy_pc_fix_guide" and not settings.blogger_blog_id:
        missing.append("EASY_PC_FIX_GUIDE_BLOGGER_BLOG_ID")
    if missing:
        return PreflightCheck("site_settings", "fail", f"Missing required settings: {', '.join(missing)}")
    return PreflightCheck("site_settings", "pass", f"{settings.site_name} is configured for {settings.site_url}.")


def check_seed_file(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    try:
        seeds = load_seed_list(site)
    except Exception as exc:
        return PreflightCheck("seed_file", "fail", f"Could not load seed file: {exc}")
    blank_count = sum(1 for seed in seeds if not str(seed).strip())
    if blank_count:
        return PreflightCheck("seed_file", "fail", f"Seed file contains {blank_count} blank topic seed(s).")
    normalized_counts: dict[str, int] = {}
    for seed in seeds:
        normalized = str(seed).strip().lower()
        normalized_counts[normalized] = normalized_counts.get(normalized, 0) + 1
    duplicates = sorted(seed for seed, count in normalized_counts.items() if count > 1)
    if duplicates:
        return PreflightCheck(
            "seed_file",
            "fail",
            f"Duplicate topic seeds found: {', '.join(duplicates[:5])}. Remove duplicates before unattended publishing.",
        )
    if settings.content_domain == "windows_help":
        weak_seeds = weak_windows_topic_seeds(seeds)
        if weak_seeds:
            return PreflightCheck(
                "seed_file",
                "fail",
                f"Weak Windows topic seeds found: {', '.join(weak_seeds[:5])}. Use specific error codes, symptoms, apps, or Windows features.",
            )
    if len(seeds) < 30:
        return PreflightCheck("seed_file", "warn", f"Only {len(seeds)} topic seeds found; add more for long automation runs.")
    return PreflightCheck("seed_file", "pass", f"{len(seeds)} topic seeds found.")


def weak_windows_topic_seeds(seeds: list[str]) -> list[str]:
    generic = {
        "error",
        "windows error",
        "windows problem",
        "computer problem",
        "pc problem",
        "windows help",
        "fix windows",
        "windows issue",
    }
    weak = []
    for seed in seeds:
        normalized = str(seed).strip().lower()
        if normalized in generic or len(normalized.split()) < 3:
            weak.append(str(seed).strip())
    return weak


def check_seed_inventory(site: str | None = None) -> PreflightCheck:
    try:
        seeds = load_seed_list(site)
        used = used_keywords(site, include_validation=False)
    except Exception as exc:
        return PreflightCheck("seed_inventory", "fail", f"Could not inspect seed inventory: {exc}")
    normalized_seeds = {seed.lower() for seed in seeds}
    used_seed_count = len(normalized_seeds & used)
    unused_seed_count = max(0, len(normalized_seeds) - used_seed_count)
    message = f"{unused_seed_count}/{len(normalized_seeds)} exact-match topic seeds remain unused."
    if not normalized_seeds:
        return PreflightCheck("seed_inventory", "fail", "Seed inventory is empty.")
    if unused_seed_count == 0:
        return PreflightCheck(
            "seed_inventory",
            "fail",
            f"{message} Add fresh Windows topic seeds before the next unattended publish.",
        )
    if unused_seed_count < 14:
        return PreflightCheck(
            "seed_inventory",
            "warn",
            f"{message} Add at least two weeks of fresh topic seeds soon.",
        )
    return PreflightCheck("seed_inventory", "pass", message)


def check_all_seed_quality(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    if settings.content_domain != "windows_help":
        return PreflightCheck("all_seed_quality", "pass", "No Windows seed quality sweep is required for this site.")
    try:
        seeds = load_seed_list(site)
    except Exception as exc:
        return PreflightCheck("all_seed_quality", "fail", f"Could not load seed quality inputs: {exc}")

    seed_set = set(seeds)
    validations = [validate_seed(seed, seed_set, used=set(), site=site, generate=False) for seed in seeds]
    failures = [item for item in validations if item.status != "pass"]
    if failures:
        details = "; ".join(f"{item.seed}: {', '.join(item.issues)}" for item in failures[:8])
        return PreflightCheck(
            "all_seed_quality",
            "fail",
            f"Long-term seed quality failed for {len(failures)}/{len(validations)} topic(s): {details}",
        )
    return PreflightCheck(
        "all_seed_quality",
        "pass",
        f"{len(validations)}/{len(seeds)} long-term topics have specific categories and enough Microsoft sources.",
    )


def check_launch_queue(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    if settings.content_domain != "windows_help":
        return PreflightCheck("launch_queue", "pass", "No launch queue is required for this site.")
    try:
        seeds = load_seed_list(site)
        launch_seeds = load_launch_seed_list(site)
    except Exception as exc:
        return PreflightCheck("launch_queue", "fail", f"Could not load launch queue: {exc}")
    if len(launch_seeds) < 7:
        return PreflightCheck("launch_queue", "fail", "Windows launch queue must include at least 7 topics.")
    duplicates = sorted({seed for seed in launch_seeds if launch_seeds.count(seed) > 1})
    if duplicates:
        return PreflightCheck("launch_queue", "fail", f"Duplicate launch topics: {', '.join(duplicates)}")
    seed_set = set(seeds)
    missing = [seed for seed in launch_seeds if seed not in seed_set]
    if missing:
        return PreflightCheck("launch_queue", "fail", f"Launch topics missing from main seed file: {', '.join(missing)}")
    used = used_keywords(site, include_validation=False)
    normalized_launch_seeds = {seed.lower() for seed in launch_seeds}
    unused_launch_count = max(0, len(normalized_launch_seeds) - len(normalized_launch_seeds & used))
    message = f"{unused_launch_count}/{len(normalized_launch_seeds)} launch topics remain unused before the long-term queue."
    if unused_launch_count == 0:
        return PreflightCheck(
            "launch_queue",
            "warn",
            f"{message} Production will use the long-term seed list. Add fresh launch topics only if the new blog still needs a guided launch sequence.",
        )
    if unused_launch_count < 3:
        return PreflightCheck(
            "launch_queue",
            "warn",
            f"{message} Add launch topics soon if the new blog still needs a guided launch sequence.",
        )
    return PreflightCheck("launch_queue", "pass", message)


def check_launch_queue_quality(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    if settings.content_domain != "windows_help":
        return PreflightCheck("launch_queue_quality", "pass", "No launch queue quality check is required for this site.")
    try:
        seeds = set(load_seed_list(site))
        launch_seeds = load_launch_seed_list(site)
    except Exception as exc:
        return PreflightCheck("launch_queue_quality", "fail", f"Could not load launch queue quality inputs: {exc}")

    global_issues = global_launch_queue_issues(launch_seeds, seeds)
    if global_issues:
        return PreflightCheck(
            "launch_queue_quality",
            "fail",
            f"Launch queue structure issues: {'; '.join(global_issues[:3])}",
        )

    # Ignore used status here. The regular launch_queue check tracks consumption;
    # this check proves remaining queue entries are specific, categorized, and source-ready.
    validations = [validate_seed(seed, seeds, used=set(), site=site, generate=False) for seed in launch_seeds]
    failures = [item for item in validations if item.status != "pass"]
    if failures:
        details = "; ".join(f"{item.seed}: {', '.join(item.issues)}" for item in failures[:5])
        return PreflightCheck("launch_queue_quality", "fail", f"Launch queue quality failed: {details}")
    return PreflightCheck(
        "launch_queue_quality",
        "pass",
        f"{len(validations)}/{len(launch_seeds)} launch topics have specific categories and enough Microsoft sources.",
    )


def check_reddit_collection_settings(site: str | None = None) -> PreflightCheck:
    settings = load_settings(site)
    if not settings.reddit_subreddits:
        return PreflightCheck("reddit_collection", "fail", "No subreddit list is configured for Reddit topic discovery.")
    if not settings.reddit_user_agent:
        return PreflightCheck("reddit_collection", "fail", "REDDIT_USER_AGENT is required for Reddit topic discovery.")
    if settings.reddit_client_id and settings.reddit_client_secret:
        return PreflightCheck(
            "reddit_collection",
            "pass",
            f"Reddit OAuth credentials are configured for {len(settings.reddit_subreddits)} subreddit(s).",
        )
    wait_note = ""
    if getattr(settings, "reddit_data_access_request_submitted_at", ""):
        wait_note = (
            f" Reddit Data Access Request was submitted on {settings.reddit_data_access_request_submitted_at}; "
            "OAuth can be added later after approval."
        )
    return PreflightCheck(
        "reddit_collection",
        "warn",
        "Reddit OAuth credentials are not configured, so the default topic discovery path uses Google site:reddit.com searches, "
        "Google Suggest, and official-source validation. This does not block unattended publishing or cadence review by itself."
        f"{wait_note} Optional OAuth upgrade: create a script app at {REDDIT_APPS_URL}, then add {reddit_oauth_secret_label()} at {GITHUB_SECRETS_URL}.",
    )


PAID_IMAGE_ENV_NAMES = [
    "OPENAI_API_KEY",
    "OPENAI_IMAGES_API_KEY",
    "OPENAI_IMAGE_MODEL",
    "IMAGE_GENERATION_API_KEY",
    "PEXELS_API_KEY",
]


def check_zero_cost_image_policy() -> PreflightCheck:
    configured = [name for name in PAID_IMAGE_ENV_NAMES if os.getenv(name)]
    workflow_refs = _paid_image_env_refs_in_workflows()
    image_plan = ROOT_DIR / "src" / "images" / "ai_plan.py"
    image_plan_text = image_plan.read_text(encoding="utf-8") if image_plan.exists() else ""
    missing_safeguards = [
        snippet
        for snippet in [
            "Do not call paid image APIs in the Python pipeline.",
            "codex_generated_no_api",
            "prompt_policy",
            "codex_app_automation",
            "built_in_image_gen",
            "IMAGE_ASSET_MODE",
            "manual_jpg",
            "return \"svg\"",
        ]
        if snippet not in image_plan_text
    ]
    if workflow_refs:
        return PreflightCheck(
            "zero_cost_image_policy",
            "fail",
            "Paid/external image API environment names are referenced by GitHub Actions: "
            f"{', '.join(workflow_refs)}. Remove them from unattended publishing workflows.",
        )
    if missing_safeguards:
        return PreflightCheck(
            "zero_cost_image_policy",
            "fail",
            f"Image plan is missing zero-cost safeguards: {', '.join(missing_safeguards)}",
        )
    if configured:
        return PreflightCheck(
            "zero_cost_image_policy",
            "warn",
            "Local paid/external image API settings are present but must not be used by unattended publishing: "
            f"{', '.join(configured)}.",
        )
    return PreflightCheck(
        "zero_cost_image_policy",
        "pass",
        "Unattended publishing is configured for Codex image plans and local SVG fallback without paid image API wiring.",
    )


def _paid_image_env_refs_in_workflows() -> list[str]:
    workflow_dir = ROOT_DIR / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    refs: set[str] = set()
    for path in workflow_dir.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for name in PAID_IMAGE_ENV_NAMES:
            if name in text:
                refs.add(name)
    return sorted(refs)


def check_python_runtime() -> PreflightCheck:
    version = sys.version_info
    current = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < (3, 11):
        return PreflightCheck(
            "python_runtime",
            "warn",
            f"Current Python is {current}; use Python 3.11 to match GitHub Actions and avoid dependency drift.",
        )
    return PreflightCheck("python_runtime", "pass", f"Python {current} matches the automation runtime policy.")


def check_daily_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml"
    if not path.exists():
        return PreflightCheck("daily_workflow", "fail", "Easy PC daily workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "Run safety regression tests",
        'cron: "10 0 * * *"',
        'cron: "25 0 * * *"',
        "group: easy-pc-fix-daily-publish",
        "cancel-in-progress: false",
        "python -m unittest discover -v",
        "python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide",
        "python -m src.pipeline.daily_draft --site easy_pc_fix_guide",
        "env.BLOGGER_PUBLISH_MODE == 'publish'",
        "python -m src.pipeline.stage3_submit_sitemap --site easy_pc_fix_guide",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("daily_workflow", "fail", f"Missing workflow safeguards: {', '.join(missing)}")
    return PreflightCheck(
        "daily_workflow",
        "pass",
        "Daily workflow runs tests before publishing, prevents overlapping publish runs, and submits sitemap only after publish runs.",
    )


def check_validate_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-validate-smoke.yml"
    if not path.exists():
        return PreflightCheck("validate_workflow", "fail", "Easy PC validate workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        '"src/**"',
        '"tests/**"',
        '".github/workflows/easy-pc-daily.yml"',
        '".github/workflows/easy-pc-publication-check.yml"',
        '".github/workflows/easy-pc-weekly-report.yml"',
        '".github/workflows/easy-pc-cadence-alert.yml"',
        '".github/workflows/easy-pc-validate-smoke.yml"',
        "Run safety regression tests",
        "python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode validate",
        "if: ${{ always() }}",
        "reports/",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("validate_workflow", "fail", f"Missing validate workflow coverage: {', '.join(missing)}")
    return PreflightCheck("validate_workflow", "pass", "Validate workflow covers source, tests, and Easy PC workflow changes.")


def check_publication_check_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-publication-check.yml"
    if not path.exists():
        return PreflightCheck("publication_check_workflow", "fail", "Easy PC publication check workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "45 0 * * *",
        "python -m src.pipeline.stage4_publication_check --site easy_pc_fix_guide --after-hour 9",
        "if: always()",
        "reports/easy_pc_fix_guide-publication-check.json",
        "reports/easy_pc_fix_guide-publication-check.md",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("publication_check_workflow", "fail", f"Missing publication check safeguards: {', '.join(missing)}")
    return PreflightCheck("publication_check_workflow", "pass", "Publication check workflow verifies the public feed after daily publishing and uploads its report.")


def check_weekly_report_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-weekly-report.yml"
    if not path.exists():
        return PreflightCheck("weekly_report_workflow", "fail", "Easy PC weekly report workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "40 0 * * 1",
        "GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON",
        "GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON",
        "REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}",
        "REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}",
        "python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide",
        "continue-on-error: true",
        "reports/easy_pc_fix_guide-reddit-health.json",
        "python -m src.pipeline.stage3_weekly_report --site easy_pc_fix_guide",
        "reports/easy_pc_fix_guide-weekly-*",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("weekly_report_workflow", "fail", f"Missing weekly report safeguards: {', '.join(missing)}")
    return PreflightCheck("weekly_report_workflow", "pass", "Weekly report workflow includes Search Console, Analytics, Telegram, and artifact upload wiring.")


def check_cadence_alert_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-cadence-alert.yml"
    if not path.exists():
        return PreflightCheck("cadence_alert_workflow", "fail", "Easy PC cadence alert workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "30 0 22 7 *",
        "30 0 19 8 *",
        "GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON",
        "python -m src.pipeline.stage3_cadence_alert --site easy_pc_fix_guide",
        "Upload cadence alert report",
        "if: ${{ always() }}",
        "reports/easy_pc_fix_guide-cadence-alert-*.json",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("cadence_alert_workflow", "fail", f"Missing cadence alert safeguards: {', '.join(missing)}")
    return PreflightCheck("cadence_alert_workflow", "pass", "Cadence alert workflow sends Posting Bot review alerts on 2026-07-22 and 2026-08-19.")


def check_reddit_health_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-reddit-health.yml"
    if not path.exists():
        return PreflightCheck("reddit_health_workflow", "fail", "Easy PC Reddit health workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "20 0 * * *",
        "REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}",
        "REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}",
        "python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide",
        'EVENT_NAME="${{ github.event_name }}"',
        "--notify",
        "reports/easy_pc_fix_guide-reddit-health.json",
        "reports/easy_pc_fix_guide-reddit-health.md",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("reddit_health_workflow", "fail", f"Missing Reddit health workflow safeguards: {', '.join(missing)}")
    return PreflightCheck(
        "reddit_health_workflow",
        "pass",
        "Reddit health workflow checks OAuth with secrets, keeps scheduled runs quiet, and uploads JSON/Markdown reports.",
    )


def check_reddit_health_report_persistence() -> PreflightCheck:
    path = ROOT_DIR / "src" / "pipeline" / "stage0_reddit_health.py"
    if not path.exists():
        return PreflightCheck("reddit_health_report_persistence", "fail", "Reddit health pipeline file is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "human_summary_markdown",
        "build_markdown_report(result)",
        "reddit-health.md",
        "output_path.write_text(json.dumps(result",
        "markdown_path.write_text(markdown_report",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck(
            "reddit_health_report_persistence",
            "fail",
            f"Missing Reddit health report persistence safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "reddit_health_report_persistence",
        "pass",
        "Reddit health writes JSON, Markdown, and embedded human-readable summary before notification.",
    )


def check_publication_check_report_persistence() -> PreflightCheck:
    path = ROOT_DIR / "src" / "pipeline" / "stage4_publication_check.py"
    if not path.exists():
        return PreflightCheck("publication_check_report_persistence", "fail", "Publication check pipeline file is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "publication_check_failure_result",
        "save_result(result)",
        "publication-check.md",
        "action_items",
        "notification_error",
        "raise",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck(
            "publication_check_report_persistence",
            "fail",
            f"Missing publication check failure persistence safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "publication_check_report_persistence",
        "pass",
        "Publication check writes JSON/Markdown and action items even when public feed verification fails.",
    )


def check_sitemap_submit_report_persistence() -> PreflightCheck:
    path = ROOT_DIR / "src" / "pipeline" / "stage3_submit_sitemap.py"
    if not path.exists():
        return PreflightCheck("sitemap_submit_report_persistence", "fail", "Search Console sitemap pipeline file is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "SearchConsoleClient(settings).submit_sitemap",
        'result["submitted_at"]',
        "build_daily_publish_context(settings.site_key)",
        "build_indexing_guidance(result)",
        "sitemap_action_items(result)",
        'result["human_summary"] = build_message',
        "search-console-sitemap-submit.json",
        "output_path.write_text(json.dumps(result",
        'NotificationClient(settings).send_required(result["human_summary"])',
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck(
            "sitemap_submit_report_persistence",
            "fail",
            f"Missing sitemap submission report persistence safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "sitemap_submit_report_persistence",
        "pass",
        "Sitemap submission writes JSON action items, indexing guidance, daily context, and human summary before notification.",
    )


def check_daily_failure_report_persistence() -> PreflightCheck:
    path = ROOT_DIR / "src" / "pipeline" / "daily_draft.py"
    if not path.exists():
        return PreflightCheck("daily_failure_report_persistence", "fail", "Daily draft pipeline file is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "save_daily_failure_report(selected_seed, exc, site, publish_mode)",
        "daily_failure_action_items(error, mode, settings.site_key)",
        "build_daily_failure_message(seed, exc, site, mode)",
        "\"error_summary\": error",
        "\"action_items\": action_items",
        "\"human_summary\": build_daily_failure_message",
        "\"traceback\": traceback.format_exception",
        "daily_failure_report_name(settings.site_key, mode)",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck(
            "daily_failure_report_persistence",
            "fail",
            f"Missing daily failure report persistence safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "daily_failure_report_persistence",
        "pass",
        "Daily publish failures write JSON action items, human summary, and traceback before notification.",
    )


def check_weekly_failure_report_persistence() -> PreflightCheck:
    path = ROOT_DIR / "src" / "pipeline" / "stage3_weekly_report.py"
    if not path.exists():
        return PreflightCheck("weekly_failure_report_persistence", "fail", "Weekly report pipeline file is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "save_weekly_failure_report(site, exc)",
        "weekly_failure_action_items(error)",
        "build_weekly_failure_message(site, exc)",
        "\"error_summary\": error",
        "\"action_items\": action_items",
        "\"human_summary\": build_weekly_failure_message",
        "\"traceback\": traceback.format_exception",
        "weekly-failure.json",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck(
            "weekly_failure_report_persistence",
            "fail",
            f"Missing weekly failure report persistence safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "weekly_failure_report_persistence",
        "pass",
        "Weekly report failures write JSON action items, human summary, and traceback before notification.",
    )


def check_seed_plan_source_quality_reporting() -> PreflightCheck:
    daily_path = ROOT_DIR / "src" / "pipeline" / "daily_draft.py"
    weekly_path = ROOT_DIR / "src" / "reporting" / "weekly.py"
    if not daily_path.exists() or not weekly_path.exists():
        return PreflightCheck(
            "seed_plan_source_quality_reporting",
            "fail",
            "Daily or weekly reporting file is missing.",
        )
    daily_text = daily_path.read_text(encoding="utf-8")
    weekly_text = weekly_path.read_text(encoding="utf-8")
    required = {
        "daily_draft.py": [
            "direct_microsoft_source_count",
            "search_result_source_count",
            "/검색",
            "Microsoft 출처",
        ],
        "weekly.py": [
            "_seed_plan_source_quality_lines",
            "후보 소스 품질",
            "다음 시드 출처",
            "search_result_source_count",
        ],
    }
    missing = []
    for filename, snippets in required.items():
        text = daily_text if filename == "daily_draft.py" else weekly_text
        missing.extend(f"{filename}:{snippet}" for snippet in snippets if snippet not in text)
    if missing:
        return PreflightCheck(
            "seed_plan_source_quality_reporting",
            "fail",
            f"Missing seed plan source quality reporting safeguards: {', '.join(missing)}",
        )
    return PreflightCheck(
        "seed_plan_source_quality_reporting",
        "pass",
        "Daily and weekly reports show direct Microsoft source counts and Microsoft search-result counts.",
    )


def check_critical_notifications() -> PreflightCheck:
    required = {
        "daily_draft.py": [
            "NotificationClient(settings).send_required(build_daily_success_message(result))",
            "NotificationClient(settings).send_required(build_daily_failure_message(seed, exc, site, mode))",
        ],
        "stage3_submit_sitemap.py": "NotificationClient(settings).send_required(result[\"human_summary\"])",
        "stage4_publication_check.py": "NotificationClient(settings).send_required(build_message(result))",
        "stage0_reddit_health.py": "NotificationClient(settings).send_required(build_message(result))",
        "stage3_weekly_report.py": [
            "NotificationClient(settings).send_required(path.read_text(encoding=\"utf-8\"))",
            "NotificationClient(settings).send_required(build_weekly_failure_message(site, exc))",
        ],
        "stage3_cadence_alert.py": "NotificationClient(settings).send_required(message)",
    }
    missing = []
    pipeline_dir = ROOT_DIR / "src" / "pipeline"
    for filename, snippet in required.items():
        path = pipeline_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        text = path.read_text(encoding="utf-8")
        snippets = snippet if isinstance(snippet, list) else [snippet]
        missing_snippets = [item for item in snippets if item not in text]
        if missing_snippets:
            missing.append(filename)
    if missing:
        return PreflightCheck(
            "critical_notifications",
            "fail",
            f"Critical Posting Bot notifications are not enforced in: {', '.join(missing)}",
        )
    return PreflightCheck("critical_notifications", "pass", "Critical Posting Bot notifications fail loudly if Telegram delivery fails.")


def check_public_feed(site_url: str) -> PreflightCheck:
    try:
        posts = parse_posts(fetch_public_feed(site_url))
    except Exception as exc:
        return PreflightCheck("public_feed", "warn", f"Public Blogger feed could not be read: {exc}")
    if not posts:
        return PreflightCheck("public_feed", "warn", "Public Blogger feed is reachable but has no posts yet.")
    return PreflightCheck("public_feed", "pass", f"Public Blogger feed is reachable with {len(posts)} recent post(s).")


def check_local_google_files(client_secret_file: str, token_file: str) -> PreflightCheck:
    missing = []
    for label, value in [("GOOGLE_OAUTH_CLIENT_SECRET_FILE", client_secret_file), ("GOOGLE_OAUTH_TOKEN_FILE", token_file)]:
        if not value:
            missing.append(label)
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.exists():
            missing.append(label)
    if missing:
        return PreflightCheck(
            "local_google_files",
            "warn",
            f"Local OAuth files missing or unset: {', '.join(missing)}. This is OK in GitHub Actions if secrets are configured.",
        )
    return PreflightCheck("local_google_files", "pass", "Local Google OAuth files are present.")


def check_reporting_google_files(client_secret_file: str, token_file: str) -> PreflightCheck:
    if not client_secret_file or not token_file:
        return PreflightCheck(
            "reporting_google_files",
            "warn",
            "Search Console/GA4 reporting OAuth files are not fully set locally. "
            "This is OK in GitHub Actions if reporting token secrets are configured.",
        )

    secret_path = resolve_path(client_secret_file)
    search_console_token = token_path_for_scopes(token_file, [SEARCH_CONSOLE_SUBMIT_SCOPE])
    analytics_token = token_path_for_scopes(token_file, [ANALYTICS_READONLY_SCOPE])
    missing = []
    for label, path in [
        ("GOOGLE_OAUTH_CLIENT_SECRET_FILE", secret_path),
        ("GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON", search_console_token),
        ("GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON", analytics_token),
    ]:
        if not path.exists():
            missing.append(label)

    if missing:
        return PreflightCheck(
            "reporting_google_files",
            "warn",
            "Reporting OAuth files missing locally: "
            f"{', '.join(missing)}. Weekly reports can still work in GitHub Actions if the matching secrets exist.",
        )
    return PreflightCheck(
        "reporting_google_files",
        "pass",
        "Search Console and GA4 reporting OAuth token files are present locally.",
    )


def check_telegram_settings(provider: str, bot_token: str, chat_id: str) -> PreflightCheck:
    if provider.lower() != "telegram":
        return PreflightCheck("telegram", "warn", "Telegram notifications are disabled.")
    if not bot_token or not chat_id:
        return PreflightCheck("telegram", "fail", "Telegram provider is enabled but bot token or chat ID is missing.")
    return PreflightCheck("telegram", "pass", "Telegram notifications are configured.")


def build_setup_actions(checks: list[PreflightCheck]) -> list[dict]:
    actions = []
    for check in checks:
        if check.status == "pass":
            continue
        if check.name == "reddit_collection":
            actions.append(
                {
                    "name": "reddit_oauth_optional",
                    "label": "Reddit OAuth 선택 보강",
                    "status": check.status,
                    "owner": "user",
                    "urgency": "optional_upgrade",
                    "blocks_unattended_publish": check.status == "fail",
                    "blocks_cadence_increase": check.status == "fail",
                    "message": check.message,
                    "next_step": (
                        "지금은 Google site:reddit.com 검색 기반 리서치로 운영하세요. "
                        "승인 메일이 오면 Reddit script app을 만들고 REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets에 저장한 뒤 "
                        "Easy PC Fix Reddit OAuth Health workflow를 수동 실행하면 됩니다."
                    ),
                    "links": {
                        "reddit_apps": REDDIT_APPS_URL,
                        "reddit_data_access_request": REDDIT_DATA_ACCESS_REQUEST_URL,
                        "responsible_builder_policy": REDDIT_RESPONSIBLE_BUILDER_POLICY_URL,
                        "github_secrets": GITHUB_SECRETS_URL,
                    },
                    "reddit_data_access_request_guide": reddit_data_access_request_guide(),
                    "user_action_checklist": user_action_checklist(
                        "Easy PC Fix Guide Automation",
                        "easy-pc-fix-guide/0.1 by posting-automation-alert-bot",
                    ),
                }
            )
        elif check.name == "reporting_google_files":
            actions.append(
                {
                    "name": "reporting_oauth",
                    "label": "Search Console/GA4 보고 토큰",
                    "status": check.status,
                    "owner": "user_or_github_secrets",
                    "urgency": "before_weekly_reporting",
                    "blocks_unattended_publish": False,
                    "blocks_cadence_increase": False,
                    "message": check.message,
                    "next_step": (
                        "GitHub Secrets에 GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON과 "
                        "GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON이 있는지 확인하세요."
                    ),
                }
            )
        elif check.name == "telegram":
            actions.append(
                {
                    "name": "posting_bot",
                    "label": "Posting Bot 알림",
                    "status": check.status,
                    "owner": "user_or_github_secrets",
                    "urgency": "before_unattended_operations",
                    "blocks_unattended_publish": check.status == "fail",
                    "blocks_cadence_increase": False,
                    "message": check.message,
                    "next_step": "NOTIFICATION_PROVIDER=telegram, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 설정하세요.",
                }
            )
        elif check.name == "seed_inventory":
            is_failure = check.status == "fail"
            actions.append(
                {
                    "name": "seed_inventory",
                    "label": "Windows topic seed 재고",
                    "status": check.status,
                    "owner": "automation",
                    "urgency": "before_unattended_publish" if is_failure else "before_cadence_increase",
                    "blocks_unattended_publish": is_failure,
                    "blocks_cadence_increase": True,
                    "message": check.message,
                    "next_step": (
                        "새 Windows 오류/증상 seed를 최소 14개 이상 보충하고, "
                        "중복/모호한 주제가 없는지 preflight를 다시 실행하세요."
                    ),
                }
            )
        elif check.name == "python_runtime":
            actions.append(
                {
                    "name": "python_runtime",
                    "label": "로컬 Python 런타임",
                    "status": check.status,
                    "owner": "local_environment",
                    "urgency": "maintenance",
                    "blocks_unattended_publish": False,
                    "blocks_cadence_increase": False,
                    "message": check.message,
                    "next_step": "로컬 개발 환경을 Python 3.11로 맞추면 GitHub Actions와 더 비슷하게 검증할 수 있습니다.",
                }
            )
        elif check.name in {
            "site_settings",
            "seed_file",
            "all_seed_quality",
            "launch_queue",
            "launch_queue_quality",
            "daily_workflow",
            "critical_notifications",
        }:
            actions.append(
                {
                    "name": check.name,
                    "label": check.name,
                    "status": check.status,
                    "owner": "automation",
                    "urgency": "before_unattended_publish",
                    "blocks_unattended_publish": True,
                    "blocks_cadence_increase": True,
                    "message": check.message,
                    "next_step": "자동 발행 전에 이 preflight 항목을 pass로 복구하세요.",
                }
            )
        else:
            actions.append(
                {
                    "name": check.name,
                    "label": check.name,
                    "status": check.status,
                    "owner": "automation_or_user",
                    "urgency": "review",
                    "blocks_unattended_publish": check.status == "fail",
                    "blocks_cadence_increase": check.status == "fail",
                    "message": check.message,
                    "next_step": "preflight 메시지를 확인하고 필요한 설정이나 워크플로를 복구하세요.",
                }
            )
    return actions


def build_readiness_summary(checks: list[PreflightCheck], setup_actions: list[dict]) -> dict:
    return {
        "ready_for_unattended_publish": not any(action.get("blocks_unattended_publish") for action in setup_actions),
        "ready_for_cadence_increase": not any(action.get("blocks_cadence_increase") for action in setup_actions),
        "required_user_action_count": sum(1 for action in setup_actions if str(action.get("owner", "")).startswith("user")),
        "action_count": len(setup_actions),
        "failed_checks": [check.name for check in checks if check.status == "fail"],
        "warning_checks": [check.name for check in checks if check.status == "warn"],
    }


def build_preflight_markdown(result: dict) -> str:
    readiness = result.get("readiness") or {}
    setup_actions = result.get("setup_actions") or []
    checks = result.get("checks") or []
    lines = [
        f"# Preflight Report: {result.get('site_name', result.get('site', 'Unknown Site'))}",
        "",
        f"- 사이트: {result.get('site_url', '')}",
        f"- 전체 상태: {_status_label(result.get('status'))}",
        f"- 무인 발행 준비: {'예' if readiness.get('ready_for_unattended_publish') else '아니오'}",
        f"- 발행량 증량 준비: {'예' if readiness.get('ready_for_cadence_increase') else '아니오'}",
        f"- 필요 사용자 조치 수: {readiness.get('required_user_action_count', 0)}",
        "",
        "## 필요한 조치",
        "",
    ]
    if setup_actions:
        for action in setup_actions:
            lines.extend(
                [
                    f"### {action.get('label', action.get('name', '설정 조치'))}",
                    "",
                    f"- 상태: {_status_label(action.get('status'))}",
                    f"- 담당: {action.get('owner', '확인 필요')}",
                    f"- 시점: {action.get('urgency', 'review')}",
                    f"- 무인 발행 차단: {'예' if action.get('blocks_unattended_publish') else '아니오'}",
                    f"- 증량 차단: {'예' if action.get('blocks_cadence_increase') else '아니오'}",
                    f"- 내용: {action.get('message', '')}",
                    f"- 다음 단계: {action.get('next_step', '확인 필요')}",
                ]
            )
            links = action.get("links") or {}
            if links:
                lines.append("- 링크:")
                for label, url in links.items():
                    lines.append(f"  - {label}: {url}")
            access_request = action.get("reddit_data_access_request_guide") or []
            if access_request:
                lines.append("- Data Access Request 입력 가이드:")
                for item in access_request:
                    lines.append(f"  - {item}")
            checklist = action.get("user_action_checklist") or []
            if checklist:
                lines.append("- 사용자가 직접 할 일:")
                for item in checklist:
                    lines.append(f"  - {item}")
            lines.append("")
    else:
        lines.append("- 추가 조치 없음")
        lines.append("")

    lines.extend(["## 전체 점검", ""])
    for check in checks:
        lines.append(f"- {_status_label(check.get('status'))} `{check.get('name')}`: {check.get('message')}")
    lines.append("")
    return "\n".join(lines)


def _status_label(status: str | None) -> str:
    return {
        "pass": "통과",
        "warn": "주의",
        "fail": "실패",
    }.get(status or "", status or "확인 필요")


def overall_status(checks: list[PreflightCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a site automation preflight check.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    path = run(args.site)
    print(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
