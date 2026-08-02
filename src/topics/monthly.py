from __future__ import annotations

from collections import Counter
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import re
import tempfile
from typing import Any

from src.topics.ids import normalize_text
from src.topics.models import ProposalKind
from src.topics.models import ProposalStatus
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.schema import validate_monthly_proposal_bundle
from src.topics.store import TopicStore
from src.topics.validation import topic_similarity


REVIEW_WINDOW_DAYS = 365
PUBLISHED_STATUSES = {
    TopicStatus.PUBLISHED,
    TopicStatus.LIVE_UNVERIFIED,
}
EXCLUDED_STATUSES = {
    TopicStatus.MERGED,
    TopicStatus.REJECTED,
}
IDENTITY_PATTERNS = (
    re.compile(r"\b0x[0-9a-f]{4,}\b", re.IGNORECASE),
    re.compile(r"\b(?:kb|err(?:or)?[- _]?)[0-9]{3,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:windows|android|ios|macos)\s+(?:version\s+)?[0-9]+(?:\.[0-9]+)*\b",
        re.IGNORECASE,
    ),
)
IDENTITY_TERMS = (
    "seollal",
    "chuseok",
    "lunar new year",
    "korean thanksgiving",
)
IDENTITY_ENTITIES = {
    "component:file-explorer": ("file explorer",),
    "component:microsoft-store": ("microsoft store", "windows store"),
    "component:onedrive": ("onedrive", "one drive"),
    "component:photos-app": ("photos app", "microsoft photos"),
    "component:windows-update": ("windows update",),
    "resource:cpu": ("cpu",),
    "resource:disk": ("disk",),
    "resource:gpu": ("gpu",),
    "resource:memory": ("memory", "ram"),
}


def _as_utc(value: str, *, fallback: datetime | None = None) -> datetime | None:
    selected = str(value or "").strip()
    if not selected:
        return fallback
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(selected[:10])
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _identity_tokens(topic: TopicRecord) -> set[str]:
    material = " ".join(
        value
        for value in (
            topic.problem_signature,
            topic.canonical_intent,
            topic.canonical_title,
            *topic.aliases,
        )
        if value
    )
    normalized = normalize_text(material)
    tokens = {
        normalize_text(match.group(0))
        for pattern in IDENTITY_PATTERNS
        for match in pattern.finditer(material)
    }
    tokens.update(
        f"entity:{term}"
        for term in IDENTITY_TERMS
        if term in normalized
    )
    tokens.update(
        f"entity:{entity}"
        for entity, aliases in IDENTITY_ENTITIES.items()
        if any(
            re.search(
                rf"(?:^|\s){re.escape(normalize_text(alias))}(?:$|\s)",
                normalized,
            )
            for alias in aliases
        )
    )
    return tokens


def _exact_identity_values(topic: TopicRecord) -> set[str]:
    return {
        normalize_text(value)
        for value in (
            topic.problem_signature,
            topic.canonical_intent,
            topic.canonical_title,
            *topic.aliases,
        )
        if normalize_text(value)
    }


def _has_identity_conflict(left: TopicRecord, right: TopicRecord) -> bool:
    left_tokens = _identity_tokens(left)
    right_tokens = _identity_tokens(right)
    return bool(left_tokens or right_tokens) and left_tokens != right_tokens


def _recent_scope(
    store: TopicStore,
    site: str,
    as_of: datetime,
) -> tuple[list[TopicRecord], set[str], set[str]]:
    cutoff = as_of - timedelta(days=REVIEW_WINDOW_DAYS)
    questions = store.list_questions(site)
    recent_question_ids = {
        question.question_id
        for question in questions
        if question.eligible_evidence
        and max(
            (
                timestamp
                for timestamp in (
                    _as_utc(question.created_at),
                    _as_utc(question.collected_at),
                )
                if timestamp is not None
            ),
            default=datetime.min.replace(tzinfo=timezone.utc),
        )
        >= cutoff
    }
    recent_run_ids: set[str] = set()
    for bundle in store.list_run_archives(site):
        ended_at = _as_utc(
            str(
                bundle.get("ended_at")
                or bundle.get("started_at")
                or bundle.get("run_at")
                or ""
            )
        )
        if ended_at is not None and ended_at >= cutoff:
            recent_run_ids.add(str(bundle.get("run_id") or ""))

    clusters = store.list_clusters(site, include_merged=False)
    recent_cluster_ids = {
        cluster.cluster_id
        for cluster in clusters
        if set(cluster.question_ids) & recent_question_ids
        or set(cluster.observation_run_ids) & recent_run_ids
    }
    all_topics = store.list_topics(site)
    scoped_topics = [
        topic
        for topic in all_topics
        if topic.publications
        or set(topic.question_ids) & recent_question_ids
        or topic.cluster_id in recent_cluster_ids
    ]
    return scoped_topics, recent_question_ids, recent_cluster_ids


