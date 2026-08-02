from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from typing import Iterator

from src.sites import SITE_PROFILES
from src.config import load_settings
from src.publishing.blogger import BloggerPublisher
from src.topics.blogger_labels import rollback_proposal_blogger_labels
from src.topics.blogger_labels import sync_proposal_blogger_labels
from src.topics.decisions import apply_sheet_decisions
from src.topics.migration import backfill_local_history
from src.topics.migration import import_weekly_bundle
from src.topics.migration import load_bundle
from src.topics.migration import sync_blogger_snapshot
from src.topics.models import TopicStatus
from src.topics.models import utc_now
from src.topics.research_state import ResearchCampaignStore
from src.topics.run_repair import apply_run_projection_repairs
from src.topics.run_repair import audit_run_projections
from src.topics.ids import publication_key
from src.topics.monthly import execute_monthly_reorganization
from src.topics.monthly import import_proposal_bundle
from src.topics.sheet_export import build_sheet_export
from src.topics.sheet_export import write_sheet_export
from src.topics.sheet_sync import load_sheet_sync_state
from src.topics.sheet_sync import record_sheet_sync
from src.topics.store import DEFAULT_ROOT
from src.topics.store import ROLLOUT_READY_FIRST
from src.topics.store import TopicStore


EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_BLOCKED = 2
EXIT_OPERATIONAL = 3
SITES = tuple(sorted(SITE_PROFILES))


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def _working_store(root: Path, dry_run: bool) -> Iterator[TopicStore]:
    if not dry_run:
        yield TopicStore(root)
        return
    with tempfile.TemporaryDirectory(prefix="topic-board-dry-run-") as directory:
        scratch = Path(directory) / "topics"
        if root.exists():
            shutil.copytree(root, scratch)
        yield TopicStore(scratch)


def _selected_sites(site: str | None) -> list[str]:
    return [site] if site else list(SITES)


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Topic registry root (default: data/topics)",
    )


