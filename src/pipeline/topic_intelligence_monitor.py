from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR
from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.pipeline.weekly_queue import load_weekly_queue
from src.pipeline.weekly_queue import queue_registry_provenance_valid
from src.sites import SITE_PROFILES
from src.topics.sheet_sync import load_sheet_sync_state
from src.topics.store import DEFAULT_ROOT
from src.topics.store import TopicStore


KST = ZoneInfo("Asia/Seoul")
DEFAULT_MAX_RUN_AGE_HOURS = 192.0
MONITOR_REPORT = ROOT_DIR / "reports" / "topic-intelligence-monitor.json"
MONITOR_STATE = ROOT_DIR / "reports" / "topic-intelligence-monitor-state.json"


def _age_hours(value: str, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600


def build_monitor_report(
    store: TopicStore,
    sites: list[str],
    *,
    now: datetime | None = None,
    max_run_age_hours: float = DEFAULT_MAX_RUN_AGE_HOURS,
    queue_loader: Callable[[str, object], dict | None] = load_weekly_queue,
) -> dict:
    selected_now = now or datetime.now(tz=KST)
    site_reports = []
    for site in sites:
        rollout = store.get_rollout_state(site)
        issues: list[dict[str, str]] = []
        validation_errors = [
            item.to_dict()
            for item in store.validate_site(site)
            if item.severity == "ERROR"
        ]
        if validation_errors:
            issues.append(
                {
                    "code": "REGISTRY_INVALID",
                    "detail": f"{len(validation_errors)} validation errors",
                }
            )
        if not bool((rollout.get("backfill") or {}).get("complete")):
            issues.append(
                {
                    "code": "BACKFILL_INCOMPLETE",
                    "detail": "required backfill coverage is incomplete",
                }
            )
        last_run_id = str(rollout.get("last_run_id") or "")
        last_run_at = str(rollout.get("last_run_at") or "")
        run_age = _age_hours(last_run_at, selected_now)
        if not last_run_id:
            issues.append(
                {
                    "code": "WEEKLY_RUN_MISSING",
                    "detail": "no qualifying weekly research run is recorded",
                }
            )
        elif run_age is None or run_age > max_run_age_hours:
            issues.append(
                {
                    "code": "WEEKLY_RUN_STALE",
                    "detail": f"latest weekly run age is {run_age!r} hours",
                }
            )
        queue = queue_loader(site, selected_now.date())
        if queue is None:
            issues.append(
                {
                    "code": "CURRENT_QUEUE_MISSING",
                    "detail": "current ISO-week queue is missing",
                }
            )
            registry_queue_items = 0
        else:
            registry_queue_items = sum(
                1
                for item in queue.get("items") or []
                if item.get("topic_source") == "registry"
            )
            if registry_queue_items and not queue_registry_provenance_valid(
                queue,
                site,
                store,
            ):
                issues.append(
                    {
                        "code": "QUEUE_PROVENANCE_INVALID",
                        "detail": "Registry queue does not match latest completed run",
                    }
                )
        sheet_state = load_sheet_sync_state(store, site)
        sheet_record = dict((sheet_state.get("runs") or {}).get(last_run_id) or {})
        if last_run_id and sheet_record.get("status") != "SUCCESS":
            issues.append(
                {
                    "code": "SHEET_SYNC_PENDING",
                    "detail": f"{last_run_id} is not acknowledged SUCCESS",
                }
            )
        outbox_count = len(store.list_publication_outbox(site))
        if outbox_count:
            issues.append(
                {
                    "code": "PUBLICATION_OUTBOX_PENDING",
                    "detail": f"{outbox_count} publication reconciliation items",
                }
            )
        site_reports.append(
            {
                "site": site,
                "status": "ATTENTION" if issues else "OK",
                "issues": issues,
                "rollout_mode": rollout.get("mode", "SHADOW"),
                "backfill_complete": bool(
                    (rollout.get("backfill") or {}).get("complete")
                ),
                "last_run_id": last_run_id,
                "last_run_at": last_run_at,
                "run_age_hours": run_age,
                "queue_path": str((queue or {}).get("_path") or ""),
                "registry_queue_items": registry_queue_items,
                "sheet_sync_status": sheet_record.get("status", ""),
                "publication_outbox_count": outbox_count,
                "validation_errors": validation_errors,
            }
        )
    report = {
        "checked_at_kst": selected_now.astimezone(KST).isoformat(),
        "status": (
            "ATTENTION"
            if any(item["status"] != "OK" for item in site_reports)
            else "OK"
        ),
        "sites": site_reports,
    }
    report["fingerprint"] = sha256(
        json.dumps(
            [
                {
                    "site": item["site"],
                    "issues": [issue["code"] for issue in item["issues"]],
                }
                for item in site_reports
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return report


def build_message(report: dict) -> str:
    title = (
        "[Topic Intelligence] 운영 점검 정상"
        if report.get("status") == "OK"
        else "[Topic Intelligence] 운영 점검 필요"
    )
    lines = [title, f"- 확인: {report.get('checked_at_kst')}"]
    for site in report.get("sites") or []:
        codes = ", ".join(issue["code"] for issue in site.get("issues") or [])
        lines.append(
            f"- {site.get('site')}: {site.get('status')}"
            + (f" ({codes})" if codes else "")
        )
    return "\n".join(lines)


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def run(
    *,
    root: Path = DEFAULT_ROOT,
    sites: list[str] | None = None,
    notify: bool = False,
    max_run_age_hours: float = DEFAULT_MAX_RUN_AGE_HOURS,
) -> dict:
    selected_sites = sites or sorted(SITE_PROFILES)
    store = TopicStore(root)
    report = build_monitor_report(
        store,
        selected_sites,
        max_run_age_hours=max_run_age_hours,
    )
    previous = _read_json(MONITOR_STATE)
    changed = previous.get("fingerprint") != report["fingerprint"]
    recovered = previous.get("status") == "ATTENTION" and report["status"] == "OK"
    report["notification_changed"] = changed
    report["recovered"] = recovered
    TopicStore._atomic_write(MONITOR_REPORT, report)
    TopicStore._atomic_write(
        MONITOR_STATE,
        {
            "status": report["status"],
            "fingerprint": report["fingerprint"],
            "updated_at": report["checked_at_kst"],
        },
    )
    if notify and (changed or recovered):
        NotificationClient(load_settings(selected_sites[-1])).send_required(
            build_message(report)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitor topic research, queue provenance, and sync ledgers"
    )
    parser.add_argument("--site", choices=sorted(SITE_PROFILES), action="append")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--max-run-age-hours",
        type=float,
        default=DEFAULT_MAX_RUN_AGE_HOURS,
    )
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    report = run(
        root=args.root,
        sites=args.site,
        notify=args.notify,
        max_run_age_hours=args.max_run_age_hours,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
