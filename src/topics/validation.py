from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from src.topics.ids import canonical_url
from src.topics.ids import normalize_text
from src.topics.ids import publication_key
from src.topics.models import CategoryRecord
from src.topics.models import ClusterRecord
from src.topics.models import QuestionRecord
from src.topics.models import TopicAction
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus


MIN_READY_PRIORITY = 20.0
MIN_INDEPENDENT_EVIDENCE = 2
HIGH_CONFIDENCE_EVIDENCE_BASES = {
    "INFORMATION_DENSITY",
    "ENGAGEMENT",
    "FIRST_PARTY_DEMAND",
    "OFFICIAL_ISSUE",
}
DEFAULT_AUTHORITY_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "topics"
    / "trusted_authorities.json"
)


def _authority_config() -> dict:
    configured = os.getenv("TOPIC_BOARD_AUTHORITY_CONFIG", "").strip()
    path = Path(configured) if configured else DEFAULT_AUTHORITY_CONFIG
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def trusted_authority_host(
    site: str,
    authority_type: str,
    host: str,
) -> bool:
    """Match an asserted authority class to an explicit host registry."""

    normalized_host = host.casefold().strip(".")
    selected_type = authority_type.strip().upper()
    if not normalized_host or selected_type not in {
        "GOVERNMENT",
        "VENDOR",
        "PLATFORM",
        "OPERATOR",
        "FIRST_PARTY",
    }:
        return False
    config = _authority_config()
    global_rules = dict(config.get("global") or {})
    site_rules = dict((config.get("sites") or {}).get(site) or {})
    roots = [
        str(item).casefold().strip()
        for item in [
            *list(global_rules.get(selected_type) or []),
            *list(site_rules.get(selected_type) or []),
        ]
        if str(item).strip()
    ]
    for root in roots:
        if root.startswith("."):
            if normalized_host.endswith(root):
                return True
            continue
        normalized_root = root.strip(".")
        if (
            normalized_host == normalized_root
            or normalized_host.endswith(f".{normalized_root}")
        ):
            return True
    return False


@dataclass(frozen=True)
class EvidenceGateResult:
    passed: bool
    independent_evidence_count: int
    eligible_question_ids: tuple[str, ...]
    excluded_question_ids: tuple[str, ...]
    exception_used: bool
    reason: str


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


def evidence_gate(
    topic: TopicRecord,
    questions: Iterable[QuestionRecord],
) -> EvidenceGateResult:
    """Require two independent observed/first-party demand records.

    Search suggestions, query plans, and fallback templates may remain in the
    inbox for context, but never count as demand evidence.  A one-off exception
    is only valid when a human approval identity, rationale, and timestamp are
    all recorded on the topic.
    """

    by_id = {question.question_id: question for question in questions}
    independent: dict[str, str] = {}
    excluded: list[str] = []
    for question_id in topic.question_ids:
        question = by_id.get(question_id)
        if question is None or not question.eligible_evidence:
            excluded.append(question_id)
            continue
        if question.source_item_id:
            identity = f"{normalize_text(question.source)}:{question.source_item_id.strip()}"
        elif question.url:
            identity = canonical_url(question.url)
        else:
            identity = question.content_hash
        if identity:
            independent.setdefault(identity, question.question_id)

    exception = topic.evidence_exception or {}
    exception_basis = str(
        exception.get("basis")
        or exception.get("high_confidence_basis")
        or ""
    ).strip().upper()
    approved_exception = all(
        str(exception.get(field) or "").strip()
        for field in (
            "approved_by",
            "reason",
            "approved_at",
            "decision_id",
        )
    ) and (
        str(exception.get("approval_source") or "").strip().upper()
        == "USER_DECISION"
    ) and exception_basis in HIGH_CONFIDENCE_EVIDENCE_BASES
    eligible_with_locator = any(
        question.question_id in independent.values()
        and bool(question.evidence_locator)
        for question in by_id.values()
    )
    exception_used = approved_exception and eligible_with_locator
    passed = (
        len(independent) >= MIN_INDEPENDENT_EVIDENCE
        and eligible_with_locator
    ) or exception_used
    if (
        len(independent) >= MIN_INDEPENDENT_EVIDENCE
        and eligible_with_locator
    ):
        reason = f"{len(independent)} independent demand records"
    elif exception_used:
        reason = f"human-approved evidence exception ({exception_basis})"
    else:
        if not eligible_with_locator:
            reason = "needs at least one eligible immutable evidence locator"
        else:
            reason = (
                f"needs {MIN_INDEPENDENT_EVIDENCE} independent observed/first-party records; "
                f"found {len(independent)}"
            )
    return EvidenceGateResult(
        passed=passed,
        independent_evidence_count=len(independent),
        eligible_question_ids=tuple(independent.values()),
        excluded_question_ids=tuple(excluded),
        exception_used=exception_used,
        reason=reason,
    )


