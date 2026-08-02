from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from enum import Enum
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from src.topics.ids import canonical_url
from src.topics.ids import normalize_text
from src.topics.ids import question_id_for


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _enum_value(value: Any, enum_type: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).upper())
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class TopicStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    REVIEW = "REVIEW"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    CLAIMED = "CLAIMED"
    GENERATED = "GENERATED"
    LIVE_UNVERIFIED = "LIVE_UNVERIFIED"
    PUBLISHED = "PUBLISHED"
    UPDATE_DUE = "UPDATE_DUE"
    HOLD = "HOLD"
    STALE = "STALE"
    MERGED = "MERGED"
    REJECTED = "REJECTED"


class TopicAction(str, Enum):
    NEW_POST = "NEW_POST"
    UPDATE_EXISTING = "UPDATE_EXISTING"
    FAQ_ADD = "FAQ_ADD"
    WATCH = "WATCH"
    MERGE = "MERGE"
    REJECT = "REJECT"


class EvidenceType(str, Enum):
    OBSERVED_QUESTION = "OBSERVED_QUESTION"
    FIRST_PARTY_QUERY = "FIRST_PARTY_QUERY"
    SEARCH_SUGGESTION = "SEARCH_SUGGESTION"
    QUERY_PLAN = "QUERY_PLAN"
    FALLBACK_TEMPLATE = "FALLBACK_TEMPLATE"


OBSERVED_SOURCE_HOST_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "reddit": ("reddit.com",),
    "reddit_oauth": ("reddit.com",),
    "stack_exchange": (
        "stackexchange.com",
        "stackoverflow.com",
        "superuser.com",
        "serverfault.com",
        "askubuntu.com",
    ),
    "stackoverflow": ("stackoverflow.com",),
    "superuser": ("superuser.com",),
    "server_fault": ("serverfault.com",),
    "ask_ubuntu": ("askubuntu.com",),
    "microsoft_answers": ("answers.microsoft.com",),
    "quora": ("quora.com",),
}


def _host_matches_allowlist(host: str, allowed_roots: tuple[str, ...]) -> bool:
    return any(host == root or host.endswith(f".{root}") for root in allowed_roots)


class ProposalKind(str, Enum):
    CREATE_CATEGORY = "CREATE_CATEGORY"
    RENAME_CATEGORY = "RENAME_CATEGORY"
    MERGE_CATEGORY = "MERGE_CATEGORY"
    SPLIT_CATEGORY = "SPLIT_CATEGORY"
    LABEL_CHANGE = "LABEL_CHANGE"
    MERGE_CLUSTER = "MERGE_CLUSTER"
    SPLIT_CLUSTER = "SPLIT_CLUSTER"
    REASSIGN_CATEGORY = "REASSIGN_CATEGORY"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class PublicationRef:
    blogger_post_id: str = ""
    url: str = ""
    title: str = ""
    status: str = ""
    published_at: str = ""
    updated_at: str = ""
    last_verified_at: str = ""
    primary: bool = True

    @property
    def post_id(self) -> str:
        return self.blogger_post_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PublicationRef":
        data = data or {}
        return cls(
            blogger_post_id=str(data.get("blogger_post_id") or data.get("post_id") or data.get("id") or ""),
            url=str(data.get("url") or ""),
            title=str(data.get("title") or ""),
            status=str(data.get("status") or ""),
            published_at=str(data.get("published_at") or data.get("published") or ""),
            updated_at=str(data.get("updated_at") or data.get("updated") or ""),
            last_verified_at=str(data.get("last_verified_at") or ""),
            primary=bool(data.get("primary", True)),
        )


