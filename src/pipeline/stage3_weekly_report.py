from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import traceback

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.reporting.weekly import WeeklyReporter


def run(site: str | None = None) -> Path:
    settings = load_settings(site)
    try:
        path = WeeklyReporter(settings).generate()
        NotificationClient(settings).send_required(path.read_text(encoding="utf-8"))
        remove_stale_weekly_failure_report(settings.site_key)
        return path
    except Exception as exc:
        save_weekly_failure_report(site, exc)
        raise


def save_weekly_failure_report(site: str | None, exc: Exception) -> Path:
    settings = load_settings(site)
    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{settings.site_key}-weekly-failure.json"
    payload = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "status": "failed",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def remove_stale_weekly_failure_report(site_key: str) -> None:
    output_path = ROOT_DIR / "reports" / f"{site_key}-weekly-failure.json"
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a weekly automation report.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    path = run(args.site)
    print(path)


if __name__ == "__main__":
    main()
