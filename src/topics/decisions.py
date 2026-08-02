from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
from typing import Any

from src.topics.models import ProposalStatus
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.schema import validate_sheet_decision_bundle
from src.topics.store import TopicStore


FORMULA_PREFIXES = ("=", "+", "-", "@")
ALLOWED_TOPIC_DECISIONS = {"HOLD", "REJECT", "PRIORITY_OVERRIDE", "NOTES"}
PREPUBLICATION_DECISION_STATUSES = {
    TopicStatus.DISCOVERED,
    TopicStatus.REVIEW,
    TopicStatus.READY,
    TopicStatus.HOLD,
    TopicStatus.STALE,
}


def _contains_formula_payload(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith(FORMULA_PREFIXES)
    if isinstance(value, list):
        return any(_contains_formula_payload(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_formula_payload(key) or _contains_formula_payload(item)
            for key, item in value.items()
        )
    return False


def _apply_sheet_decisions_mutating(
    store: TopicStore,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Apply a narrow, revision-checked decision allowlist.

    The entire bundle is prevalidated before the first mutation.  Category or
    Blogger-label changes are deliberately absent; those require a separately
    approved monthly proposal.
    """

    validate_sheet_decision_bundle(bundle)
    site = str(bundle.get("site") or "")
    if not site:
        raise ValueError("Sheet decision bundle requires site")
    decisions = bundle.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Sheet decision bundle requires decisions list")
    if _contains_formula_payload(bundle):
        raise ValueError("Formula-like payload is not allowed in Sheet decisions")

    seen: set[str] = set()
    prepared_topics: list[tuple[TopicRecord, int]] = []
    prepared_proposals: list[tuple[str, str]] = []
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ValueError(f"decisions[{index}] must be an object")
        topic_id = str(decision.get("topic_id") or "")
        proposal_id = str(decision.get("proposal_id") or "")
        if bool(topic_id) == bool(proposal_id):
            raise ValueError(
                f"decisions[{index}] must identify exactly one topic_id or proposal_id"
            )
        entity_key = f"topic:{topic_id}" if topic_id else f"proposal:{proposal_id}"
        if entity_key in seen:
            raise ValueError(f"Duplicate decision target: {entity_key}")
        seen.add(entity_key)
        selected = str(decision.get("decision") or "").upper()

        if topic_id:
            if selected not in ALLOWED_TOPIC_DECISIONS:
                raise ValueError(f"Unsupported topic decision: {selected}")
            topic = store.get_topic(site, topic_id, resolve_aliases=False)
            if topic is None:
                raise ValueError(f"Unknown topic_id: {topic_id}")
            try:
                expected_revision = int(decision["expected_revision"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Topic decision {topic_id} requires expected_revision"
                ) from exc
            if topic.revision != expected_revision:
                raise ValueError(
                    f"Stale topic revision for {topic_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            requested_category = str(decision.get("category_id") or "")
            if requested_category and requested_category != topic.category_id:
                raise ValueError(
                    "Direct category reassignment is forbidden; submit a monthly proposal"
                )
            updated = TopicRecord.from_dict(topic.to_dict())
            if selected == "HOLD":
                if topic.status not in PREPUBLICATION_DECISION_STATUSES:
                    raise ValueError(
                        f"HOLD is forbidden for active/published topic {topic_id}"
                    )
                updated.status = TopicStatus.HOLD
                updated.status_reason = str(decision.get("reason") or "held from Sheet review")
                updated.claim_run_id = ""
            elif selected == "REJECT":
                if topic.status not in PREPUBLICATION_DECISION_STATUSES:
                    raise ValueError(
                        f"REJECT is forbidden for active/published topic {topic_id}"
                    )
                updated.status = TopicStatus.REJECTED
                updated.status_reason = str(
                    decision.get("reason") or "rejected from Sheet review"
                )
                updated.claim_run_id = ""
            elif selected == "PRIORITY_OVERRIDE":
                if topic.status not in PREPUBLICATION_DECISION_STATUSES:
                    raise ValueError(
                        f"Priority override is forbidden for active/published topic {topic_id}"
                    )
                try:
                    score = float(decision["priority_override"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Priority decision {topic_id} requires priority_override"
                    ) from exc
                if not 0 <= score <= 100:
                    raise ValueError("priority_override must be between 0 and 100")
                updated.priority_override = round(score, 2)
                updated.priority_score = round(score, 2)
                if updated.status is TopicStatus.READY and score < 20:
                    updated.status = TopicStatus.HOLD
                    updated.status_reason = "priority override is below READY threshold"
            elif selected == "NOTES":
                note = str(decision.get("notes") or "").strip()
                if not note:
                    raise ValueError(f"Notes decision {topic_id} requires notes")
                updated.editor_notes = list(
                    dict.fromkeys([*updated.editor_notes, note])
                )
            prepared_topics.append((updated, expected_revision))
        else:
            if selected not in {"APPROVE", "REJECT"}:
                raise ValueError("Proposal decisions only allow APPROVE or REJECT")
            proposal = store.get_monthly_proposal(site, proposal_id)
            if proposal is None:
                raise ValueError(f"Unknown proposal_id: {proposal_id}")
            if proposal.status is not ProposalStatus.PROPOSED:
                raise ValueError(
                    f"Proposal {proposal_id} is not PROPOSED ({proposal.status.value})"
                )
            reviewed_by = str(decision.get("reviewed_by") or "").strip()
            reason = str(decision.get("reason") or "").strip()
            if not reviewed_by or not reason:
                raise ValueError("Proposal decision requires reviewed_by and reason")
            prepared_proposals.append((proposal_id, f"{selected}:{reviewed_by}:{reason}"))

    applied: list[dict[str, Any]] = []
    for topic, revision in prepared_topics:
        saved = store.upsert_topic(site, topic, expected_revision=revision)
        applied.append(
            {
                "topic_id": saved.topic_id,
                "revision": saved.revision,
                "status": saved.status.value,
            }
        )
    for proposal_id, encoded in prepared_proposals:
        selected, reviewed_by, reason = encoded.split(":", 2)
        saved = (
            store.approve_monthly_proposal(site, proposal_id, reviewed_by, reason)
            if selected == "APPROVE"
            else store.reject_monthly_proposal(site, proposal_id, reviewed_by, reason)
        )
        applied.append(
            {
                "proposal_id": saved.proposal_id,
                "status": saved.status.value,
                "reviewed_by": saved.approved_by,
                "reason": reason,
            }
        )
    return {"site": site, "applied_count": len(applied), "applied": applied}


def apply_sheet_decisions(
    store: TopicStore,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    validate_sheet_decision_bundle(bundle)
    site = str(bundle["site"])
    base_registry = store._load_registry(site)
    base_revision = int(base_registry.get("revision") or 0)
    base_proposals = store._load_proposals(site)
    with tempfile.TemporaryDirectory(prefix="sheet-decision-stage-") as directory:
        staging_root = Path(directory) / "topics"
        source_site = store.site_dir(site)
        if source_site.exists():
            shutil.copytree(source_site, staging_root / site)
        staged = TopicStore(staging_root)
        report = _apply_sheet_decisions_mutating(staged, deepcopy(bundle))
        errors = [
            issue.to_dict()
            for issue in staged.validate_site(site)
            if issue.severity == "ERROR"
        ]
        if errors:
            raise ValueError(f"Sheet decisions failed staged validation: {errors}")
        with store._lock(site):
            current_revision = int(store._load_registry(site).get("revision") or 0)
            if current_revision != base_revision or store._load_proposals(site) != base_proposals:
                raise ValueError(
                    "Topic registry changed during Sheet decision staging; retry"
                )
            for source, target in (
                (staged.registry_path(site), store.registry_path(site)),
                (staged.inbox_path(site), store.inbox_path(site)),
                (staged.categories_path(site), store.categories_path(site)),
                (staged.proposals_path(site), store.proposals_path(site)),
            ):
                payload = staged._read_json(source, {})
                store._atomic_write(target, payload)
        return report
