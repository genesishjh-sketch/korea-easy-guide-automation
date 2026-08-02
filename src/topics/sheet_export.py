from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any
from typing import Protocol

from src.topics.monthly import build_monthly_review
from src.topics.models import TopicStatus
from src.topics.sheet_sync import load_sheet_sync_state
from src.topics.store import TopicStore
from src.topics.validation import evidence_gate


SHEET_EXPORT_FILENAME = "sheet_export.json"
FORMULA_PREFIXES = ("=", "+", "-", "@")
ALLOWED_QUESTION_FIELDS = (
    "question_id",
    "site",
    "source",
    "source_item_id",
    "url",
    "title",
    "summary",
    "created_at",
    "collected_at",
    "engagement",
    "content_hash",
    "evidence_type",
    "verification_method",
    "verified_at",
    "verified_by",
    "property_id",
    "topic_id",
    "aliases",
)


class SheetAdapter(Protocol):
    """External adapters may upsert this snapshot; the core never calls Sheets."""

    def upsert_topic_board(self, payload: dict[str, Any], *, dry_run: bool) -> Any:
        ...


def formula_safe(value: Any) -> Any:
    if isinstance(value, str):
        return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value
    if isinstance(value, list):
        return [formula_safe(item) for item in value]
    if isinstance(value, tuple):
        return [formula_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): formula_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return value