def semantic_text_similarity(left_value: str, right_value: str) -> float:
    left_text = normalize_text(left_value)
    right_text = normalize_text(right_value)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_text, right_text).ratio()
    return round(max(jaccard, sequence), 4)


def topic_similarity(left: TopicRecord, right: TopicRecord) -> float:
    return semantic_text_similarity(
        left.problem_signature or left.canonical_title,
        right.problem_signature or right.canonical_title,
    )


def ready_blockers(
    topic: TopicRecord,
    questions: Iterable[QuestionRecord],
    category: CategoryRecord | None,
) -> list[str]:
    blockers: list[str] = []
    if not topic.canonical_title.strip():
        blockers.append("canonical title is empty")
    if category is None or category.status != "ACTIVE":
        blockers.append("active category is missing")
    if topic.action in {TopicAction.REJECT, TopicAction.MERGE, TopicAction.WATCH}:
        blockers.append(f"action {topic.action.value} is not publishable")
    if topic.priority_score < MIN_READY_PRIORITY:
        blockers.append(
            f"priority {topic.priority_score:.2f} is below {MIN_READY_PRIORITY:.2f}"
        )
    if not topic.editor_brief.strip():
        blockers.append("editor brief is required")
    if not topic.reader_questions:
        blockers.append("at least one reader question is required")
    if not topic.difference_from_existing.strip():
        blockers.append("difference from existing content is required")
    gate = evidence_gate(topic, questions)
    if not gate.passed:
        blockers.append(gate.reason)
    linked = {
        question.question_id: question
        for question in questions
        if question.question_id in topic.question_ids
    }
    noneligible = [
        question_id
        for question_id in topic.question_ids
        if question_id in linked and not linked[question_id].eligible_evidence
    ]
    if noneligible:
        blockers.append(
            "READY topic contains noneligible/synthetic linked questions"
        )
    blocked_official_hosts = {
        "reddit.com",
        "www.reddit.com",
        "google.com",
        "www.google.com",
        "bing.com",
        "www.bing.com",
        "quora.com",
        "www.quora.com",
        "stackexchange.com",
        "stackoverflow.com",
        "facebook.com",
        "x.com",
        "twitter.com",
        "instagram.com",
    }
    valid_authorities = {
        "GOVERNMENT",
        "VENDOR",
        "PLATFORM",
        "OPERATOR",
        "FIRST_PARTY",
    }
    official_refs = []
    for ref in topic.official_source_refs:
        url = canonical_url(str(ref.get("url") or ""))
        host = urlsplit(url).netloc.casefold()
        authority_type = str(ref.get("authority_type") or "").upper()
        blocked = host in blocked_official_hosts or any(
            host.endswith(f".{blocked_host}")
            for blocked_host in blocked_official_hosts
        )
        if (
            url.startswith("https://")
            and host
            and not blocked
            and authority_type in valid_authorities
            and trusted_authority_host(
                topic.site,
                authority_type,
                host,
            )
        ):
            official_refs.append(ref)
    if not official_refs:
        blockers.append(
            "at least one trusted host matching its official authority class is required"
        )
    if not topic.official_answerable:
        blockers.append("official sources do not yet make the topic answerable")
    if topic.auditor_decision != "PASS" or not topic.audited_at:
        blockers.append("topic-level auditor PASS with audited_at is required")
    if topic.duplicate_candidate_ids:
        blockers.append("unresolved duplicate candidates exist")
    if topic.merged_into_topic_id:
        blockers.append("topic has been merged")
    return blockers