def _add_site(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument("--site", choices=SITES, required=required)


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run against an isolated copy; do not modify the configured registry",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage the durable two-site topic registry. "
            "Blogger reconciliation is read-only unless an explicitly approved "
            "category-label sync is requested; Google Sheets remains an adapter."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser(
        "backfill",
        help="Idempotently import seed and local publication history",
    )
    _add_root(backfill)
    _add_site(backfill)
    _add_dry_run(backfill)
    backfill.add_argument(
        "--generated-root",
        type=Path,
        help="Override local data/generated root",
    )
    backfill.add_argument(
        "--question-bundle",
        type=Path,
        help="Optional schema-v1 BACKFILL_RESEARCH question/cluster bundle",
    )

    weekly = subparsers.add_parser(
        "import-bundle",
        aliases=["weekly-update"],
        help="Import a verified weekly collector/clustering JSON bundle",
    )
    _add_root(weekly)
    _add_site(weekly)
    _add_dry_run(weekly)
    weekly.add_argument("--input", type=Path, required=True)

    sync = subparsers.add_parser(
        "sync-blogger",
        aliases=["reconcile-publications", "verify-live"],
        help="Read all live Blogger posts or reconcile an adapter snapshot",
    )
    _add_root(sync)
    _add_site(sync)
    _add_dry_run(sync)
    sync.add_argument(
        "--input",
        type=Path,
        help="Optional adapter snapshot; omitted uses read-only Blogger OAuth",
    )
    sync.add_argument(
        "--create-missing",
        action="store_true",
        help="Create registry records for otherwise unmatched Blogger posts",
    )

    queue = subparsers.add_parser(
        "build-queue",
        help="Build a priority-sorted queue after rollout and invariant gates",
    )
    _add_root(queue)
    _add_site(queue, required=True)
    _add_dry_run(queue)
    queue.add_argument("--limit", type=int, default=7)
    queue.add_argument("--output", type=Path)
    queue.add_argument(
        "--schedule",
        action="store_true",
        help="Atomically move selected READY topics to SCHEDULED",
    )

    monthly = subparsers.add_parser(
        "monthly-review",
        help="Generate category/cluster review; proposals remain PROPOSED",
    )
    _add_root(monthly)
    _add_site(monthly, required=True)
    _add_dry_run(monthly)
    monthly.add_argument("--proposal-bundle", type=Path)
    monthly.add_argument("--output", type=Path)
    monthly.add_argument(
        "--as-of",
        help="Optional ISO timestamp used for the rolling 12-month boundary",
    )

    apply_proposal = subparsers.add_parser(
        "apply-category-proposal",
        help="Approve/apply or roll back one category/cluster proposal",
    )
    _add_root(apply_proposal)
    _add_site(apply_proposal, required=True)
    _add_dry_run(apply_proposal)
    apply_proposal.add_argument("--proposal-id", required=True)
    apply_proposal.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve before applying",
    )
    apply_proposal.add_argument("--approved-by")
    apply_proposal.add_argument(
        "--rollback",
        action="store_true",
        help="Restore the snapshot captured when this proposal was applied",
    )
    apply_proposal.add_argument(
        "--publication-sync-success",
        action="store_true",
        help="Acknowledge successful external Blogger label synchronization",
    )
    apply_proposal.add_argument(
        "--publication-sync-error",
        help="Record a failed external Blogger label synchronization",
    )

    label_sync = subparsers.add_parser(
        "sync-blogger-labels",
        help=(
            "Preview an approved proposal's exact Blogger label changes; "
            "--apply is required for writes"
        ),
    )
    _add_root(label_sync)
    _add_site(label_sync, required=True)
    label_sync.add_argument("--proposal-id", required=True)
    label_sync.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly execute approved old-to-new Blogger label updates",
    )
    label_sync.add_argument(
        "--rollback",
        action="store_true",
        help=(
            "Preview exact Blogger label restoration from the immutable "
            "pre-change snapshot; --apply is required for writes"
        ),
    )

    validate = subparsers.add_parser(
        "validate",
        help="Validate registry invariants, rollout mode, and optional freshness",
    )
    _add_root(validate)
    _add_site(validate)
    validate.add_argument("--max-run-age-hours", type=float)
    validate.add_argument(
        "--require-mode",
        choices=("SHADOW", "READY_FIRST", "DEGRADED"),
    )

    export = subparsers.add_parser(
        "export-sheet",
        help="Write deterministic formula-safe JSON for a Sheets adapter",
    )
    _add_root(export)
    _add_site(export)
    _add_dry_run(export)
    export.add_argument(
        "--output",
        type=Path,
        help="Default: <root>/sheet_export.json",
    )

    sheet_sync = subparsers.add_parser(
        "record-sheet-sync",
        aliases=["ack-sheet-sync"],
        help="Durably record a weekly run's post-import Google Sheet outcome",
    )
    _add_root(sheet_sync)
    _add_site(sheet_sync, required=True)
    _add_dry_run(sheet_sync)
    sheet_sync.add_argument("--run-id", required=True)
    sheet_sync.add_argument(
        "--status",
        required=True,
        choices=("PENDING", "SUCCESS", "FAILED"),
    )
    sheet_sync.add_argument(
        "--error",
        default="",
        help="Required operational detail for FAILED; forbidden for SUCCESS",
    )

    decisions = subparsers.add_parser(
        "apply-sheet-decisions",
        help="Apply revision-checked HOLD/REJECT/priority/notes/proposal approvals",
    )
    _add_root(decisions)
    _add_dry_run(decisions)
    decisions.add_argument("--input", type=Path, required=True)

    evidence_approval = subparsers.add_parser(
        "approve-evidence-exception",
        help=(
            "Persist one explicit, revision-checked user decision allowing a "
            "single-signal recurrence exception"
        ),
    )
    _add_root(evidence_approval)
    _add_site(evidence_approval, required=True)
    _add_dry_run(evidence_approval)
    evidence_approval.add_argument("--topic-id", required=True)
    evidence_approval.add_argument("--expected-revision", type=int, required=True)
    evidence_approval.add_argument("--approved-by", required=True)
    evidence_approval.add_argument("--decision-id", required=True)
    evidence_approval.add_argument(
        "--basis",
        required=True,
        choices=(
            "INFORMATION_DENSITY",
            "ENGAGEMENT",
            "FIRST_PARTY_DEMAND",
            "OFFICIAL_ISSUE",
        ),
    )
    evidence_approval.add_argument("--reason", required=True)
    evidence_approval.add_argument("--approved-at", default="")

    research = subparsers.add_parser(
        "research-campaign",
        help="Create, inspect, claim, or checkpoint a resumable research campaign",
    )
    _add_root(research)
    _add_site(research, required=True)
    _add_dry_run(research)
    research.add_argument(
        "--action",
        required=True,
        choices=("create", "status", "claim", "checkpoint", "bundle-metadata"),
    )
    research.add_argument("--campaign-id", required=True)
    research.add_argument(
        "--input",
        type=Path,
        help="Create manifest JSON with run_type/window/logic_version/work_items",
    )
    research.add_argument("--work-id")
    research.add_argument(
        "--state",
        choices=("PENDING", "RUNNING", "PAUSED", "DONE", "BLOCKED", "SATURATED"),
    )
    research.add_argument("--cursor", default="")
    research.add_argument("--last-error", default="")
    research.add_argument("--discovered-id", action="append", default=[])

    repair_runs = subparsers.add_parser(
        "repair-run-projections",
        help=(
            "Audit immutable run archives and optionally append correction "
            "records for derived metrics"
        ),
    )
    _add_root(repair_runs)
    _add_site(repair_runs, required=True)
    repair_runs.add_argument(
        "--apply",
        action="store_true",
        help="Append correction records; archived bundles remain unchanged",
    )

    replay = subparsers.add_parser(
        "replay-outbox",
        help="Reconcile pending publication mappings and acknowledge successes",
    )
    _add_root(replay)
    _add_site(replay, required=True)
    _add_dry_run(replay)
    replay.add_argument(
        "--input",
        type=Path,
        help="Optional Blogger snapshot; omitted uses read-only Blogger OAuth",
    )
    replay.add_argument(
        "--local-outbox",
        type=Path,
        help=(
            "Optional stage2 durable fallback JSONL; default uses "
            "TOPIC_PUBLICATION_OUTBOX or data/topics/publication_sync_pending.jsonl"
        ),
    )
    replay.add_argument(
        "--sheet-acknowledged-outbox-id",
        action="append",
        default=[],
        help=(
            "Publication outbox ID confirmed written to Google Sheets. "
            "Repeat once per successfully upserted ID."
        ),
    )

    expire = subparsers.add_parser(
        "expire-scheduled",
        help="Move stale SCHEDULED topics to STALE",
    )
    _add_root(expire)
    _add_site(expire, required=True)
    _add_dry_run(expire)
    expire.add_argument("--older-than-hours", type=float, default=48.0)
    return parser