def build_monthly_review(
    store: TopicStore,
    site: str,
    *,
    as_of: str = "",
) -> dict[str, Any]:
    selected_as_of = _as_utc(as_of) or datetime.now(tz=timezone.utc)
    window_start = selected_as_of - timedelta(days=REVIEW_WINDOW_DAYS)
    all_topics = store.list_topics(site)
    all_questions = store.list_questions(site)
    topics, recent_question_ids, recent_cluster_ids = _recent_scope(
        store,
        site,
        selected_as_of,
    )
    categories = {item.category_id: item for item in store.list_categories(site)}
    proposals = store.list_monthly_proposals(site)
    all_clusters = store.list_clusters(site)
    scoped_cluster_ids = {
        topic.cluster_id for topic in topics if topic.cluster_id
    } | recent_cluster_ids
    clusters = [
        cluster
        for cluster in all_clusters
        if cluster.cluster_id in scoped_cluster_ids
    ]
    status_counts = Counter(topic.status.value for topic in topics)
    action_counts = Counter(topic.action.value for topic in topics)
    category_counts = Counter(topic.category_id for topic in topics)

    duplicate_pairs: list[dict[str, Any]] = []
    excluded_identity_conflicts: list[dict[str, Any]] = []
    active = [
        topic
        for topic in topics
        if topic.status not in EXCLUDED_STATUSES
    ]
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            similarity = topic_similarity(left, right)
            if similarity < 0.86:
                continue
            if _has_identity_conflict(left, right):
                excluded_identity_conflicts.append(
                    {
                        "left_topic_id": left.topic_id,
                        "right_topic_id": right.topic_id,
                        "similarity": similarity,
                        "reason": "identity-critical tokens differ",
                        "left_identity_tokens": sorted(_identity_tokens(left)),
                        "right_identity_tokens": sorted(_identity_tokens(right)),
                    }
                )
                continue
            has_publication = bool(left.publications or right.publications)
            exact_identity = bool(
                _exact_identity_values(left) & _exact_identity_values(right)
            )
            if not has_publication and exact_identity:
                decision = "AUTO_MERGE"
            elif has_publication:
                decision = "PROPOSAL_REQUIRED"
            else:
                decision = "AI_REVIEW_REQUIRED"
            duplicate_pairs.append(
                {
                    "left_topic_id": left.topic_id,
                    "right_topic_id": right.topic_id,
                    "left_cluster_id": left.cluster_id,
                    "right_cluster_id": right.cluster_id,
                    "similarity": similarity,
                    "exact_identity": exact_identity,
                    "published_cluster": has_publication,
                    "decision": decision,
                }
            )
    duplicate_pairs.sort(
        key=lambda item: (
            -float(item["similarity"]),
            item["left_topic_id"],
            item["right_topic_id"],
        )
    )
    excluded_identity_conflicts.sort(
        key=lambda item: (
            -float(item["similarity"]),
            item["left_topic_id"],
            item["right_topic_id"],
        )
    )
    return {
        "site": site,
        "as_of": selected_as_of.isoformat(),
        "window_start": window_start.isoformat(),
        "window_days": REVIEW_WINDOW_DAYS,
        "topic_count": len(topics),
        "total_topic_count": len(all_topics),
        "excluded_stale_unpublished_topic_count": len(all_topics) - len(topics),
        "question_count": len(recent_question_ids),
        "total_question_count": len(all_questions),
        "publication_count": sum(len(topic.publications) for topic in topics),
        "cluster_count": len(clusters),
        "total_cluster_count": len(all_clusters),
        "clusters": [
            {
                "cluster_id": cluster.cluster_id,
                "problem_signature": cluster.problem_signature,
                "canonical_label": cluster.canonical_label,
                "question_count": len(
                    set(cluster.question_ids) & recent_question_ids
                ),
                "topic_count": len(cluster.topic_ids),
                "observation_run_count": len(cluster.observation_run_ids),
                "merged_into_cluster_id": cluster.merged_into_cluster_id,
            }
            for cluster in sorted(clusters, key=lambda item: item.cluster_id)
        ],
        "status_counts": dict(sorted(status_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "category_distribution": [
            {
                "category_id": category_id,
                "category_name": categories.get(category_id).name
                if category_id in categories
                else "",
                "topic_count": count,
            }
            for category_id, count in sorted(category_counts.items())
        ],
        "empty_active_categories": [
            category.category_id
            for category in sorted(
                categories.values(),
                key=lambda item: item.category_id,
            )
            if category.status == "ACTIVE" and not category_counts[category.category_id]
        ],
        "duplicate_pairs": duplicate_pairs,
        "identity_conflicts_excluded": excluded_identity_conflicts,
        "proposal_counts": dict(
            sorted(Counter(proposal.status.value for proposal in proposals).items())
        ),
        "pending_proposal_ids": [
            proposal.proposal_id
            for proposal in proposals
            if proposal.status in {
                ProposalStatus.PROPOSED,
                ProposalStatus.APPROVED,
            }
        ],
    }


def execute_monthly_reorganization(
    store: TopicStore,
    site: str,
    *,
    as_of: str = "",
) -> dict[str, Any]:
    """Apply only exact unpublished merges and propose published restructures."""

    initial = build_monthly_review(store, site, as_of=as_of)
    merged: list[dict[str, str]] = []
    proposed: list[str] = []
    for pair in initial["duplicate_pairs"]:
        if pair["decision"] == "AUTO_MERGE":
            left = store.get_topic(site, pair["left_topic_id"])
            right = store.get_topic(site, pair["right_topic_id"])
            if (
                left is None
                or right is None
                or left.status in EXCLUDED_STATUSES
                or right.status in EXCLUDED_STATUSES
                or left.publications
                or right.publications
            ):
                continue
            ranked = sorted(
                (left, right),
                key=lambda item: (
                    -len(item.question_ids),
                    item.created_at,
                    item.topic_id,
                ),
            )
            target, source = ranked[0], ranked[1]
            store.merge_topics(
                site,
                source.topic_id,
                target.topic_id,
                reason=(
                    "Monthly exact-identity merge within the rolling "
                    f"{REVIEW_WINDOW_DAYS}-day window"
                ),
            )
            merged.append(
                {
                    "source_topic_id": source.topic_id,
                    "target_topic_id": target.topic_id,
                }
            )
        elif (
            pair["decision"] == "PROPOSAL_REQUIRED"
            and pair["left_cluster_id"]
            and pair["right_cluster_id"]
            and pair["left_cluster_id"] != pair["right_cluster_id"]
        ):
            target_topic = store.get_topic(site, pair["left_topic_id"])
            source_topic = store.get_topic(site, pair["right_topic_id"])
            target_title = (
                target_topic.canonical_title
                if target_topic is not None
                else pair["left_topic_id"]
            )
            source_title = (
                source_topic.canonical_title
                if source_topic is not None
                else pair["right_topic_id"]
            )
            similarity = float(pair["similarity"])
            proposal = store.create_monthly_proposal(
                site,
                ProposalKind.MERGE_CLUSTER,
                {
                    "source_cluster_id": pair["right_cluster_id"],
                    "target_cluster_id": pair["left_cluster_id"],
                    "source_topic_id": pair["right_topic_id"],
                    "target_topic_id": pair["left_topic_id"],
                    "current_value": (
                        f"{source_title} ↔ {target_title}"
                    ),
                    "proposed_value": (
                        f"Merge {pair['right_cluster_id']} into "
                        f"{pair['left_cluster_id']}"
                    ),
                    "evidence_summary": (
                        f"Semantic similarity {similarity:.1%}; at least one "
                        "cluster is linked to published content."
                    ),
                    "impact": (
                        "Approval merges Registry cluster identity while "
                        "preserving aliases, questions, topic links, and "
                        "publication URLs. It does not change Blogger labels."
                    ),
                },
                reason=(
                    f'Possible duplicate published guides: "{source_title}" '
                    f'and "{target_title}". Explicit approval is required.'
                ),
            )
            proposed.append(proposal.proposal_id)
    return {
        "site": site,
        "auto_merges": merged,
        "generated_proposal_ids": list(dict.fromkeys(proposed)),
        "review": build_monthly_review(store, site, as_of=as_of),
    }


def import_proposal_bundle(
    store: TopicStore,
    site: str,
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and stage a complete AI proposal bundle before one-file commit."""

    validate_monthly_proposal_bundle(bundle)
    if str(bundle.get("site") or "") != site:
        raise ValueError(f"monthly proposal bundle site must be {site}")
    auditor = dict(bundle.get("auditor") or {})
    if str(auditor.get("decision") or "").upper() != "PASS":
        raise ValueError("monthly proposal bundle requires Auditor PASS")
    proposals = bundle.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("Proposal bundle requires a proposals list")

    base_document = store._load_proposals(site)
    with tempfile.TemporaryDirectory(prefix="monthly-proposal-stage-") as directory:
        staged = TopicStore(Path(directory) / "topics")
        staged._atomic_write(staged.proposals_path(site), base_document)
        created = []
        for index, raw in enumerate(proposals):
            if not isinstance(raw, dict):
                raise ValueError(f"proposals[{index}] must be an object")
            proposal = staged.create_monthly_proposal(
                site,
                kind=str(raw.get("kind") or ""),
                payload=dict(raw.get("payload") or {}),
                reason=str(raw.get("reason") or ""),
                proposal_id=str(raw.get("proposal_id") or ""),
            )
            created.append(proposal.to_dict())
        staged_document = staged._load_proposals(site)

    if staged_document == base_document:
        return created
    with store._lock(site):
        if store._load_proposals(site) != base_document:
            raise ValueError(
                "Monthly proposals changed during staged import; retry"
            )
        store._atomic_write(store.proposals_path(site), staged_document)
    return created