def validate_documents(
    site: str,
    topics: Iterable[TopicRecord],
    questions: Iterable[QuestionRecord],
    categories: Iterable[CategoryRecord],
    clusters: Iterable[ClusterRecord] = (),
    aliases: dict[str, str] | None = None,
    cluster_aliases: dict[str, str] | None = None,
    publication_index: dict[str, str] | None = None,
    rollout: dict | None = None,
) -> list[ValidationIssue]:
    topic_map = {topic.topic_id: topic for topic in topics}
    question_map = {question.question_id: question for question in questions}
    category_map = {category.category_id: category for category in categories}
    cluster_map = {cluster.cluster_id: cluster for cluster in clusters}
    issues: list[ValidationIssue] = []

    for topic in topic_map.values():
        path = f"topics.{topic.topic_id}"
        if topic.site != site:
            issues.append(
                ValidationIssue("ERROR", "TOPIC_SITE_MISMATCH", "topic site does not match registry", path)
            )
        primary_publications = [
            publication
            for publication in topic.publications
            if publication.primary
        ]
        if (
            topic.action is TopicAction.NEW_POST
            and len(primary_publications) > 1
        ):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "NEW_POST_MULTIPLE_PRIMARY_PUBLICATIONS",
                    "NEW_POST topics may own at most one primary publication",
                    f"{path}.publications",
                )
            )
        if topic.category_id not in category_map:
            issues.append(
                ValidationIssue("ERROR", "UNKNOWN_CATEGORY", "topic references an unknown category", path)
            )
        if not topic.cluster_id or topic.cluster_id not in cluster_map:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "UNKNOWN_CLUSTER",
                    "topic references an unknown problem cluster",
                    path,
                )
            )
        elif topic.topic_id not in cluster_map[topic.cluster_id].topic_ids:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "CLUSTER_TOPIC_ASYMMETRIC",
                    "topic cluster does not link back to the topic",
                    path,
                )
            )
        missing_questions = [
            question_id for question_id in topic.question_ids if question_id not in question_map
        ]
        if missing_questions:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "MISSING_QUESTION",
                    f"topic references missing questions: {', '.join(missing_questions)}",
                    path,
                )
            )
        if topic.status is TopicStatus.READY:
            for blocker in ready_blockers(topic, question_map.values(), category_map.get(topic.category_id)):
                issues.append(ValidationIssue("ERROR", "READY_GATE_FAILED", blocker, path))
        if topic.status is TopicStatus.CLAIMED and not topic.claim_run_id:
            issues.append(
                ValidationIssue("ERROR", "CLAIM_WITHOUT_RUN", "claimed topic has no run id", path)
            )
        if topic.status in {TopicStatus.LIVE_UNVERIFIED, TopicStatus.PUBLISHED} and not topic.publications:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "PUBLICATION_MISSING",
                    f"{topic.status.value} topic has no publication reference",
                    path,
                )
            )
        if topic.status is TopicStatus.MERGED:
            if not topic.merged_into_topic_id or topic.merged_into_topic_id not in topic_map:
                issues.append(
                    ValidationIssue("ERROR", "MERGE_TARGET_MISSING", "merged topic target is missing", path)
                )
        for duplicate_id in topic.duplicate_candidate_ids:
            if duplicate_id not in topic_map and not duplicate_id.startswith("blogger:"):
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        "DUPLICATE_REFERENCE_MISSING",
                        f"duplicate candidate {duplicate_id} is missing",
                        path,
                    )
                )

    for question in question_map.values():
        path = f"questions.{question.question_id}"
        if question.site != site:
            issues.append(
                ValidationIssue(
                    "ERROR", "QUESTION_SITE_MISMATCH", "question site does not match inbox", path
                )
            )
        if question.evidence_type.value in {
            "OBSERVED_QUESTION",
            "FIRST_PARTY_QUERY",
        } and not question.eligible_evidence:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "EVIDENCE_PROVENANCE_INVALID",
                    (
                        "eligible evidence type lacks immutable identity or "
                        "approved verification provenance"
                    ),
                    path,
                )
            )
        if question.topic_id and question.topic_id not in topic_map:
            issues.append(
                ValidationIssue("ERROR", "QUESTION_TOPIC_MISSING", "question topic is missing", path)
            )
        elif question.topic_id and question.question_id not in topic_map[question.topic_id].question_ids:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "QUESTION_LINK_ASYMMETRIC",
                    "question points to a topic that does not link back",
                    path,
                )
            )

    for cluster in cluster_map.values():
        path = f"clusters.{cluster.cluster_id}"
        if cluster.site != site:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "CLUSTER_SITE_MISMATCH",
                    "cluster site does not match registry",
                    path,
                )
            )
        for topic_id in cluster.topic_ids:
            topic = topic_map.get(topic_id)
            if topic is None:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "CLUSTER_TOPIC_MISSING",
                        f"cluster references missing topic {topic_id}",
                        path,
                    )
                )
            elif topic.cluster_id != cluster.cluster_id and not cluster.merged_into_cluster_id:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "CLUSTER_TOPIC_LINK_MISMATCH",
                        f"topic {topic_id} points to {topic.cluster_id}",
                        path,
                    )
                )
        for question_id in cluster.question_ids:
            if question_id not in question_map:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "CLUSTER_QUESTION_MISSING",
                        f"cluster references missing question {question_id}",
                        path,
                    )
                )
        if cluster.merged_into_cluster_id and cluster.merged_into_cluster_id not in cluster_map:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "CLUSTER_MERGE_TARGET_MISSING",
                    "merged cluster target is missing",
                    path,
                )
            )

    for alias, target in (cluster_aliases or {}).items():
        if target not in cluster_map:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "CLUSTER_ALIAS_TARGET_MISSING",
                    f"cluster alias {alias} targets missing cluster {target}",
                    f"cluster_aliases.{alias}",
                )
            )

    seen_publications: dict[str, str] = {}
    for topic in topic_map.values():
        for publication in topic.publications:
            for key in (
                publication_key(publication.blogger_post_id, ""),
                publication_key("", publication.url),
            ):
                if not key or key == "url:":
                    continue
                owner = seen_publications.get(key)
                if owner and owner != topic.topic_id:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "PUBLICATION_DUPLICATE",
                            f"{key} is mapped to both {owner} and {topic.topic_id}",
                            f"topics.{topic.topic_id}.publications",
                        )
                    )
                seen_publications[key] = topic.topic_id

    for alias, target in (aliases or {}).items():
        if target not in topic_map:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "ALIAS_TARGET_MISSING",
                    f"alias {alias} targets missing topic {target}",
                    f"aliases.{alias}",
                )
            )
        if alias == target:
            issues.append(
                ValidationIssue("ERROR", "ALIAS_SELF_REFERENCE", "alias points to itself", f"aliases.{alias}")
            )

    for key, target in (publication_index or {}).items():
        if target not in topic_map:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "PUBLICATION_INDEX_TARGET_MISSING",
                    f"{key} targets missing topic {target}",
                    f"publication_index.{key}",
                )
            )
        elif seen_publications.get(key) != target:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "PUBLICATION_INDEX_STALE",
                    f"{key} does not match the topic publication list",
                    f"publication_index.{key}",
                )
            )

    rollout = rollout or {}
    mode = str(rollout.get("mode") or "SHADOW")
    successes = int(rollout.get("consecutive_qualifying_runs") or 0)
    required = int(rollout.get("required_qualifying_runs") or 2)
    if mode == "READY_FIRST" and successes < required:
        issues.append(
            ValidationIssue(
                "ERROR",
                "ROLLOUT_GATE_BYPASSED",
                "READY_FIRST mode is active before the shadow gate passed",
                "rollout",
            )
        )
    if mode == "READY_FIRST" and not bool(
        (rollout.get("backfill") or {}).get("complete")
    ):
        issues.append(
            ValidationIssue(
                "ERROR",
                "ROLLOUT_BACKFILL_INCOMPLETE",
                "READY_FIRST mode is active before required backfill completion",
                "rollout.backfill",
            )
        )
    qualifying_weeks = [
        str((item.get("details") or {}).get("iso_week") or "")
        for item in rollout.get("recent_runs") or []
        if item.get("qualifying") is True
    ]
    normalized_weeks = [item for item in qualifying_weeks if item]
    if len(normalized_weeks) != len(set(normalized_weeks)):
        issues.append(
            ValidationIssue(
                "ERROR",
                "ROLLOUT_DUPLICATE_QUALIFYING_WEEK",
                "more than one qualifying run was counted for the same KST ISO week",
                "rollout.recent_runs",
            )
        )
    return issues