def _command_backfill(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        reports = [
            backfill_local_history(
                store,
                site,
                generated_root=args.generated_root,
            )
            for site in _selected_sites(args.site)
        ]
        question_report = None
        if args.question_bundle:
            bundle = load_bundle(args.question_bundle)
            if not isinstance(bundle, dict):
                raise ValueError("Backfill question bundle must be a JSON object")
            if bundle.get("run_type") != "BACKFILL_RESEARCH":
                raise ValueError("--question-bundle requires run_type BACKFILL_RESEARCH")
            bundle_site = str(bundle.get("site") or "")
            if args.site and args.site != bundle_site:
                raise ValueError("--site does not match question bundle site")
            question_report = import_weekly_bundle(store, bundle_site, bundle)
    _emit(
        {
            "dry_run": args.dry_run,
            "reports": reports,
            "question_bundle_report": question_report,
        }
    )
    return EXIT_VALIDATION if any(item["conflicts"] for item in reports) else EXIT_OK


def _command_import(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.input)
    if not isinstance(bundle, dict):
        raise ValueError("Weekly bundle must be a JSON object")
    site = args.site or str(bundle.get("site") or "")
    if site not in SITES:
        raise ValueError("--site or a valid bundle.site is required")
    with _working_store(args.root, args.dry_run) as store:
        report = import_weekly_bundle(store, site, bundle)
    _emit({"dry_run": args.dry_run, **report})
    return EXIT_OK if report["effective_status"] == "SUCCESS" else EXIT_BLOCKED


def _command_sync(args: argparse.Namespace) -> int:
    snapshots: list[tuple[str, Any]] = []
    if args.input:
        snapshot = load_bundle(args.input)
        inferred_site = (
            str(snapshot.get("site") or "") if isinstance(snapshot, dict) else ""
        )
        site = args.site or inferred_site
        if site not in SITES:
            raise ValueError("--site or snapshot.site is required with --input")
        snapshots.append((site, snapshot))
    else:
        # Fetch every requested site first. Authentication failure therefore
        # occurs before any registry mutation.
        for site in _selected_sites(args.site):
            posts = BloggerPublisher(load_settings(site)).list_live_posts(
                fetch_bodies=True
            )
            snapshots.append(
                (
                    site,
                    {
                        "site": site,
                        "source": "BLOGGER_API",
                        "authoritative_live": True,
                        "fetched_at": utc_now(),
                        "complete_snapshot": True,
                        "posts": posts,
                    },
                )
            )
    reports = []
    with _working_store(args.root, args.dry_run) as store:
        for site, snapshot in snapshots:
            reports.append(
                sync_blogger_snapshot(
                    store,
                    site,
                    snapshot,
                    create_missing=args.create_missing,
                )
            )
    _emit({"dry_run": args.dry_run, "reports": reports})
    return (
        EXIT_VALIDATION
        if any(report["conflicts"] for report in reports)
        else EXIT_OK
    )


def _queue_item(store: TopicStore, site: str, topic: Any) -> dict[str, Any]:
    category = store.get_category(site, topic.category_id)
    return {
        "topic_id": topic.topic_id,
        "revision": topic.revision,
        "site": site,
        "seed": topic.canonical_title,
        "topic": topic.canonical_title,
        "category_id": topic.category_id,
        "category": category.blogger_label if category else "",
        "action": topic.action.value,
        "priority_score": topic.priority_score,
        "status": topic.status.value,
        "editor_brief": topic.editor_brief,
        "reader_questions": list(topic.reader_questions),
        "difference_from_existing": topic.difference_from_existing,
    }


def _command_build_queue(args: argparse.Namespace) -> int:
    store = TopicStore(args.root)
    rollout = store.get_rollout_state(args.site)
    if rollout.get("mode") != ROLLOUT_READY_FIRST:
        _emit(
            {
                "site": args.site,
                "status": "BLOCKED",
                "reason": "rollout gate is not READY_FIRST",
                "rollout": rollout,
                "items": [],
            }
        )
        return EXIT_BLOCKED
    issues = [
        issue.to_dict()
        for issue in store.validate_site(args.site)
        if issue.severity == "ERROR"
    ]
    if issues:
        _emit({"site": args.site, "status": "INVALID", "issues": issues})
        return EXIT_VALIDATION

    with _working_store(args.root, args.dry_run) as working:
        topics = working.list_ready_topics(args.site, limit=args.limit)
        if args.schedule:
            scheduled = []
            for topic in topics:
                scheduled.append(
                    working.mark_topic_status(
                        args.site,
                        topic.topic_id,
                        TopicStatus.SCHEDULED,
                        "selected by topic-board queue",
                        expected_revision=topic.revision,
                    )
                )
            topics = scheduled
        items = [_queue_item(working, args.site, topic) for topic in topics]
        payload = {
            "site": args.site,
            "status": "READY",
            "rollout_mode": working.get_rollout_mode(args.site),
            "scheduled": bool(args.schedule),
            "items": items,
        }
        if args.output and not args.dry_run:
            _atomic_json(args.output, payload)
            payload["output"] = str(args.output)
    _emit({"dry_run": args.dry_run, **payload})
    return EXIT_OK


def _command_monthly(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        imported: list[dict[str, Any]] = []
        if args.proposal_bundle:
            bundle = load_bundle(args.proposal_bundle)
            if not isinstance(bundle, dict):
                raise ValueError("Proposal bundle must be a JSON object")
            imported = import_proposal_bundle(store, args.site, bundle)
        result = execute_monthly_reorganization(
            store,
            args.site,
            as_of=args.as_of or "",
        )
        validation_errors = [
            issue.to_dict()
            for issue in store.validate_site(args.site)
            if issue.severity == "ERROR"
        ]
        if validation_errors:
            raise ValueError(
                "Monthly reorganization failed validation: "
                + json.dumps(
                    validation_errors,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        payload = {
            "site": args.site,
            "dry_run": args.dry_run,
            "imported_proposals": imported,
            **result,
        }
        if args.output and not args.dry_run:
            _atomic_json(args.output, payload)
            payload["output"] = str(args.output)
    _emit(payload)
    return EXIT_OK


def _command_apply_proposal(args: argparse.Namespace) -> int:
    selected_actions = sum(
        bool(item)
        for item in (
            args.rollback,
            args.approve,
            args.publication_sync_success,
            args.publication_sync_error,
        )
    )
    if selected_actions > 1:
        raise ValueError(
            "--rollback, --approve, and publication-sync outcomes cannot be combined"
        )
    if args.approve and not (args.approved_by or "").strip():
        raise ValueError("--approve requires --approved-by")
    with _working_store(args.root, args.dry_run) as store:
        if args.publication_sync_success or args.publication_sync_error:
            proposal = store.mark_proposal_publication_sync(
                args.site,
                args.proposal_id,
                success=args.publication_sync_success,
                error=args.publication_sync_error or "",
            )
        elif args.rollback:
            current = store.get_monthly_proposal(args.site, args.proposal_id)
            if current is None:
                raise ValueError(f"Unknown proposal: {args.proposal_id}")
            if current.label_sync_snapshot_path:
                raise ValueError(
                    "This proposal changed Blogger labels; use "
                    "sync-blogger-labels --rollback for external-first rollback"
                )
            proposal = store.rollback_monthly_proposal(args.site, args.proposal_id)
        else:
            if args.approve:
                store.approve_monthly_proposal(
                    args.site,
                    args.proposal_id,
                    args.approved_by,
                )
            current = store.get_monthly_proposal(args.site, args.proposal_id)
            if current is None:
                raise ValueError(f"Unknown proposal: {args.proposal_id}")
            if current.status.value != "APPROVED":
                _emit(
                    {
                        "site": args.site,
                        "proposal_id": args.proposal_id,
                        "status": "BLOCKED",
                        "reason": "proposal must be explicitly APPROVED",
                    }
                )
                return EXIT_BLOCKED
            proposal = store.apply_monthly_proposal(args.site, args.proposal_id)
    _emit({"dry_run": args.dry_run, "proposal": proposal.to_dict()})
    return EXIT_OK


def _command_sync_blogger_labels(args: argparse.Namespace) -> int:
    store = TopicStore(args.root)
    client = BloggerPublisher(load_settings(args.site))
    operation = (
        rollback_proposal_blogger_labels
        if args.rollback
        else sync_proposal_blogger_labels
    )
    report = operation(
        store,
        args.site,
        args.proposal_id,
        client,
        apply=args.apply,
    )
    _emit(report)
    return EXIT_OK if report.get("success") else EXIT_BLOCKED


def _freshness_issue(
    store: TopicStore,
    site: str,
    max_age_hours: float,
) -> dict[str, str] | None:
    state = store.get_rollout_state(site)
    value = str(state.get("last_run_at") or "")
    if not value:
        return {
            "severity": "ERROR",
            "code": "ROLLOUT_RUN_MISSING",
            "message": "no collector rollout run is recorded",
            "path": "rollout.last_run_at",
        }
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return {
            "severity": "ERROR",
            "code": "ROLLOUT_RUN_TIME_INVALID",
            "message": f"invalid last_run_at: {value}",
            "path": "rollout.last_run_at",
        }
    age_hours = (datetime.now(tz=timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
    if age_hours > max_age_hours:
        return {
            "severity": "ERROR",
            "code": "ROLLOUT_RUN_STALE",
            "message": f"last collector run is {age_hours:.1f}h old (max {max_age_hours:.1f}h)",
            "path": "rollout.last_run_at",
        }
    return None


def _command_validate(args: argparse.Namespace) -> int:
    store = TopicStore(args.root)
    reports = []
    has_errors = False
    for site in _selected_sites(args.site):
        issues = [item.to_dict() for item in store.validate_site(site)]
        try:
            load_sheet_sync_state(store, site)
        except ValueError as exc:
            issues.append(
                {
                    "severity": "ERROR",
                    "code": "SHEET_SYNC_STATE_INVALID",
                    "message": str(exc),
                    "path": str(store.site_dir(site) / "sheet_sync.json"),
                }
            )
        if args.max_run_age_hours is not None:
            issue = _freshness_issue(store, site, args.max_run_age_hours)
            if issue:
                issues.append(issue)
        state = store.get_rollout_state(site)
        if args.require_mode and state.get("mode") != args.require_mode:
            issues.append(
                {
                    "severity": "ERROR",
                    "code": "ROLLOUT_MODE_MISMATCH",
                    "message": f"required {args.require_mode}, found {state.get('mode')}",
                    "path": "rollout.mode",
                }
            )
        has_errors = has_errors or any(
            issue.get("severity") == "ERROR" for issue in issues
        )
        reports.append(
            {
                "site": site,
                "valid": not any(
                    issue.get("severity") == "ERROR" for issue in issues
                ),
                "rollout": state,
                "issues": issues,
            }
        )
    _emit({"valid": not has_errors, "reports": reports})
    return EXIT_VALIDATION if has_errors else EXIT_OK


def _command_export(args: argparse.Namespace) -> int:
    sites = _selected_sites(args.site)
    store = TopicStore(args.root)
    if args.dry_run:
        payload = build_sheet_export(store, sites)
        _emit(
            {
                "dry_run": True,
                "sites": sites,
                "row_counts": {
                    key: len(value) if isinstance(value, list) else 0
                    for key, value in payload.items()
                },
                "output": None,
            }
        )
        return EXIT_OK
    path = write_sheet_export(store, sites, args.output)
    payload = build_sheet_export(store, sites)
    _emit(
        {
            "dry_run": False,
            "sites": sites,
            "row_counts": {
                key: len(value) if isinstance(value, list) else 0
                for key, value in payload.items()
            },
            "output": str(path),
        }
    )
    return EXIT_OK


def _command_record_sheet_sync(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        record = record_sheet_sync(
            store,
            args.site,
            args.run_id,
            args.status,
            error=args.error,
        )
    _emit(
        {
            "dry_run": args.dry_run,
            "site": args.site,
            "sheet_sync": record,
        }
    )
    return EXIT_OK


def _command_apply_sheet_decisions(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.input)
    if not isinstance(bundle, dict):
        raise ValueError("Sheet decision bundle must be a JSON object")
    with _working_store(args.root, args.dry_run) as store:
        report = apply_sheet_decisions(store, bundle)
    _emit({"dry_run": args.dry_run, **report})
    return EXIT_OK


def _command_approve_evidence_exception(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        topic = store.approve_evidence_exception(
            args.site,
            args.topic_id,
            approved_by=args.approved_by,
            reason=args.reason,
            basis=args.basis,
            decision_id=args.decision_id,
            expected_revision=args.expected_revision,
            approved_at=args.approved_at,
        )
    _emit(
        {
            "dry_run": args.dry_run,
            "site": args.site,
            "topic_id": topic.topic_id,
            "topic_revision": topic.revision,
            "evidence_exception": topic.evidence_exception,
        }
    )
    return EXIT_OK


def _command_research_campaign(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        campaigns = ResearchCampaignStore(store)
        if args.action == "create":
            if args.input is None:
                raise ValueError("research-campaign create requires --input")
            manifest = load_bundle(args.input)
            if not isinstance(manifest, dict):
                raise ValueError("research campaign manifest must be an object")
            result = campaigns.create(
                args.site,
                args.campaign_id,
                run_type=str(manifest.get("run_type") or ""),
                window_start=str(manifest.get("window_start") or ""),
                window_end=str(manifest.get("window_end") or ""),
                logic_version=str(manifest.get("logic_version") or ""),
                work_items=list(manifest.get("work_items") or []),
            )
        elif args.action == "status":
            result = campaigns.status(args.site, args.campaign_id)
        elif args.action == "claim":
            result = campaigns.claim_next(args.site, args.campaign_id)
        elif args.action == "bundle-metadata":
            result = campaigns.bundle_metadata(args.site, args.campaign_id)
        else:
            if not args.work_id or not args.state:
                raise ValueError(
                    "research-campaign checkpoint requires --work-id and --state"
                )
            result = campaigns.checkpoint(
                args.site,
                args.campaign_id,
                args.work_id,
                state=args.state,
                cursor=args.cursor,
                last_error=args.last_error,
                discovered_ids=list(args.discovered_id or []),
            )
    _emit(
        {
            "dry_run": args.dry_run,
            "site": args.site,
            "campaign_id": args.campaign_id,
            "action": args.action,
            "result": result,
        }
    )
    return EXIT_OK


def _command_repair_run_projections(args: argparse.Namespace) -> int:
    store = TopicStore(args.root)
    report = (
        apply_run_projection_repairs(store, args.site)
        if args.apply
        else audit_run_projections(store, args.site)
    )
    _emit({"applied": bool(args.apply), **report})
    return EXIT_OK


def _command_replay_outbox(args: argparse.Namespace) -> int:
    if args.input:
        snapshot = load_bundle(args.input)
    else:
        snapshot = {
            "site": args.site,
            "source": "BLOGGER_API",
            "authoritative_live": True,
            "fetched_at": utc_now(),
            "complete_snapshot": True,
            "posts": BloggerPublisher(
                load_settings(args.site)
            ).list_live_posts(fetch_bodies=True),
        }
    sheet_acknowledged = set(
        snapshot.get("sheet_acknowledged_outbox_ids") or []
        if isinstance(snapshot, dict)
        else []
    )
    sheet_acknowledged.update(
        str(item)
        for item in (
            getattr(args, "sheet_acknowledged_outbox_id", None) or []
        )
        if str(item).strip()
    )
    with _working_store(args.root, args.dry_run) as store:
        from src.pipeline.stage2_publish import replay_local_publication_outbox

        local_report = replay_local_publication_outbox(
            store,
            args.site,
            path=getattr(args, "local_outbox", None),
            consume=not args.dry_run,
        )
        before = store.list_publication_outbox(args.site)
        sync_report = sync_blogger_snapshot(store, args.site, snapshot)
        acknowledged = []
        for entry in before:
            topic = store.get_topic(args.site, str(entry.get("topic_id") or ""))
            key = str(entry.get("publication_key") or "")
            mapped = topic and any(
                publication_key(item.blogger_post_id, item.url) == key
                for item in topic.publications
            )
            outbox_id = str(entry.get("outbox_id") or "")
            if mapped and outbox_id in sheet_acknowledged:
                store.mark_publication_outbox_stage(
                    args.site,
                    outbox_id,
                    "sheet",
                    success=True,
                )
                if store.acknowledge_publication_sync(args.site, outbox_id):
                    acknowledged.append(outbox_id)
        remaining = store.list_publication_outbox(args.site)
    _emit(
        {
            "dry_run": args.dry_run,
            "site": args.site,
            "local_outbox": local_report,
            "sync": sync_report,
            "acknowledged": acknowledged,
            "remaining": len(remaining),
        }
    )
    return EXIT_OK if not sync_report["conflicts"] else EXIT_VALIDATION


def _command_expire_scheduled(args: argparse.Namespace) -> int:
    with _working_store(args.root, args.dry_run) as store:
        expired = store.expire_stale_scheduled(
            args.site,
            args.older_than_hours,
        )
    _emit(
        {
            "dry_run": args.dry_run,
            "site": args.site,
            "expired_topic_ids": [item.topic_id for item in expired],
        }
    )
    return EXIT_OK


COMMANDS = {
    "backfill": _command_backfill,
    "import-bundle": _command_import,
    "weekly-update": _command_import,
    "sync-blogger": _command_sync,
    "reconcile-publications": _command_sync,
    "verify-live": _command_sync,
    "build-queue": _command_build_queue,
    "monthly-review": _command_monthly,
    "apply-category-proposal": _command_apply_proposal,
    "sync-blogger-labels": _command_sync_blogger_labels,
    "validate": _command_validate,
    "export-sheet": _command_export,
    "record-sheet-sync": _command_record_sheet_sync,
    "ack-sheet-sync": _command_record_sheet_sync,
    "apply-sheet-decisions": _command_apply_sheet_decisions,
    "approve-evidence-exception": _command_approve_evidence_exception,
    "research-campaign": _command_research_campaign,
    "repair-run-projections": _command_repair_run_projections,
    "replay-outbox": _command_replay_outbox,
    "expire-scheduled": _command_expire_scheduled,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _emit(
            {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return EXIT_OPERATIONAL


if __name__ == "__main__":
    sys.exit(main())