def build_sheet_export(
    store: TopicStore,
    sites: list[str],
) -> dict[str, Any]:
    dashboard: list[dict[str, Any]] = []
    topic_rows: list[dict[str, Any]] = []
    question_rows: list[dict[str, Any]] = []
    category_rows: list[dict[str, Any]] = []
    monthly_review: list[dict[str, Any]] = []
    publication_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []

    for site in sorted(set(sites)):
        topics = store.list_topics(site)
        questions = store.list_questions(site)
        questions_by_id = {item.question_id: item for item in questions}
        categories = {item.category_id: item for item in store.list_categories(site)}
        clusters = {item.cluster_id: item for item in store.list_clusters(site)}
        topics_by_id = {item.topic_id: item for item in topics}
        rollout = store.get_rollout_state(site)
        sheet_sync_runs = load_sheet_sync_state(store, site)["runs"]
        status_counts = Counter(topic.status.value for topic in topics)
        dashboard.append(
            {
                "site": site,
                "topic_count": len(topics),
                "ready_count": status_counts.get("READY", 0),
                "published_count": status_counts.get("PUBLISHED", 0),
                "live_unverified_count": status_counts.get("LIVE_UNVERIFIED", 0),
                "question_count": len(questions),
                "eligible_question_count": sum(
                    1 for question in questions if question.eligible_evidence
                ),
                "publication_count": sum(len(topic.publications) for topic in topics),
                "rollout_mode": rollout.get("mode", "SHADOW"),
                "qualifying_runs": rollout.get("consecutive_qualifying_runs", 0),
                "publication_outbox_count": len(store.list_publication_outbox(site)),
                "sheet_sync_pending_count": sum(
                    1
                    for record in sheet_sync_runs.values()
                    if record.get("pending") is True
                ),
                "cluster_count": len(clusters),
                "monthly_summary": build_monthly_review(store, site),
            }
        )
        for topic in sorted(topics, key=lambda item: item.topic_id):
            linked_questions = [
                questions_by_id[question_id]
                for question_id in topic.question_ids
                if question_id in questions_by_id
            ]
            gate = evidence_gate(topic, linked_questions)
            primary = next(
                (item for item in topic.publications if item.primary),
                topic.publications[0] if topic.publications else None,
            )
            category = categories.get(topic.category_id)
            cluster = clusters.get(topic.cluster_id)
            topic_rows.append(
                {
                    "topic_id": topic.topic_id,
                    "site": site,
                    "cluster_id": topic.cluster_id,
                    "cluster_problem_signature": (
                        cluster.problem_signature if cluster else ""
                    ),
                    "cluster_aliases": list(cluster.aliases) if cluster else [],
                    "cluster_observation_run_ids": (
                        list(cluster.observation_run_ids) if cluster else []
                    ),
                    "category_id": topic.category_id,
                    "category_name": category.name if category else "",
                    "blogger_label": category.blogger_label if category else "",
                    "canonical_title": topic.canonical_title,
                    "canonical_intent": topic.canonical_intent,
                    "problem_signature": topic.problem_signature,
                    "action": topic.action.value,
                    "topic_action": topic.action.value,
                    "status": topic.status.value,
                    "user_decision": (
                        "HOLD"
                        if topic.status is TopicStatus.HOLD
                        else "REJECT"
                        if topic.status is TopicStatus.REJECTED
                        else "AUTO"
                    ),
                    "priority_score": topic.priority_score,
                    "priority_override": topic.priority_override,
                    "priority_components": deepcopy(topic.priority_components),
                    "notes": "\n".join(topic.editor_notes),
                    "independent_evidence_count": gate.independent_evidence_count,
                    "evidence_count": gate.independent_evidence_count,
                    "evidence_gate_passed": gate.passed,
                    "evidence_exception_used": gate.exception_used,
                    "question_count": len(topic.question_ids),
                    "primary_publication_url": primary.url if primary else "",
                    "published_url": primary.url if primary else "",
                    "primary_blogger_post_id": primary.blogger_post_id if primary else "",
                    "published_post_id": primary.blogger_post_id if primary else "",
                    "editor_brief": topic.editor_brief,
                    "editor_notes": list(topic.editor_notes),
                    "reader_questions": list(topic.reader_questions),
                    "difference_from_existing": topic.difference_from_existing,
                    "severity_score": topic.severity_score,
                    "severity_reason": topic.severity_reason,
                    "official_source_urls": list(topic.official_source_urls),
                    "official_source_refs": deepcopy(topic.official_source_refs),
                    "official_answerable": topic.official_answerable,
                    "auditor_decision": topic.auditor_decision,
                    "auditor_reasons": list(topic.auditor_reasons),
                    "audited_at": topic.audited_at,
                    "duplicate_candidate_ids": list(topic.duplicate_candidate_ids),
                    "aliases": list(topic.aliases),
                    "revision": topic.revision,
                    "status_reason": topic.status_reason,
                    "created_at": topic.created_at,
                    "updated_at": topic.updated_at,
                    "last_validated_at": topic.last_validated_at,
                }
            )
            for publication in sorted(
                topic.publications,
                key=lambda item: (item.blogger_post_id, item.url),
            ):
                publication_rows.append(
                    {
                        "site": site,
                        "topic_id": topic.topic_id,
                        **publication.to_dict(),
                        "posted_at": publication.published_at,
                        "verified_at": publication.last_verified_at,
                        "sync_status": (
                            "VERIFIED"
                            if publication.last_verified_at
                            else "UNVERIFIED"
                        ),
                    }
                )
        for question in sorted(questions, key=lambda item: item.question_id):
            raw = question.to_dict()
            row = {field: deepcopy(raw.get(field)) for field in ALLOWED_QUESTION_FIELDS}
            linked_topic = topics_by_id.get(question.topic_id)
            row.update(
                {
                    "cluster_id": linked_topic.cluster_id if linked_topic else "",
                    "posted_at": question.created_at,
                    "comment_count": question.engagement.get("comments", 0),
                    "engagement_score": max(
                        question.engagement.values(),
                        default=0,
                    ),
                    "verified": question.eligible_evidence,
                }
            )
            question_rows.append(row)
        for category in sorted(categories.values(), key=lambda item: item.category_id):
            category_topics = [
                topic for topic in topics if topic.category_id == category.category_id
            ]
            category_rows.append(
                {
                    **category.to_dict(),
                    "active_clusters": len(
                        {
                            topic.cluster_id
                            for topic in category_topics
                            if topic.status.value not in {"MERGED", "REJECTED"}
                        }
                    ),
                    "ready_published_topics": sum(
                        1
                        for topic in category_topics
                        if topic.status.value
                        in {"READY", "PUBLISHED"}
                    ),
                }
            )
        for proposal in store.list_monthly_proposals(site):
            affected_ids = sorted(
                {
                    str(value)
                    for key, value in proposal.payload.items()
                    if key.endswith("_id") and value
                }
                | {
                    str(item)
                    for key, value in proposal.payload.items()
                    if key.endswith("_ids") and isinstance(value, list)
                    for item in value
                }
            )
            monthly_review.append(
                {
                    "proposal_id": proposal.proposal_id,
                    "site": site,
                    "kind": proposal.kind.value,
                    "proposal_type": proposal.kind.value,
                    "affected_ids": affected_ids,
                    "payload": deepcopy(proposal.payload),
                    "current_value": deepcopy(
                        proposal.payload.get("current_value")
                        or proposal.payload.get("from")
                        or ""
                    ),
                    "proposed_value": deepcopy(
                        proposal.payload.get("proposed_value")
                        or proposal.payload.get("to")
                        or proposal.payload.get("category")
                        or proposal.payload.get("new_categories")
                        or ""
                    ),
                    "evidence_summary": str(
                        proposal.payload.get("evidence_summary") or ""
                    ),
                    "impact": str(proposal.payload.get("impact") or ""),
                    "reason": proposal.reason,
                    "status": proposal.status.value,
                    "approval": (
                        "PENDING"
                        if proposal.status.value == "PROPOSED"
                        else proposal.status.value
                    ),
                    "approved_by": proposal.approved_by,
                    "reviewer_notes": proposal.reviewer_notes,
                    "snapshot_path": proposal.snapshot_path,
                    "rollback_path": proposal.rollback_path,
                    "rollback_audit_path": proposal.rollback_audit_path,
                    "label_sync_snapshot_path": proposal.label_sync_snapshot_path,
                    "publication_sync_pending": proposal.publication_sync_pending,
                    "created_at": proposal.created_at,
                    "approved_at": proposal.approved_at,
                    "applied_at": proposal.applied_at,
                    "rolled_back_at": proposal.rolled_back_at,
                }
            )
        recent_by_id = {
            str(item.get("run_id") or ""): item
            for item in rollout.get("recent_runs") or []
        }
        archived_run_ids: set[str] = set()
        for bundle in store.list_run_archives(site):
            run_id = str(bundle.get("run_id") or "")
            archived_run_ids.add(run_id)
            rollout_run = recent_by_id.get(run_id, {})
            rollout_details = dict(rollout_run.get("details") or {})
            sheet_sync = dict(sheet_sync_runs.get(run_id) or {})
            eligible_count = sum(
                1
                for question in bundle.get("questions") or []
                if question.get("evidence_type")
                in {"OBSERVED_QUESTION", "FIRST_PARTY_QUERY"}
            )
            run_rows.append(
                {
                    "site": site,
                    "run_id": run_id,
                    "run_at": bundle.get("started_at", ""),
                    "status": (
                        "DEGRADED"
                        if bundle.get("degraded")
                        else "SUCCESS"
                    ),
                    "qualifying": bool(rollout_run.get("qualifying")),
                    "mode_after": rollout_run.get("mode_after", ""),
                    "run_type": bundle.get("run_type", ""),
                    "started_at": bundle.get("started_at", ""),
                    "ended_at": bundle.get("ended_at", ""),
                    "stop_condition": bundle.get("stop_condition", ""),
                    "checkpoint": deepcopy(bundle.get("checkpoint") or {}),
                    "verified_questions": eligible_count,
                    # A research bundle may revisit existing clusters. Prefer
                    # the import result so this reports actual creations,
                    # rather than every cluster received in the bundle.
                    "new_clusters": rollout_details.get(
                        "new_clusters",
                        len(bundle.get("clusters") or []),
                    ),
                    "ready_topics": sum(
                        1
                        for topic in bundle.get("topics") or []
                        if topic.get("status") == "READY"
                    ),
                    "unexplored_scope": deepcopy(
                        bundle.get("unexplored_scope") or []
                    ),
                    "sheet_sync_status": bundle.get(
                        "sheet_sync_status",
                        "PENDING",
                    ),
                    "sheet_sync_pending": sheet_sync.get(
                        "pending",
                        str(
                            bundle.get("sheet_sync_status") or "PENDING"
                        ).upper()
                        != "SUCCESS",
                    ),
                    "sheet_sync_error": sheet_sync.get("last_error", ""),
                    "rollout_mode": rollout_run.get("mode_after", ""),
                }
            )
            run_rows[-1]["sheet_sync_status"] = sheet_sync.get(
                "status",
                run_rows[-1]["sheet_sync_status"],
            )
        for run in rollout.get("recent_runs") or []:
            if str(run.get("run_id") or "") in archived_run_ids:
                continue
            details = dict(run.get("details") or {})
            run_id = str(run.get("run_id") or "")
            sheet_sync = dict(sheet_sync_runs.get(run_id) or {})
            run_rows.append(
                {
                    "site": site,
                    **deepcopy(run),
                    "run_type": details.get("run_type", ""),
                    "started_at": details.get("started_at", ""),
                    "ended_at": details.get("ended_at", ""),
                    "stop_condition": details.get("stop_condition", ""),
                    "verified_questions": details.get("verified_questions", 0),
                    "new_clusters": details.get("new_clusters", 0),
                    "ready_topics": details.get("ready_topics", 0),
                    "unexplored_scope": details.get("unexplored_scope", []),
                    "sheet_sync_status": sheet_sync.get(
                        "status",
                        details.get("sheet_sync_status", "PENDING"),
                    ),
                    "sheet_sync_pending": sheet_sync.get(
                        "pending",
                        str(
                            details.get("sheet_sync_status") or "PENDING"
                        ).upper()
                        != "SUCCESS",
                    ),
                    "sheet_sync_error": sheet_sync.get("last_error", ""),
                    "rollout_mode": run.get("mode_after", ""),
                }
            )

    result = {
        "dashboard": dashboard,
        "topics": topic_rows,
        "questions": question_rows,
        "categories": category_rows,
        "monthly_review": monthly_review,
        "publications": publication_rows,
        "runs": sorted(
            run_rows,
            key=lambda item: (
                str(item.get("site") or ""),
                str(item.get("run_at") or ""),
                str(item.get("run_id") or ""),
            ),
        ),
    }
    return formula_safe(result)


def write_sheet_export(
    store: TopicStore,
    sites: list[str],
    output: str | Path | None = None,
) -> Path:
    path = Path(output) if output is not None else store.root / SHEET_EXPORT_FILENAME
    payload = build_sheet_export(store, sites)
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
    return path


def export_with_adapter(
    store: TopicStore,
    sites: list[str],
    adapter: SheetAdapter,
    *,
    dry_run: bool = True,
) -> Any:
    return adapter.upsert_topic_board(
        build_sheet_export(store, sites),
        dry_run=dry_run,
    )
