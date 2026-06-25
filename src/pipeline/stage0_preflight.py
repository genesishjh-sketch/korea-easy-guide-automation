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
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import reddit_oauth_secret_label


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
        check_launch_queue(site),
        check_reddit_collection_settings(site),
        check_zero_cost_image_policy(),
        check_daily_workflow(),
        check_validate_workflow(),
        check_publication_check_workflow(),
        check_weekly_report_workflow(),
        check_cadence_alert_workflow(),
        check_reddit_health_workflow(),
        check_critical_notifications(),
        check_public_feed(settings.site_url),
        check_local_google_files(settings.google_oauth_client_secret_file, settings.google_oauth_token_file),
        check_reporting_google_files(settings.google_oauth_client_secret_file, settings.google_oauth_token_file),
        check_telegram_settings(settings.notification_provider, settings.telegram_bot_token, settings.telegram_chat_id),
    ]
    result = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "status": overall_status(checks),
        "checks": [asdict(check) for check in checks],
    }
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-preflight.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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
        used = used_keywords(site)
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
    used = used_keywords(site)
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
    return PreflightCheck(
        "reddit_collection",
        "warn",
        "Reddit OAuth credentials are missing. Public Reddit JSON may return 403, so the pipeline may rely on fallback reader questions. "
        f"Create a script app at {REDDIT_APPS_URL}, then add {reddit_oauth_secret_label()} at {GITHUB_SECRETS_URL}.",
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
        "python -m unittest discover -v",
        "python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide",
        "python -m src.pipeline.daily_draft --site easy_pc_fix_guide",
        "env.BLOGGER_PUBLISH_MODE == 'publish'",
        "python -m src.pipeline.stage3_submit_sitemap --site easy_pc_fix_guide",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("daily_workflow", "fail", f"Missing workflow safeguards: {', '.join(missing)}")
    return PreflightCheck("daily_workflow", "pass", "Daily workflow runs tests before publishing and submits sitemap only after publish runs.")


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
        "--notify",
        "reports/easy_pc_fix_guide-reddit-health.json",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("reddit_health_workflow", "fail", f"Missing Reddit health workflow safeguards: {', '.join(missing)}")
    return PreflightCheck("reddit_health_workflow", "pass", "Reddit health workflow checks OAuth with secrets and uploads its report.")


def check_critical_notifications() -> PreflightCheck:
    required = {
        "daily_draft.py": [
            "NotificationClient(settings).send_required(build_daily_success_message(result))",
            "NotificationClient(settings).send_required(build_daily_failure_message(seed, exc, site))",
        ],
        "stage3_submit_sitemap.py": "NotificationClient(settings).send_required(build_message(settings.site_name, result))",
        "stage4_publication_check.py": "NotificationClient(settings).send_required(build_message(result))",
        "stage0_reddit_health.py": "NotificationClient(settings).send_required(build_message(result))",
        "stage3_weekly_report.py": "NotificationClient(settings).send_required(path.read_text(encoding=\"utf-8\"))",
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
