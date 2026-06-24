from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import json
from pathlib import Path

from src.config import ROOT_DIR
from src.config import load_settings
from src.pipeline.daily_draft import load_launch_seed_list
from src.pipeline.daily_draft import load_seed_list
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


def run(site: str | None = None) -> Path:
    settings = load_settings(site)
    checks = [
        check_site_settings(site),
        check_seed_file(site),
        check_launch_queue(site),
        check_daily_workflow(),
        check_validate_workflow(),
        check_publication_check_workflow(),
        check_weekly_report_workflow(),
        check_critical_notifications(),
        check_public_feed(settings.site_url),
        check_local_google_files(settings.google_oauth_client_secret_file, settings.google_oauth_token_file),
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
    try:
        seeds = load_seed_list(site)
    except Exception as exc:
        return PreflightCheck("seed_file", "fail", f"Could not load seed file: {exc}")
    if len(seeds) < 30:
        return PreflightCheck("seed_file", "warn", f"Only {len(seeds)} topic seeds found; add more for long automation runs.")
    return PreflightCheck("seed_file", "pass", f"{len(seeds)} topic seeds found.")


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
    return PreflightCheck("launch_queue", "pass", f"{len(launch_seeds)} launch topics are ready before the long-term queue.")


def check_daily_workflow() -> PreflightCheck:
    path = ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml"
    if not path.exists():
        return PreflightCheck("daily_workflow", "fail", "Easy PC daily workflow is missing.")
    text = path.read_text(encoding="utf-8")
    required = [
        "Run safety regression tests",
        "python -m unittest discover -v",
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
        "Run safety regression tests",
        "python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode validate",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return PreflightCheck("validate_workflow", "fail", f"Missing validate workflow coverage: {', '.join(missing)}")
    return PreflightCheck("validate_workflow", "pass", "Validate workflow covers source, tests, and daily workflow changes.")


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


def check_critical_notifications() -> PreflightCheck:
    required = {
        "daily_draft.py": "NotificationClient(settings).send_required(build_daily_success_message(result))",
        "stage3_submit_sitemap.py": "NotificationClient(settings).send_required(build_message(settings.site_name, result))",
        "stage4_publication_check.py": "NotificationClient(settings).send_required(build_message(result))",
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
        if snippet not in path.read_text(encoding="utf-8"):
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