@dataclass
class QuestionRecord:
    question_id: str
    site: str
    source: str
    title: str
    source_item_id: str = ""
    url: str = ""
    summary: str = ""
    created_at: str = ""
    collected_at: str = field(default_factory=utc_now)
    engagement: dict[str, float] = field(default_factory=dict)
    content_hash: str = ""
    evidence_type: EvidenceType = EvidenceType.FALLBACK_TEMPLATE
    verification_method: str = ""
    verified_at: str = ""
    verified_by: str = ""
    property_id: str = ""
    topic_id: str = ""
    aliases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.question_id = self.question_id or question_id_for(
            self.site,
            self.source,
            self.source_item_id,
            self.url,
            self.title,
        )
        self.url = canonical_url(self.url)
        if not self.content_hash:
            material = f"{normalize_text(self.title)}\x1f{normalize_text(self.summary)}"
            self.content_hash = sha256(material.encode("utf-8")).hexdigest()
        self.evidence_type = _enum_value(
            self.evidence_type,
            EvidenceType,
            EvidenceType.FALLBACK_TEMPLATE,
        )  # type: ignore[assignment]
        self.aliases = _string_list(self.aliases)
        cleaned: dict[str, float] = {}
        for key, value in (self.engagement or {}).items():
            try:
                cleaned[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        self.engagement = cleaned

    @property
    def eligible_evidence(self) -> bool:
        if not self.verified_at or not self.verified_by:
            return False
        has_identity = bool(self.source_item_id or self.url)
        if not has_identity:
            return False
        method = normalize_text(self.verification_method).replace(" ", "_")
        source = normalize_text(self.source).replace(" ", "_")
        host = urlsplit(self.url).netloc.casefold()
        if self.evidence_type is EvidenceType.OBSERVED_QUESTION:
            if method == "reddit_oauth":
                return source in {"reddit", "reddit_oauth"} and (
                    host == "reddit.com" or host.endswith(".reddit.com")
                )
            if method in {"browser_verified", "verified_by_codex"}:
                allowed_roots = OBSERVED_SOURCE_HOST_ALLOWLIST.get(source, ())
                return bool(host) and _host_matches_allowlist(
                    host,
                    allowed_roots,
                )
            return False
        if self.evidence_type is EvidenceType.FIRST_PARTY_QUERY:
            return (
                source in {"search_console", "google_search_console"}
                and method in {"search_console_api", "search_console_export"}
                and bool(self.source_item_id)
                and bool(self.property_id)
            )
        return False

    @property
    def evidence_locator(self) -> str:
        """Return the immutable locator used to audit eligible demand evidence."""

        if not self.eligible_evidence:
            return ""
        if self.evidence_type is EvidenceType.FIRST_PARTY_QUERY:
            return (
                f"search-console:{self.property_id.strip()}:"
                f"{self.source_item_id.strip()}"
            )
        return canonical_url(self.url)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_type"] = self.evidence_type.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestionRecord":
        engagement = data.get("engagement")
        if not isinstance(engagement, dict):
            engagement = {
                key: data[key]
                for key in ("score", "comments", "upvotes", "views")
                if key in data
            }
        return cls(
            question_id=str(data.get("question_id") or ""),
            site=str(data.get("site") or ""),
            source=str(data.get("source") or "unknown"),
            source_item_id=str(
                data.get("source_item_id")
                or data.get("source_id")
                or data.get("reddit_id")
                or data.get("external_id")
                or data.get("id")
                or ""
            ),
            url=str(data.get("url") or data.get("permalink") or ""),
            title=str(data.get("title") or data.get("question") or ""),
            summary=str(data.get("summary") or ""),
            created_at=str(
                data.get("created_at")
                or data.get("posted_at")
                or data.get("created_utc")
                or ""
            ),
            collected_at=str(data.get("collected_at") or utc_now()),
            engagement=engagement,
            content_hash=str(data.get("content_hash") or ""),
            evidence_type=data.get("evidence_type")
            or data.get("evidence")
            or EvidenceType.FALLBACK_TEMPLATE,
            verification_method=str(data.get("verification_method") or ""),
            verified_at=str(data.get("verified_at") or ""),
            verified_by=str(data.get("verified_by") or ""),
            property_id=str(
                data.get("property_id")
                or data.get("site_property")
                or data.get("property")
                or ""
            ),
            topic_id=str(data.get("topic_id") or ""),
            aliases=_string_list(data.get("aliases")),
        )


@dataclass
class CategoryRecord:
    category_id: str
    site: str
    name: str
    blogger_label: str
    aliases: list[str] = field(default_factory=list)
    status: str = "ACTIVE"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CategoryRecord":
        return cls(
            category_id=str(data.get("category_id") or ""),
            site=str(data.get("site") or ""),
            name=str(data.get("name") or ""),
            blogger_label=str(data.get("blogger_label") or data.get("name") or ""),
            aliases=_string_list(data.get("aliases")),
            status=str(data.get("status") or "ACTIVE").upper(),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
        )


@dataclass
class ClusterRecord:
    cluster_id: str
    site: str
    problem_signature: str
    canonical_label: str = ""
    question_ids: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    merged_into_cluster_id: str = ""
    observation_run_ids: list[str] = field(default_factory=list)
    revision: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.question_ids = _string_list(self.question_ids)
        self.topic_ids = _string_list(self.topic_ids)
        self.aliases = _string_list(self.aliases)
        self.observation_run_ids = _string_list(self.observation_run_ids)
        self.revision = max(1, int(self.revision or 1))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClusterRecord":
        return cls(
            cluster_id=str(data.get("cluster_id") or ""),
            site=str(data.get("site") or ""),
            problem_signature=str(data.get("problem_signature") or ""),
            canonical_label=str(data.get("canonical_label") or data.get("label") or ""),
            question_ids=_string_list(data.get("question_ids")),
            topic_ids=_string_list(data.get("topic_ids")),
            aliases=_string_list(data.get("aliases")),
            merged_into_cluster_id=str(data.get("merged_into_cluster_id") or ""),
            observation_run_ids=_string_list(data.get("observation_run_ids")),
            revision=data.get("revision") or 1,
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
        )


@dataclass
class TopicRecord:
    topic_id: str
    site: str
    canonical_title: str
    category_id: str
    cluster_id: str = ""
    canonical_intent: str = ""
    problem_signature: str = ""
    question_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    action: TopicAction = TopicAction.NEW_POST
    status: TopicStatus = TopicStatus.DISCOVERED
    priority_score: float = 0.0
    priority_components: dict[str, float] = field(default_factory=dict)
    priority_override: float | None = None
    revision: int = 1
    merged_into_topic_id: str = ""
    publications: list[PublicationRef] = field(default_factory=list)
    editor_brief: str = ""
    editor_notes: list[str] = field(default_factory=list)
    reader_questions: list[str] = field(default_factory=list)
    difference_from_existing: str = ""
    severity_score: float = 0.0
    severity_reason: str = ""
    official_source_urls: list[str] = field(default_factory=list)
    official_source_refs: list[dict[str, str]] = field(default_factory=list)
    official_answerable: bool = False
    auditor_decision: str = ""
    auditor_reasons: list[str] = field(default_factory=list)
    audited_at: str = ""
    duplicate_candidate_ids: list[str] = field(default_factory=list)
    evidence_exception: dict[str, str] = field(default_factory=dict)
    status_reason: str = ""
    claim_run_id: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_validated_at: str = ""

    def __post_init__(self) -> None:
        self.action = _enum_value(
            self.action,
            TopicAction,
            TopicAction.NEW_POST,
        )  # type: ignore[assignment]
        self.status = _enum_value(
            self.status,
            TopicStatus,
            TopicStatus.DISCOVERED,
        )  # type: ignore[assignment]
        self.question_ids = _string_list(self.question_ids)
        self.aliases = _string_list(self.aliases)
        self.reader_questions = _string_list(self.reader_questions)
        self.editor_notes = _string_list(self.editor_notes)
        self.duplicate_candidate_ids = _string_list(self.duplicate_candidate_ids)
        self.official_source_urls = _string_list(self.official_source_urls)
        self.official_source_refs = [
            {
                "url": str(item.get("url") or ""),
                "authority_type": str(item.get("authority_type") or "").upper(),
            }
            for item in self.official_source_refs
            if isinstance(item, dict)
        ]
        self.auditor_reasons = _string_list(self.auditor_reasons)
        self.publications = [
            item if isinstance(item, PublicationRef) else PublicationRef.from_dict(item)
            for item in self.publications
        ]
        try:
            self.priority_score = round(float(self.priority_score), 2)
        except (TypeError, ValueError):
            self.priority_score = 0.0
        try:
            self.severity_score = round(float(self.severity_score), 2)
        except (TypeError, ValueError):
            self.severity_score = 0.0
        if self.priority_override is not None:
            try:
                self.priority_override = round(float(self.priority_override), 2)
            except (TypeError, ValueError):
                self.priority_override = None
        try:
            self.revision = max(1, int(self.revision))
        except (TypeError, ValueError):
            self.revision = 1

    @property
    def canonical_topic(self) -> str:
        return self.canonical_title

    @property
    def title(self) -> str:
        return self.canonical_title

    @property
    def seed(self) -> str:
        return self.canonical_title

    @property
    def category(self) -> str:
        return self.category_id

    @property
    def existing_post_refs(self) -> list[PublicationRef]:
        return self.publications

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["action"] = self.action.value
        result["status"] = self.status.value
        result["publications"] = [item.to_dict() for item in self.publications]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicRecord":
        return cls(
            topic_id=str(data.get("topic_id") or ""),
            site=str(data.get("site") or ""),
            canonical_title=str(
                data.get("canonical_title")
                or data.get("canonical_topic")
                or data.get("title")
                or data.get("seed")
                or ""
            ),
            category_id=str(data.get("category_id") or data.get("category") or ""),
            cluster_id=str(data.get("cluster_id") or ""),
            canonical_intent=str(data.get("canonical_intent") or data.get("intent") or ""),
            problem_signature=str(data.get("problem_signature") or ""),
            question_ids=_string_list(data.get("question_ids")),
            aliases=_string_list(data.get("aliases")),
            action=data.get("action") or TopicAction.NEW_POST,
            status=data.get("status") or TopicStatus.DISCOVERED,
            priority_score=data.get("priority_score") or 0.0,
            priority_components=dict(data.get("priority_components") or {}),
            priority_override=(
                data.get("priority_override")
                if data.get("priority_override") is not None
                else None
            ),
            revision=data.get("revision") or 1,
            merged_into_topic_id=str(data.get("merged_into_topic_id") or ""),
            publications=[
                PublicationRef.from_dict(item)
                for item in data.get("publications", data.get("existing_post_refs", []))
                if isinstance(item, dict)
            ],
            editor_brief=str(data.get("editor_brief") or ""),
            editor_notes=_string_list(data.get("editor_notes")),
            reader_questions=_string_list(data.get("reader_questions")),
            difference_from_existing=str(data.get("difference_from_existing") or ""),
            severity_score=data.get("severity_score") or 0.0,
            severity_reason=str(data.get("severity_reason") or ""),
            official_source_urls=_string_list(data.get("official_source_urls")),
            official_source_refs=[
                dict(item)
                for item in data.get("official_source_refs", [])
                if isinstance(item, dict)
            ],
            official_answerable=bool(data.get("official_answerable", False)),
            auditor_decision=str(data.get("auditor_decision") or "").upper(),
            auditor_reasons=_string_list(data.get("auditor_reasons")),
            audited_at=str(data.get("audited_at") or ""),
            duplicate_candidate_ids=_string_list(data.get("duplicate_candidate_ids")),
            evidence_exception={
                str(key): str(value)
                for key, value in dict(data.get("evidence_exception") or {}).items()
            },
            status_reason=str(data.get("status_reason") or ""),
            claim_run_id=str(data.get("claim_run_id") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            last_validated_at=str(data.get("last_validated_at") or ""),
        )


@dataclass
class MonthlyProposal:
    proposal_id: str
    site: str
    kind: ProposalKind
    payload: dict[str, Any]
    reason: str = ""
    status: ProposalStatus = ProposalStatus.PROPOSED
    label_snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot_path: str = ""
    rollback_path: str = ""
    rollback_audit_path: str = ""
    label_sync_snapshot_path: str = ""
    publication_sync_pending: bool = False
    publication_sync_error: str = ""
    approved_by: str = ""
    reviewer_notes: str = ""
    created_at: str = field(default_factory=utc_now)
    approved_at: str = ""
    applied_at: str = ""
    rolled_back_at: str = ""

    def __post_init__(self) -> None:
        self.kind = _enum_value(
            self.kind,
            ProposalKind,
            ProposalKind.CREATE_CATEGORY,
        )  # type: ignore[assignment]
        self.status = _enum_value(
            self.status,
            ProposalStatus,
            ProposalStatus.PROPOSED,
        )  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kind"] = self.kind.value
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonthlyProposal":
        return cls(
            proposal_id=str(data.get("proposal_id") or ""),
            site=str(data.get("site") or ""),
            kind=data.get("kind") or ProposalKind.CREATE_CATEGORY,
            payload=dict(data.get("payload") or {}),
            reason=str(data.get("reason") or ""),
            status=data.get("status") or ProposalStatus.PROPOSED,
            label_snapshot=dict(data.get("label_snapshot") or {}),
            snapshot_path=str(data.get("snapshot_path") or ""),
            rollback_path=str(data.get("rollback_path") or ""),
            rollback_audit_path=str(data.get("rollback_audit_path") or ""),
            label_sync_snapshot_path=str(
                data.get("label_sync_snapshot_path") or ""
            ),
            publication_sync_pending=bool(data.get("publication_sync_pending", False)),
            publication_sync_error=str(data.get("publication_sync_error") or ""),
            approved_by=str(data.get("approved_by") or ""),
            reviewer_notes=str(data.get("reviewer_notes") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            approved_at=str(data.get("approved_at") or ""),
            applied_at=str(data.get("applied_at") or ""),
            rolled_back_at=str(data.get("rolled_back_at") or ""),
        )
