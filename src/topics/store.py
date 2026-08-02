from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any
from typing import Iterator
from zoneinfo import ZoneInfo

from src.topics.ids import canonical_url
from src.topics.ids import category_id_for
from src.topics.ids import normalize_text
from src.topics.ids import publication_key
from src.topics.ids import stable_id
from src.topics.ids import topic_id_for
from src.topics.models import CategoryRecord
from src.topics.models import ClusterRecord
from src.topics.models import EvidenceType
from src.topics.models import MonthlyProposal
from src.topics.models import ProposalKind
from src.topics.models import ProposalStatus
from src.topics.models import PublicationRef
from src.topics.models import QuestionRecord
from src.topics.models import SCHEMA_VERSION
from src.topics.models import TopicAction
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.models import utc_now
from src.topics.schema import validate_persistent_document
from src.topics.schema import validate_weekly_bundle
from src.topics.validation import ValidationIssue
from src.topics.validation import HIGH_CONFIDENCE_EVIDENCE_BASES
from src.topics.validation import evidence_gate
from src.topics.validation import ready_blockers
from src.topics.validation import semantic_text_similarity
from src.topics.validation import topic_similarity
from src.topics.validation import validate_documents


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "topics"
ROLLOUT_SHADOW = "SHADOW"
ROLLOUT_READY_FIRST = "READY_FIRST"
ROLLOUT_DEGRADED = "DEGRADED"
ROLLOUT_REQUIRED_RUNS = 2
KST = ZoneInfo("Asia/Seoul")
PRIORITY_COMPONENT_MAX = {
    "evidence_strength": 25.0,
    "recurrence": 20.0,
    "content_gap": 20.0,
    "severity": 15.0,
    "answerability": 10.0,
    "recency": 10.0,
}
PRIORITY_ACTIONS = {
    TopicAction.NEW_POST,
    TopicAction.UPDATE_EXISTING,
    TopicAction.FAQ_ADD,
}
PRIORITY_CANDIDATE_STATUSES = {
    TopicStatus.DISCOVERED,
    TopicStatus.REVIEW,
    TopicStatus.READY,
}
SAFE_PROPOSAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _default_registry(site: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "site": site,
        "revision": 0,
        "topics": {},
        "clusters": {},
        "aliases": {},
        "cluster_aliases": {},
        "publication_index": {},
        "blogger_catalog": {},
        "publication_outbox": [],
        "publish_attempts": {},
        "publish_attempt_history": [],
        "publication_receipts": {},
        "topic_reservations": {},
        "rollout": {
            "mode": ROLLOUT_SHADOW,
            "required_qualifying_runs": ROLLOUT_REQUIRED_RUNS,
            "consecutive_qualifying_runs": 0,
            "last_run_id": "",
            "last_run_at": "",
            "last_status": "",
            "backfill": {
                "complete": False,
                "last_run_id": "",
                "completed_at": "",
                "coverage_hash": "",
                "logic_version": "",
                "unexplored_scope": [],
            },
            "recent_runs": [],
        },
        "updated_at": "",
    }


def _default_inbox(site: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "site": site,
        "questions": {},
        "updated_at": "",
    }


def _default_categories(site: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "site": site,
        "revision": 0,
        "categories": {},
        "updated_at": "",
    }


def _default_proposals(site: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "site": site,
        "proposals": {},
        "updated_at": "",
    }


class TopicStore:
    """JSON-backed registry with atomic writes and optimistic topic claims."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    def site_dir(self, site: str) -> Path:
        return self.root / site

    def registry_path(self, site: str) -> Path:
        return self.site_dir(site) / "registry.json"

    def inbox_path(self, site: str) -> Path:
        return self.site_dir(site) / "inbox.json"

    def categories_path(self, site: str) -> Path:
        return self.site_dir(site) / "categories.json"

    def proposals_path(self, site: str) -> Path:
        return self.site_dir(site) / "monthly_proposals.json"

    @contextmanager
    def _lock(self, site: str) -> Iterator[None]:
        directory = self.site_dir(site)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".topic-board.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                self._recover_document_transaction(site)
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return deepcopy(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Cannot read topic-board file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Topic-board file must contain an object: {path}")
        return data

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            directory_fd = os.open(
                str(path.parent),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _document_hash(data: dict[str, Any]) -> str:
        payload = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def _transaction_journal_path(self, site: str) -> Path:
        return self.site_dir(site) / ".topic-board-transaction.json"

    def _recover_document_transaction(self, site: str) -> None:
        """Finish or roll back an interrupted multi-document commit."""

        journal_path = self._transaction_journal_path(site)
        if not journal_path.exists():
            return
        journal = self._read_json(journal_path, {})
        entries = list(journal.get("entries") or [])
        site_root = self.site_dir(site).resolve()
        all_applied = True
        for entry in entries:
            target = (site_root / str(entry.get("target") or "")).resolve()
            if site_root not in target.parents:
                raise ValueError("transaction target escapes site directory")
            if not target.exists():
                all_applied = False
                break
            current = self._read_json(target, {})
            if self._document_hash(current) != str(entry.get("new_hash") or ""):
                all_applied = False
                break
        transaction_dir = site_root / ".transactions" / str(
            journal.get("transaction_id") or ""
        )
        if not all_applied:
            for entry in entries:
                target = (site_root / str(entry.get("target") or "")).resolve()
                if entry.get("existed") is True:
                    backup = (
                        transaction_dir
                        / "backup"
                        / str(entry.get("target") or "")
                    )
                    if not backup.exists():
                        raise ValueError(
                            f"transaction backup is missing for {target}"
                        )
                    self._atomic_write(target, self._read_json(backup, {}))
                elif target.exists():
                    target.unlink()
        journal_path.unlink(missing_ok=True)
        if transaction_dir.exists():
            shutil.rmtree(transaction_dir)
        transactions_root = site_root / ".transactions"
        if transactions_root.exists() and not any(transactions_root.iterdir()):
            transactions_root.rmdir()

    def _commit_documents_locked(
        self,
        site: str,
        documents: list[tuple[Path, dict[str, Any]]],
    ) -> None:
        """Crash-recoverable commit for a related set of JSON documents.

        The caller must hold ``_lock(site)``.
        """

        site_root = self.site_dir(site).resolve()
        transaction_id = stable_id(
            "tx",
            site,
            utc_now(),
            os.getpid(),
        )
        transaction_dir = site_root / ".transactions" / transaction_id
        entries: list[dict[str, Any]] = []
        seen_targets: set[Path] = set()
        for target, document in documents:
            resolved = target.resolve()
            if site_root not in resolved.parents:
                raise ValueError("transaction target escapes site directory")
            if resolved in seen_targets:
                raise ValueError(f"duplicate transaction target: {resolved}")
            seen_targets.add(resolved)
            relative = resolved.relative_to(site_root)
            existed = resolved.exists()
            if existed:
                backup = transaction_dir / "backup" / relative
                self._atomic_write(
                    backup,
                    self._read_json(resolved, {}),
                )
            entries.append(
                {
                    "target": str(relative),
                    "existed": existed,
                    "new_hash": self._document_hash(document),
                }
            )
        journal = {
            "transaction_id": transaction_id,
            "site": site,
            "state": "PREPARED",
            "entries": entries,
            "created_at": utc_now(),
        }
        self._atomic_write(self._transaction_journal_path(site), journal)
        try:
            for (target, document), _entry in zip(
                documents,
                entries,
                strict=True,
            ):
                self._atomic_write(target, document)
        except BaseException:
            self._recover_document_transaction(site)
            raise
        self._recover_document_transaction(site)

    @staticmethod
    def _validate_record_map_identity(
        document: dict[str, Any],
        map_name: str,
        id_field: str,
        *,
        site: str = "",
        safe_id: bool = False,
    ) -> None:
        records = document.get(map_name)
        if not isinstance(records, dict):
            return
        for map_key, raw in records.items():
            if not isinstance(raw, dict):
                raise ValueError(f"{map_name}[{map_key!r}] must be an object")
            internal_id = str(raw.get(id_field) or "")
            if str(map_key) != internal_id:
                raise ValueError(
                    f"{map_name} map key {map_key!r} does not match "
                    f"{id_field} {internal_id!r}"
                )
            if site and str(raw.get("site") or "") != site:
                raise ValueError(
                    f"{map_name}[{map_key!r}] belongs to "
                    f"{raw.get('site')!r}, expected {site!r}"
                )
            if safe_id and not SAFE_PROPOSAL_ID_RE.fullmatch(internal_id):
                raise ValueError(f"Unsafe {id_field}: {internal_id!r}")

    @classmethod
    def _validate_registry_map_identities(
        cls,
        registry: dict[str, Any],
        site: str,
    ) -> None:
        cls._validate_record_map_identity(
            registry,
            "topics",
            "topic_id",
            site=site,
        )
        cls._validate_record_map_identity(
            registry,
            "clusters",
            "cluster_id",
            site=site,
        )
        cls._validate_record_map_identity(
            registry,
            "blogger_catalog",
            "publication_key",
        )

    @classmethod
    def _validate_proposal_map_identities(
        cls,
        document: dict[str, Any],
        site: str,
    ) -> None:
        cls._validate_record_map_identity(
            document,
            "proposals",
            "proposal_id",
            site=site,
            safe_id=True,
        )

    def _load_registry(self, site: str) -> dict[str, Any]:
        registry = self._read_json(self.registry_path(site), _default_registry(site))
        registry.setdefault("topics", {})
        registry.setdefault("clusters", {})
        registry.setdefault("aliases", {})
        registry.setdefault("cluster_aliases", {})
        registry.setdefault("publication_index", {})
        registry.setdefault("blogger_catalog", {})
        registry.setdefault("publication_outbox", [])
        registry.setdefault("publish_attempts", {})
        registry.setdefault("publish_attempt_history", [])
        registry.setdefault("publication_receipts", {})
        registry.setdefault("topic_reservations", {})
        registry.setdefault("rollout", _default_registry(site)["rollout"])
        validate_persistent_document("registry", registry, site)
        self._validate_registry_map_identities(registry, site)
        return registry

    def _load_inbox(self, site: str) -> dict[str, Any]:
        inbox = self._read_json(self.inbox_path(site), _default_inbox(site))
        inbox.setdefault("questions", {})
        validate_persistent_document("inbox", inbox, site)
        return inbox

    def _load_categories(self, site: str) -> dict[str, Any]:
        document = self._read_json(self.categories_path(site), _default_categories(site))
        document.setdefault("categories", {})
        validate_persistent_document("categories", document, site)
        return document

    def _load_proposals(self, site: str) -> dict[str, Any]:
        document = self._read_json(self.proposals_path(site), _default_proposals(site))
        document.setdefault("proposals", {})
        validate_persistent_document("proposals", document, site)
        self._validate_proposal_map_identities(document, site)
        return document

    def _save_registry(self, site: str, registry: dict[str, Any]) -> None:
        registry["schema_version"] = SCHEMA_VERSION
        registry["site"] = site
        registry["revision"] = int(registry.get("revision") or 0) + 1
        registry["updated_at"] = utc_now()
        validate_persistent_document("registry", registry, site)
        self._validate_registry_map_identities(registry, site)
        self._atomic_write(self.registry_path(site), registry)

    def _save_inbox(self, site: str, inbox: dict[str, Any]) -> None:
        inbox["schema_version"] = SCHEMA_VERSION
        inbox["site"] = site
        inbox["updated_at"] = utc_now()
        validate_persistent_document("inbox", inbox, site)
        self._atomic_write(self.inbox_path(site), inbox)

    def _save_categories(self, site: str, document: dict[str, Any]) -> None:
        document["schema_version"] = SCHEMA_VERSION
        document["site"] = site
        document["revision"] = int(document.get("revision") or 0) + 1
        document["updated_at"] = utc_now()
        validate_persistent_document("categories", document, site)
        self._atomic_write(self.categories_path(site), document)

    def _save_proposals(self, site: str, document: dict[str, Any]) -> None:
        document["schema_version"] = SCHEMA_VERSION
        document["site"] = site
        document["updated_at"] = utc_now()
        validate_persistent_document("proposals", document, site)
        self._validate_proposal_map_identities(document, site)
        self._atomic_write(self.proposals_path(site), document)

    def ensure_site(
        self,
        site: str,
        categories: list[CategoryRecord] | None = None,
    ) -> None:
        with self._lock(site):
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            category_document = self._load_categories(site)
            proposal_document = self._load_proposals(site)
            for category in categories or []:
                if category.site and category.site != site:
                    raise ValueError(f"Category {category.category_id} belongs to {category.site}")
                category.site = site
                category_document["categories"].setdefault(category.category_id, category.to_dict())
            if not self.registry_path(site).exists():
                self._save_registry(site, registry)
            if not self.inbox_path(site).exists():
                self._save_inbox(site, inbox)
            if not self.categories_path(site).exists() or categories:
                self._save_categories(site, category_document)
            if not self.proposals_path(site).exists():
                self._save_proposals(site, proposal_document)

    # ---- categories -----------------------------------------------------

    def list_categories(self, site: str) -> list[CategoryRecord]:
        document = self._load_categories(site)
        return [
            CategoryRecord.from_dict(item)
            for _, item in sorted(document["categories"].items())
        ]

    def get_category(self, site: str, category_id: str) -> CategoryRecord | None:
        data = self._load_categories(site)["categories"].get(category_id)
        return CategoryRecord.from_dict(data) if isinstance(data, dict) else None

    def category_label_for(self, site: str, category_id: str) -> str:
        category = self.get_category(site, category_id)
        if category is None:
            return ""
        return category.blogger_label or category.name

    def find_category(self, site: str, value: str) -> CategoryRecord | None:
        key = normalize_text(value)
        for category in self.list_categories(site):
            candidates = [
                category.category_id,
                category.name,
                category.blogger_label,
                *category.aliases,
            ]
            if key in {normalize_text(candidate) for candidate in candidates}:
                return category
        return None

    def upsert_category(self, site: str, category: CategoryRecord) -> CategoryRecord:
        category.site = site
        category.category_id = category.category_id or category_id_for(site, category.name)
        with self._lock(site):
            document = self._load_categories(site)
            existing_data = document["categories"].get(category.category_id)
            if existing_data:
                existing = CategoryRecord.from_dict(existing_data)
                category.created_at = existing.created_at
                category.aliases = list(
                    dict.fromkeys([*existing.aliases, *category.aliases])
                )
            category.updated_at = utc_now()
            candidate = category.to_dict()
            if existing_data == candidate:
                return category
            document["categories"][category.category_id] = candidate
            self._save_categories(site, document)
        return category

    # ---- questions ------------------------------------------------------

    def list_questions(self, site: str) -> list[QuestionRecord]:
        inbox = self._load_inbox(site)
        return [
            QuestionRecord.from_dict(item)
            for _, item in sorted(inbox["questions"].items())
        ]

    def get_question(self, site: str, question_id: str) -> QuestionRecord | None:
        data = self._load_inbox(site)["questions"].get(question_id)
        return QuestionRecord.from_dict(data) if isinstance(data, dict) else None

    @staticmethod
    def _question_duplicate_id(
        questions: dict[str, dict[str, Any]],
        incoming: QuestionRecord,
    ) -> str:
        incoming_url = canonical_url(incoming.url)
        for question_id, raw in questions.items():
            existing = QuestionRecord.from_dict(raw)
            same_source_item = (
                incoming.source_item_id
                and existing.source_item_id
                and normalize_text(incoming.source) == normalize_text(existing.source)
                and incoming.source_item_id == existing.source_item_id
            )
            same_url = bool(incoming_url and incoming_url == canonical_url(existing.url))
            same_content = bool(
                incoming.content_hash
                and incoming.content_hash == existing.content_hash
                and normalize_text(incoming.title) == normalize_text(existing.title)
            )
            if same_source_item or same_url or same_content:
                return question_id
        return ""

    def upsert_question(self, site: str, question: QuestionRecord | dict[str, Any]) -> QuestionRecord:
        if isinstance(question, dict):
            question = QuestionRecord.from_dict({**question, "site": site})
        question.site = site
        with self._lock(site):
            inbox = self._load_inbox(site)
            duplicate_id = self._question_duplicate_id(inbox["questions"], question)
            actual_id = duplicate_id or question.question_id
            existing_data = inbox["questions"].get(actual_id)
            if existing_data:
                existing = QuestionRecord.from_dict(existing_data)
                aliases = [*existing.aliases, *question.aliases]
                if question.question_id != actual_id:
                    aliases.append(question.question_id)
                evidence_rank = {
                    EvidenceType.FALLBACK_TEMPLATE: 0,
                    EvidenceType.QUERY_PLAN: 1,
                    EvidenceType.SEARCH_SUGGESTION: 2,
                    EvidenceType.FIRST_PARTY_QUERY: 3,
                    EvidenceType.OBSERVED_QUESTION: 4,
                }
                evidence_type = max(
                    (existing.evidence_type, question.evidence_type),
                    key=lambda value: evidence_rank[value],
                )
                engagement = dict(existing.engagement)
                for key, value in question.engagement.items():
                    engagement[key] = max(float(value), float(engagement.get(key, value)))
                question = QuestionRecord(
                    question_id=actual_id,
                    site=site,
                    source=question.source or existing.source,
                    source_item_id=question.source_item_id or existing.source_item_id,
                    url=question.url or existing.url,
                    title=question.title or existing.title,
                    summary=question.summary or existing.summary,
                    created_at=question.created_at or existing.created_at,
                    collected_at=max(question.collected_at, existing.collected_at),
                    engagement=engagement,
                    content_hash=question.content_hash or existing.content_hash,
                    evidence_type=evidence_type,
                    verification_method=question.verification_method or existing.verification_method,
                    verified_at=question.verified_at or existing.verified_at,
                    verified_by=question.verified_by or existing.verified_by,
                    property_id=question.property_id or existing.property_id,
                    topic_id=question.topic_id or existing.topic_id,
                    aliases=list(dict.fromkeys(aliases)),
                )
            else:
                question.question_id = actual_id
            candidate = question.to_dict()
            if candidate != existing_data:
                inbox["questions"][actual_id] = candidate
                self._save_inbox(site, inbox)
        return question

    # ---- problem clusters ----------------------------------------------

    @staticmethod
    def _resolve_cluster_id(registry: dict[str, Any], cluster_id: str) -> str:
        current = cluster_id
        seen: set[str] = set()
        while current in registry.get("cluster_aliases", {}) and current not in seen:
            seen.add(current)
            current = registry["cluster_aliases"][current]
        return current

    @staticmethod
    def _ensure_cluster_in_registry(
        registry: dict[str, Any],
        site: str,
        *,
        cluster_id: str,
        problem_signature: str,
        canonical_label: str,
        aliases: list[str] | None = None,
        observation_run_ids: list[str] | None = None,
    ) -> ClusterRecord:
        selected_id = cluster_id or stable_id(
            "cluster",
            site,
            problem_signature or canonical_label,
        )
        selected_id = TopicStore._resolve_cluster_id(registry, selected_id)
        raw = registry["clusters"].get(selected_id)
        if raw:
            cluster = ClusterRecord.from_dict(raw)
            cluster.problem_signature = problem_signature or cluster.problem_signature
            cluster.canonical_label = canonical_label or cluster.canonical_label
            cluster.aliases = list(
                dict.fromkeys([*cluster.aliases, *(aliases or [])])
            )
            cluster.observation_run_ids = list(
                dict.fromkeys(
                    [*cluster.observation_run_ids, *(observation_run_ids or [])]
                )
            )
        else:
            cluster = ClusterRecord(
                cluster_id=selected_id,
                site=site,
                problem_signature=problem_signature or canonical_label,
                canonical_label=canonical_label,
                aliases=aliases or [],
                observation_run_ids=observation_run_ids or [],
            )
        registry["clusters"][selected_id] = cluster.to_dict()
        return cluster

    def list_clusters(self, site: str, include_merged: bool = True) -> list[ClusterRecord]:
        registry = self._load_registry(site)
        clusters = [
            ClusterRecord.from_dict(item)
            for _, item in sorted(registry["clusters"].items())
        ]
        if not include_merged:
            clusters = [
                cluster
                for cluster in clusters
                if not cluster.merged_into_cluster_id
            ]
        return clusters

    def get_cluster(
        self,
        site: str,
        cluster_id: str,
        resolve_aliases: bool = True,
    ) -> ClusterRecord | None:
        registry = self._load_registry(site)
        selected_id = (
            self._resolve_cluster_id(registry, cluster_id)
            if resolve_aliases
            else cluster_id
        )
        raw = registry["clusters"].get(selected_id)
        return ClusterRecord.from_dict(raw) if isinstance(raw, dict) else None

    def upsert_cluster(
        self,
        site: str,
        cluster: ClusterRecord | dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> ClusterRecord:
        if isinstance(cluster, dict):
            cluster = ClusterRecord.from_dict({**cluster, "site": site})
        cluster.site = site
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_cluster_id(registry, cluster.cluster_id)
            existing_raw = registry["clusters"].get(resolved_id)
            if existing_raw:
                existing = ClusterRecord.from_dict(existing_raw)
                if expected_revision is not None and existing.revision != expected_revision:
                    raise ValueError(
                        f"Cluster revision conflict for {resolved_id}: "
                        f"expected {expected_revision}, found {existing.revision}"
                    )
                published_identity = any(
                    (
                        TopicRecord.from_dict(registry["topics"][topic_id]).publications
                        or TopicRecord.from_dict(
                            registry["topics"][topic_id]
                        ).status
                        in {
                            TopicStatus.PUBLISHED,
                            TopicStatus.LIVE_UNVERIFIED,
                        }
                    )
                    for topic_id in existing.topic_ids
                    if topic_id in registry["topics"]
                )
                changed_identity_fields = [
                    field
                    for field, changed in (
                        (
                            "problem_signature",
                            cluster.problem_signature
                            != existing.problem_signature,
                        ),
                        (
                            "canonical_label",
                            cluster.canonical_label
                            != existing.canonical_label,
                        ),
                    )
                    if changed
                ]
                if published_identity and changed_identity_fields:
                    raise ValueError(
                        "Published cluster identity is immutable through "
                        "upsert_cluster; use an approved monthly proposal for: "
                        + ", ".join(changed_identity_fields)
                    )
                cluster.cluster_id = resolved_id
                cluster.created_at = existing.created_at
                cluster.question_ids = list(
                    dict.fromkeys([*existing.question_ids, *cluster.question_ids])
                )
                cluster.topic_ids = list(
                    dict.fromkeys([*existing.topic_ids, *cluster.topic_ids])
                )
                cluster.aliases = list(
                    dict.fromkeys([*existing.aliases, *cluster.aliases])
                )
                cluster.observation_run_ids = list(
                    dict.fromkeys(
                        [
                            *existing.observation_run_ids,
                            *cluster.observation_run_ids,
                        ]
                    )
                )
                comparable = cluster.to_dict()
                comparable["revision"] = existing.revision
                comparable["updated_at"] = existing.updated_at
                if comparable == existing_raw:
                    return existing
                cluster.revision = existing.revision + 1
            else:
                cluster.cluster_id = cluster.cluster_id or stable_id(
                    "cluster",
                    site,
                    cluster.problem_signature or cluster.canonical_label,
                )
            cluster.updated_at = utc_now()
            registry["clusters"][cluster.cluster_id] = cluster.to_dict()
            self._save_registry(site, registry)
        return cluster

    @staticmethod
    def _merge_clusters_in_registry(
        registry: dict[str, Any],
        site: str,
        source_cluster_id: str,
        target_cluster_id: str,
        *,
        reason: str = "",
        allow_published: bool = False,
    ) -> ClusterRecord:
        source_id = TopicStore._resolve_cluster_id(registry, source_cluster_id)
        target_id = TopicStore._resolve_cluster_id(registry, target_cluster_id)
        if not source_id or not target_id or source_id == target_id:
            raise ValueError("Cluster merge source and target must differ")
        source_raw = registry["clusters"].get(source_id)
        target_raw = registry["clusters"].get(target_id)
        if not source_raw or not target_raw:
            raise ValueError("Cluster merge source or target is missing")
        source = ClusterRecord.from_dict(source_raw)
        target = ClusterRecord.from_dict(target_raw)
        linked_topic_ids = list(dict.fromkeys([*source.topic_ids, *target.topic_ids]))
        TopicStore._assert_no_blocking_external_attempts(
            registry,
            linked_topic_ids,
            mutation="merge clusters containing",
        )
        published = any(
            TopicRecord.from_dict(registry["topics"][topic_id]).publications
            for topic_id in linked_topic_ids
            if topic_id in registry["topics"]
        )
        if published and not allow_published:
            raise ValueError(
                "Published cluster restructuring requires an approved monthly proposal"
            )
        target.question_ids = list(
            dict.fromkeys([*target.question_ids, *source.question_ids])
        )
        target.topic_ids = linked_topic_ids
        target.aliases = list(
            dict.fromkeys(
                [
                    *target.aliases,
                    source.cluster_id,
                    source.canonical_label,
                    source.problem_signature,
                    *source.aliases,
                ]
            )
        )
        target.observation_run_ids = list(
            dict.fromkeys(
                [*target.observation_run_ids, *source.observation_run_ids]
            )
        )
        target.revision += 1
        target.updated_at = utc_now()
        source.merged_into_cluster_id = target.cluster_id
        source.revision += 1
        source.updated_at = utc_now()
        for topic_id in source.topic_ids:
            raw = registry["topics"].get(topic_id)
            if raw:
                topic = TopicRecord.from_dict(raw)
                topic.cluster_id = target.cluster_id
                topic.revision += 1
                topic.updated_at = utc_now()
                registry["topics"][topic_id] = topic.to_dict()
        registry["clusters"][source.cluster_id] = source.to_dict()
        registry["clusters"][target.cluster_id] = target.to_dict()
        registry["cluster_aliases"][source.cluster_id] = target.cluster_id
        for alias in source.aliases:
            if alias and alias != target.cluster_id:
                registry["cluster_aliases"][alias] = target.cluster_id
        return target

    def merge_clusters(
        self,
        site: str,
        source_cluster_id: str,
        target_cluster_id: str,
        reason: str = "",
        *,
        allow_published: bool = False,
    ) -> ClusterRecord:
        with self._lock(site):
            registry = self._load_registry(site)
            target = self._merge_clusters_in_registry(
                registry,
                site,
                source_cluster_id,
                target_cluster_id,
                reason=reason,
                allow_published=allow_published,
            )
            self._save_registry(site, registry)
        return target

    # ---- topics ---------------------------------------------------------

    @staticmethod
    def _resolve_topic_id(registry: dict[str, Any], topic_id: str) -> str:
        current = topic_id
        seen: set[str] = set()
        while current in registry.get("aliases", {}) and current not in seen:
            seen.add(current)
            current = registry["aliases"][current]
        return current

    def list_topics(self, site: str, include_merged: bool = True) -> list[TopicRecord]:
        registry = self._load_registry(site)
        topics = [
            TopicRecord.from_dict(item)
            for _, item in sorted(registry["topics"].items())
        ]
        if not include_merged:
            topics = [topic for topic in topics if topic.status is not TopicStatus.MERGED]
        return topics

    def get_topic(
        self,
        site: str,
        topic_id: str,
        resolve_aliases: bool = True,
    ) -> TopicRecord | None:
        registry = self._load_registry(site)
        selected_id = (
            self._resolve_topic_id(registry, topic_id) if resolve_aliases else topic_id
        )
        data = registry["topics"].get(selected_id)
        return TopicRecord.from_dict(data) if isinstance(data, dict) else None

    @staticmethod
    def _find_topic_id_by_text(
        registry: dict[str, Any],
        value: str,
        cluster_id: str = "",
        problem_signature: str = "",
    ) -> str:
        text_key = normalize_text(value)
        signature_key = normalize_text(problem_signature)
        for topic_id, raw in registry["topics"].items():
            topic = TopicRecord.from_dict(raw)
            if topic.status is TopicStatus.MERGED:
                continue
            if cluster_id and topic.cluster_id and cluster_id == topic.cluster_id:
                return topic_id
            if signature_key and normalize_text(topic.problem_signature) == signature_key:
                return topic_id
            candidates = [topic.canonical_title, *topic.aliases]
            if text_key and text_key in {normalize_text(candidate) for candidate in candidates}:
                return topic_id
        return ""

    def find_topic_by_text(
        self,
        site: str,
        value: str,
        cluster_id: str = "",
        problem_signature: str = "",
    ) -> TopicRecord | None:
        registry = self._load_registry(site)
        topic_id = self._find_topic_id_by_text(
            registry,
            value,
            cluster_id=cluster_id,
            problem_signature=problem_signature,
        )
        if not topic_id:
            return None
        return TopicRecord.from_dict(registry["topics"][topic_id])

    def create_topic(
        self,
        site: str,
        canonical_title: str,
        category_id: str,
        *,
        identity_key: str = "",
        cluster_id: str = "",
        canonical_intent: str = "",
        problem_signature: str = "",
        aliases: list[str] | None = None,
        action: TopicAction | str = TopicAction.NEW_POST,
        status: TopicStatus | str = TopicStatus.DISCOVERED,
        priority_score: float = 0.0,
        editor_brief: str = "",
        reader_questions: list[str] | None = None,
        difference_from_existing: str = "",
        severity_score: float = 0.0,
        severity_reason: str = "",
        official_source_urls: list[str] | None = None,
        official_source_refs: list[dict[str, str]] | None = None,
        official_answerable: bool = False,
        auditor_decision: str = "",
        auditor_reasons: list[str] | None = None,
        audited_at: str = "",
        evidence_exception: dict[str, str] | None = None,
        topic_id: str = "",
    ) -> TopicRecord:
        if not canonical_title.strip():
            raise ValueError("canonical_title is required")
        if self.get_category(site, category_id) is None:
            raise ValueError(f"Unknown category for {site}: {category_id}")
        with self._lock(site):
            registry = self._load_registry(site)
            existing_id = self._find_topic_id_by_text(
                registry,
                canonical_title,
                cluster_id=cluster_id,
                problem_signature=problem_signature,
            )
            if existing_id:
                return TopicRecord.from_dict(registry["topics"][existing_id])
            stable_topic_id = topic_id or topic_id_for(
                site,
                identity_key or cluster_id or problem_signature or canonical_title,
            )
            if stable_topic_id in registry["topics"]:
                existing = TopicRecord.from_dict(registry["topics"][stable_topic_id])
                if normalize_text(existing.canonical_title) != normalize_text(canonical_title):
                    raise ValueError(f"Stable topic id collision: {stable_topic_id}")
                return existing
            selected_cluster_id = cluster_id or stable_id(
                "cluster",
                site,
                problem_signature or canonical_title,
            )
            cluster = self._ensure_cluster_in_registry(
                registry,
                site,
                cluster_id=selected_cluster_id,
                problem_signature=problem_signature or canonical_title,
                canonical_label=canonical_title,
                aliases=aliases,
            )
            topic = TopicRecord(
                topic_id=stable_topic_id,
                site=site,
                canonical_title=canonical_title.strip(),
                category_id=category_id,
                cluster_id=cluster.cluster_id,
                canonical_intent=canonical_intent,
                problem_signature=problem_signature,
                aliases=aliases or [],
                action=action,
                status=status,
                priority_score=priority_score,
                editor_brief=editor_brief,
                reader_questions=reader_questions or [],
                difference_from_existing=difference_from_existing,
                severity_score=severity_score,
                severity_reason=severity_reason,
                official_source_urls=official_source_urls or [],
                official_source_refs=official_source_refs or [],
                official_answerable=official_answerable,
                auditor_decision=auditor_decision,
                auditor_reasons=auditor_reasons or [],
                audited_at=audited_at,
                evidence_exception=evidence_exception or {},
            )
            registry["topics"][topic.topic_id] = topic.to_dict()
            cluster.topic_ids = list(dict.fromkeys([*cluster.topic_ids, topic.topic_id]))
            cluster.updated_at = utc_now()
            registry["clusters"][cluster.cluster_id] = cluster.to_dict()
            self._save_registry(site, registry)
        return topic

    def upsert_topic(
        self,
        site: str,
        topic: TopicRecord | dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> TopicRecord:
        if isinstance(topic, dict):
            topic = TopicRecord.from_dict({**topic, "site": site})
        topic.site = site
        if not topic.topic_id:
            topic.topic_id = topic_id_for(
                site,
                topic.cluster_id
                or topic.problem_signature
                or topic.canonical_title,
            )
        if self.get_category(site, topic.category_id) is None:
            raise ValueError(f"Unknown category for {site}: {topic.category_id}")

        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic.topic_id)
            existing_data = registry["topics"].get(resolved_id)
            if existing_data:
                existing = TopicRecord.from_dict(existing_data)
                if expected_revision is not None and existing.revision != expected_revision:
                    raise ValueError(
                        f"Revision conflict for {resolved_id}: "
                        f"expected {expected_revision}, found {existing.revision}"
                    )
                immutable_identity_changes = [
                    field
                    for field, changed in (
                        (
                            "canonical_title",
                            topic.canonical_title != existing.canonical_title,
                        ),
                        (
                            "category_id",
                            topic.category_id != existing.category_id,
                        ),
                        (
                            "cluster_id",
                            topic.cluster_id != existing.cluster_id,
                        ),
                        (
                            "canonical_intent",
                            topic.canonical_intent != existing.canonical_intent,
                        ),
                        (
                            "problem_signature",
                            topic.problem_signature != existing.problem_signature,
                        ),
                    )
                    if changed
                ]
                if (
                    existing.status
                    in {
                        TopicStatus.PUBLISHED,
                        TopicStatus.LIVE_UNVERIFIED,
                    }
                    and immutable_identity_changes
                ):
                    raise ValueError(
                        f"{existing.status.value} topic identity is immutable through "
                        "upsert_topic; use an approved monthly proposal for: "
                        + ", ".join(immutable_identity_changes)
                    )
                protected_identity_changed = any(
                    (
                        topic.action is not existing.action,
                        topic.canonical_title != existing.canonical_title,
                        topic.category_id != existing.category_id,
                        topic.cluster_id != existing.cluster_id,
                        topic.canonical_intent != existing.canonical_intent,
                        topic.problem_signature != existing.problem_signature,
                        topic.merged_into_topic_id != existing.merged_into_topic_id,
                    )
                )
                if protected_identity_changed:
                    self._assert_no_blocking_external_attempts(
                        registry,
                        [resolved_id],
                        mutation="change action or identity for",
                    )
                topic.topic_id = resolved_id
                topic.created_at = existing.created_at
                topic.question_ids = list(
                    dict.fromkeys([*existing.question_ids, *topic.question_ids])
                )
                topic.aliases = list(dict.fromkeys([*existing.aliases, *topic.aliases]))
                topic.reader_questions = list(
                    dict.fromkeys([*existing.reader_questions, *topic.reader_questions])
                )
                topic.editor_notes = list(
                    dict.fromkeys([*existing.editor_notes, *topic.editor_notes])
                )
                topic.official_source_urls = list(
                    dict.fromkeys(
                        [*existing.official_source_urls, *topic.official_source_urls]
                    )
                )
                existing_refs = {
                    (item.get("url", ""), item.get("authority_type", "")): item
                    for item in existing.official_source_refs
                }
                for item in topic.official_source_refs:
                    existing_refs[
                        (item.get("url", ""), item.get("authority_type", ""))
                    ] = item
                topic.official_source_refs = list(existing_refs.values())
                topic.publications = self._merge_publication_lists(
                    existing.publications,
                    topic.publications,
                )
                topic.revision = existing.revision
            else:
                topic.revision = max(1, topic.revision)

            topic.cluster_id = topic.cluster_id or stable_id(
                "cluster",
                site,
                topic.problem_signature or topic.canonical_title,
            )
            cluster = self._ensure_cluster_in_registry(
                registry,
                site,
                cluster_id=topic.cluster_id,
                problem_signature=topic.problem_signature or topic.canonical_title,
                canonical_label=topic.canonical_title,
                aliases=topic.aliases,
            )
            cluster.topic_ids = list(dict.fromkeys([*cluster.topic_ids, topic.topic_id]))
            cluster.updated_at = utc_now()
            registry["clusters"][cluster.cluster_id] = cluster.to_dict()

            comparable = topic.to_dict()
            if existing_data:
                comparable["updated_at"] = existing_data.get("updated_at", "")
                comparable["revision"] = existing_data.get("revision", 1)
            if comparable == existing_data:
                return TopicRecord.from_dict(existing_data)

            if existing_data:
                topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][topic.topic_id] = topic.to_dict()
            for publication in topic.publications:
                for key in (
                    publication_key(publication.blogger_post_id, ""),
                    publication_key("", publication.url),
                ):
                    if not key or key == "url:":
                        continue
                    owner = registry["publication_index"].get(key)
                    if owner and owner != topic.topic_id:
                        raise ValueError(f"Publication {key} already belongs to {owner}")
                    registry["publication_index"][key] = topic.topic_id
            self._save_registry(site, registry)
        return topic

    @staticmethod
    def _merge_publication_lists(
        left: list[PublicationRef],
        right: list[PublicationRef],
    ) -> list[PublicationRef]:
        publications = [
            deepcopy(publication)
            for publication in [*left, *right]
            if publication.blogger_post_id or canonical_url(publication.url)
        ]
        parents = list(range(len(publications)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left_index: int, right_index: int) -> None:
            left_root = find(left_index)
            right_root = find(right_index)
            if left_root != right_root:
                parents[right_root] = left_root

        id_owner: dict[str, int] = {}
        url_owner: dict[str, int] = {}
        for index, publication in enumerate(publications):
            identities = (
                (id_owner, publication.blogger_post_id.strip()),
                (url_owner, canonical_url(publication.url)),
            )
            for owners, identity in identities:
                if not identity:
                    continue
                previous_index = owners.get(identity)
                if previous_index is not None:
                    union(previous_index, index)
                else:
                    owners[identity] = index

        groups: dict[int, list[int]] = {}
        for index in range(len(publications)):
            groups.setdefault(find(index), []).append(index)

        merged: list[PublicationRef] = []
        for indices in sorted(groups.values(), key=lambda value: value[0]):
            selected = publications[indices[0]]
            for index in indices[1:]:
                publication = publications[index]
                selected = PublicationRef(
                    blogger_post_id=(
                        selected.blogger_post_id or publication.blogger_post_id
                    ),
                    url=selected.url or publication.url,
                    title=selected.title or publication.title,
                    status=(
                        "LIVE"
                        if "LIVE"
                        in {selected.status.upper(), publication.status.upper()}
                        else selected.status or publication.status
                    ),
                    published_at=selected.published_at or publication.published_at,
                    updated_at=max(selected.updated_at, publication.updated_at),
                    last_verified_at=max(
                        selected.last_verified_at,
                        publication.last_verified_at,
                    ),
                    # The later full record is authoritative for primary
                    # selection. Initial migration uses explicit False for
                    # historical secondary posts.
                    primary=publication.primary,
                )
            merged.append(selected)
        return merged

    def link_question(self, site: str, question_id: str, topic_id: str) -> TopicRecord:
        with self._lock(site):
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            if resolved_id not in registry["topics"]:
                raise ValueError(f"Unknown topic: {topic_id}")
            if question_id not in inbox["questions"]:
                raise ValueError(f"Unknown question: {question_id}")
            question = QuestionRecord.from_dict(inbox["questions"][question_id])
            if question.topic_id and question.topic_id != resolved_id:
                prior_data = registry["topics"].get(question.topic_id)
                if prior_data:
                    prior = TopicRecord.from_dict(prior_data)
                    prior.question_ids = [
                        item for item in prior.question_ids if item != question_id
                    ]
                    prior.revision += 1
                    prior.updated_at = utc_now()
                    registry["topics"][prior.topic_id] = prior.to_dict()
            topic = TopicRecord.from_dict(registry["topics"][resolved_id])
            if question_id not in topic.question_ids:
                topic.question_ids.append(question_id)
                topic.revision += 1
                topic.updated_at = utc_now()
            question.topic_id = resolved_id
            if topic.cluster_id:
                cluster_id = self._resolve_cluster_id(registry, topic.cluster_id)
                cluster_raw = registry["clusters"].get(cluster_id)
                if cluster_raw:
                    cluster = ClusterRecord.from_dict(cluster_raw)
                    cluster.question_ids = list(
                        dict.fromkeys([*cluster.question_ids, question_id])
                    )
                    cluster.topic_ids = list(
                        dict.fromkeys([*cluster.topic_ids, topic.topic_id])
                    )
                    cluster.updated_at = utc_now()
                    registry["clusters"][cluster_id] = cluster.to_dict()
            inbox["questions"][question_id] = question.to_dict()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_inbox(site, inbox)
            self._save_registry(site, registry)
        return topic

    def recalculate_priority(self, site: str, topic_id: str) -> TopicRecord:
        with self._lock(site):
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(data)
            linked = [
                QuestionRecord.from_dict(inbox["questions"][question_id])
                for question_id in topic.question_ids
                if question_id in inbox["questions"]
            ]
            gate = evidence_gate(topic, linked)
            eligible = [
                question
                for question in linked
                if question.question_id in gate.eligible_question_ids
            ]
            components = {key: 0.0 for key in PRIORITY_COMPONENT_MAX}
            is_candidate = (
                topic.action in PRIORITY_ACTIONS
                and topic.status in PRIORITY_CANDIDATE_STATUSES
            )
            if is_candidate:
                sources = {
                    normalize_text(question.source)
                    for question in eligible
                }
                verified_url_bonus = 4.0 if any(
                    canonical_url(question.url) for question in eligible
                ) else 0.0
                components["evidence_strength"] = min(
                    PRIORITY_COMPONENT_MAX["evidence_strength"],
                    gate.independent_evidence_count * 7.0
                    + min(4.0, len(sources) * 2.0)
                    + min(
                        4.0,
                        math.log2(
                            sum(
                                max(question.engagement.values(), default=0.0)
                                for question in eligible
                            )
                            + 1.0
                        ),
                    )
                    + min(3.0, verified_url_bonus),
                )

                cluster_data = registry["clusters"].get(topic.cluster_id)
                observation_runs = (
                    ClusterRecord.from_dict(cluster_data).observation_run_ids
                    if cluster_data
                    else []
                )
                recurrence_units = max(
                    gate.independent_evidence_count,
                    len(set(observation_runs)),
                )
                components["recurrence"] = min(
                    PRIORITY_COMPONENT_MAX["recurrence"],
                    max(0, recurrence_units - 1) * 10.0,
                )

                if topic.action is TopicAction.NEW_POST:
                    components["content_gap"] = (
                        PRIORITY_COMPONENT_MAX["content_gap"]
                        if not topic.publications
                        else 0.0
                    )
                else:
                    components["content_gap"] = (
                        PRIORITY_COMPONENT_MAX["content_gap"]
                        if topic.difference_from_existing.strip()
                        else 10.0
                    )

                components["severity"] = (
                    topic.severity_score
                    if (
                        topic.auditor_decision == "PASS"
                        and topic.audited_at
                        and topic.severity_reason.strip()
                        and 0.0 <= topic.severity_score <= 15.0
                    )
                    else 0.0
                )

                valid_official_refs = [
                    ref
                    for ref in topic.official_source_refs
                    if canonical_url(str(ref.get("url") or ""))
                    and str(ref.get("authority_type") or "").strip()
                ]
                if (
                    topic.official_answerable
                    and valid_official_refs
                    and topic.auditor_decision == "PASS"
                ):
                    components["answerability"] = 10.0
                elif topic.official_answerable and valid_official_refs:
                    components["answerability"] = 7.0
                elif valid_official_refs:
                    components["answerability"] = 3.0

                newest: datetime | None = None
                for question in eligible:
                    raw_timestamp = question.created_at or question.collected_at
                    try:
                        parsed = datetime.fromisoformat(
                            raw_timestamp.replace("Z", "+00:00")
                        )
                    except (TypeError, ValueError):
                        continue
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    parsed = parsed.astimezone(timezone.utc)
                    newest = parsed if newest is None or parsed > newest else newest
                if newest is not None:
                    age_days = max(
                        0.0,
                        (datetime.now(timezone.utc) - newest).total_seconds()
                        / 86400.0,
                    )
                    components["recency"] = (
                        10.0
                        if age_days <= 7
                        else 8.0
                        if age_days <= 30
                        else 5.0
                        if age_days <= 90
                        else 2.0
                        if age_days <= 365
                        else 0.0
                    )
            components = {
                key: round(
                    max(0.0, min(PRIORITY_COMPONENT_MAX[key], value)),
                    2,
                )
                for key, value in components.items()
            }
            calculated_score = round(min(100.0, sum(components.values())), 2)
            score = (
                round(topic.priority_override, 2)
                if is_candidate and topic.priority_override is not None
                else calculated_score
                if is_candidate
                else 0.0
            )
            if topic.priority_score == score and topic.priority_components == components:
                return topic
            topic.priority_score = score
            topic.priority_components = components
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    def refresh_duplicate_candidates(
        self,
        site: str,
        topic_id: str,
        threshold: float = 0.86,
    ) -> TopicRecord:
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(data)
            duplicates: list[str] = []
            for other_id, other_data in registry["topics"].items():
                if other_id == resolved_id:
                    continue
                other = TopicRecord.from_dict(other_data)
                if other.status in {TopicStatus.MERGED, TopicStatus.REJECTED}:
                    continue
                if topic_similarity(topic, other) >= threshold:
                    duplicates.append(other_id)
            for key, entry in registry.get("blogger_catalog", {}).items():
                catalog_topic_id = self._resolve_topic_id(
                    registry,
                    str(entry.get("topic_id") or ""),
                )
                if catalog_topic_id == resolved_id:
                    continue
                title = str(entry.get("title") or "")
                candidate_texts = [
                    topic.canonical_title,
                    topic.problem_signature,
                    " ".join(
                        item
                        for item in (
                            topic.canonical_title,
                            topic.canonical_intent,
                        )
                        if item
                    ),
                ]
                if title and max(
                    (
                        semantic_text_similarity(candidate, title)
                        for candidate in candidate_texts
                    ),
                    default=0.0,
                ) >= threshold:
                    duplicates.append(f"blogger:{key}")
            duplicates.sort()
            duplicates = list(dict.fromkeys(duplicates))
            if duplicates != topic.duplicate_candidate_ids:
                topic.duplicate_candidate_ids = duplicates
                if duplicates and topic.status is TopicStatus.READY:
                    topic.status = TopicStatus.REVIEW
                    topic.status_reason = "similar topic requires merge/update review"
                topic.revision += 1
                topic.updated_at = utc_now()
                registry["topics"][resolved_id] = topic.to_dict()
                self._save_registry(site, registry)
        return topic

    def record_blogger_catalog_snapshot(
        self,
        site: str,
        entries: list[dict[str, Any]],
        *,
        complete: bool,
    ) -> int:
        """Persist a content-free Blogger title index for duplicate checks."""

        normalized: dict[str, dict[str, Any]] = {}
        for raw in entries:
            publication = PublicationRef.from_dict(raw)
            key = publication_key(
                publication.blogger_post_id,
                publication.url,
            )
            if not key or key == "url:" or not publication.title.strip():
                continue
            normalized[key] = {
                "publication_key": key,
                "blogger_post_id": publication.blogger_post_id,
                "url": canonical_url(publication.url),
                "title": publication.title.strip(),
                "status": publication.status,
                "published_at": publication.published_at,
                "updated_at": publication.updated_at,
                "last_seen_at": str(raw.get("last_seen_at") or ""),
                "topic_id": str(raw.get("topic_id") or ""),
                "has_topic_marker": bool(raw.get("has_topic_marker", False)),
            }
        with self._lock(site):
            registry = self._load_registry(site)
            previous = dict(registry.get("blogger_catalog") or {})
            selected = normalized if complete else {**previous, **normalized}
            if selected == previous:
                return len(selected)
            registry["blogger_catalog"] = selected
            self._save_registry(site, registry)
        return len(selected)

    @staticmethod
    def _topic_semantic_texts(topic: TopicRecord) -> list[str]:
        return list(
            dict.fromkeys(
                value
                for value in (
                    topic.canonical_title,
                    topic.problem_signature,
                    " ".join(
                        item
                        for item in (
                            topic.problem_signature or topic.canonical_title,
                            topic.canonical_intent,
                        )
                        if item
                    ),
                )
                if value.strip()
            )
        )

    def semantic_publication_duplicates(
        self,
        site: str,
        topic_ids: list[str] | set[str] | tuple[str, ...] | None = None,
        *,
        threshold: float = 0.86,
    ) -> dict[str, list[str]]:
        """Compare candidates with Registry/live Blogger titles server-side."""

        registry = self._load_registry(site)
        topics = {
            topic_id: TopicRecord.from_dict(raw)
            for topic_id, raw in registry["topics"].items()
        }
        selected_ids = (
            {
                self._resolve_topic_id(registry, topic_id)
                for topic_id in topic_ids
            }
            if topic_ids is not None
            else {
                topic.topic_id
                for topic in topics.values()
                if topic.status is TopicStatus.READY
            }
        )
        published = [
            topic
            for topic in topics.values()
            if topic.status in {
                TopicStatus.PUBLISHED,
                TopicStatus.LIVE_UNVERIFIED,
            }
        ]
        result: dict[str, list[str]] = {}
        for topic_id in sorted(selected_ids):
            candidate = topics.get(topic_id)
            if candidate is None:
                continue
            candidate_texts = self._topic_semantic_texts(candidate)
            duplicates: set[str] = set()
            for existing in published:
                if existing.topic_id == topic_id:
                    continue
                score = max(
                    (
                        semantic_text_similarity(left, right)
                        for left in candidate_texts
                        for right in self._topic_semantic_texts(existing)
                    ),
                    default=0.0,
                )
                if score >= threshold:
                    duplicates.add(existing.topic_id)
            for key, entry in registry.get("blogger_catalog", {}).items():
                mapped_topic_id = self._resolve_topic_id(
                    registry,
                    str(entry.get("topic_id") or ""),
                )
                if mapped_topic_id == topic_id:
                    continue
                if mapped_topic_id in duplicates:
                    continue
                title = str(entry.get("title") or "")
                score = max(
                    (
                        semantic_text_similarity(value, title)
                        for value in candidate_texts
                    ),
                    default=0.0,
                )
                if score >= threshold:
                    duplicates.add(f"blogger:{key}")
            if duplicates:
                result[topic_id] = sorted(duplicates)
        return result

    def ready_blockers(self, site: str, topic_id: str) -> list[str]:
        topic = self.get_topic(site, topic_id)
        if topic is None:
            return [f"unknown topic: {topic_id}"]
        questions = self.list_questions(site)
        return ready_blockers(
            topic,
            questions,
            self.get_category(site, topic.category_id),
        )

    @staticmethod
    def _allowed_transition(current: TopicStatus, target: TopicStatus) -> bool:
        if current is target:
            return True
        transitions = {
            TopicStatus.DISCOVERED: {
                TopicStatus.REVIEW,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.REVIEW: {
                TopicStatus.READY,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.READY: {
                TopicStatus.SCHEDULED,
                TopicStatus.CLAIMED,
                TopicStatus.HOLD,
                TopicStatus.REVIEW,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.SCHEDULED: {
                TopicStatus.CLAIMED,
                TopicStatus.READY,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.CLAIMED: {
                TopicStatus.GENERATED,
                TopicStatus.READY,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.GENERATED: {
                TopicStatus.LIVE_UNVERIFIED,
                TopicStatus.READY,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.LIVE_UNVERIFIED: {
                TopicStatus.PUBLISHED,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.PUBLISHED: {
                TopicStatus.UPDATE_DUE,
                TopicStatus.HOLD,
                TopicStatus.STALE,
            },
            TopicStatus.UPDATE_DUE: {
                TopicStatus.READY,
                TopicStatus.CLAIMED,
                TopicStatus.HOLD,
                TopicStatus.STALE,
            },
            TopicStatus.HOLD: {
                TopicStatus.REVIEW,
                TopicStatus.READY,
                TopicStatus.REJECTED,
                TopicStatus.STALE,
            },
            TopicStatus.STALE: {
                TopicStatus.REVIEW,
                TopicStatus.HOLD,
                TopicStatus.REJECTED,
            },
            TopicStatus.REJECTED: {TopicStatus.REVIEW},
            TopicStatus.MERGED: set(),
        }
        return target in transitions.get(current, set())

    def mark_topic_status(
        self,
        site: str,
        topic_id: str,
        status: TopicStatus | str,
        reason: str = "",
        *,
        expected_revision: int | None = None,
        run_id: str = "",
    ) -> TopicRecord:
        target = status if isinstance(status, TopicStatus) else TopicStatus(str(status).upper())
        with self._lock(site):
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            categories = self._load_categories(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(data)
            if expected_revision is not None and topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if not self._allowed_transition(topic.status, target):
                raise ValueError(
                    f"Invalid topic transition: {topic.status.value} -> {target.value}"
                )
            if target is TopicStatus.READY:
                linked = [
                    QuestionRecord.from_dict(item)
                    for item in inbox["questions"].values()
                ]
                category_data = categories["categories"].get(topic.category_id)
                category = CategoryRecord.from_dict(category_data) if category_data else None
                blockers = ready_blockers(topic, linked, category)
                if blockers:
                    raise ValueError("READY gate failed: " + "; ".join(blockers))
            if target is TopicStatus.GENERATED:
                if not run_id or topic.claim_run_id != run_id:
                    raise ValueError("GENERATED transition requires the active claim run_id")
            if target is TopicStatus.PUBLISHED:
                verified_live = any(
                    publication.last_verified_at
                    and publication.status.upper() in {"LIVE", "PUBLISHED"}
                    for publication in topic.publications
                )
                if not verified_live:
                    raise ValueError(
                        "PUBLISHED transition requires a verified live publication"
                    )
            topic.status = target
            topic.status_reason = reason
            if target is TopicStatus.CLAIMED:
                topic.claim_run_id = run_id
            elif target not in {TopicStatus.GENERATED, TopicStatus.LIVE_UNVERIFIED}:
                topic.claim_run_id = ""
            topic.revision += 1
            topic.updated_at = utc_now()
            topic.last_validated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    def approve_evidence_exception(
        self,
        site: str,
        topic_id: str,
        *,
        approved_by: str,
        reason: str,
        basis: str,
        decision_id: str,
        expected_revision: int,
        approved_at: str = "",
    ) -> TopicRecord:
        """Persist a revision-checked human decision for a single-signal gate."""

        approver = approved_by.strip()
        normalized_approver = normalize_text(approver).replace(" ", "_")
        approver_tokens = set(normalized_approver.split("_"))
        if not approver:
            raise ValueError("approved_by is required")
        if (
            normalized_approver in {
                "codex",
                "openai",
                "automation",
                "agent",
                "system",
            }
            or bool(
                approver_tokens
                & {"codex", "openai", "automation", "agent", "bot", "system"}
            )
            or normalized_approver.endswith("_bot")
        ):
            raise ValueError("automated actors cannot approve evidence exceptions")
        selected_basis = basis.strip().upper()
        if selected_basis not in HIGH_CONFIDENCE_EVIDENCE_BASES:
            raise ValueError(f"Unsupported evidence exception basis: {basis}")
        if not reason.strip():
            raise ValueError("reason is required")
        if not decision_id.strip():
            raise ValueError("decision_id is required")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            topic.evidence_exception = {
                "approved_by": approver,
                "approved_at": approved_at.strip() or utc_now(),
                "reason": reason.strip(),
                "basis": selected_basis,
                "approval_source": "USER_DECISION",
                "decision_id": decision_id.strip(),
            }
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    def list_ready_topics(
        self,
        site: str,
        limit: int | None = None,
        *,
        require_rollout_gate: bool = True,
    ) -> list[TopicRecord]:
        if require_rollout_gate and self.get_rollout_mode(site) != ROLLOUT_READY_FIRST:
            return []
        topics = [
            topic
            for topic in self.list_topics(site, include_merged=False)
            if topic.status is TopicStatus.READY
            and topic.action
            in {
                TopicAction.NEW_POST,
                TopicAction.UPDATE_EXISTING,
                TopicAction.FAQ_ADD,
            }
        ]
        topics.sort(
            key=lambda topic: (
                -topic.priority_score,
                topic.updated_at,
                topic.topic_id,
            )
        )
        return topics[:limit] if limit is not None else topics

    def claim_ready_topic(
        self,
        site: str,
        run_id: str,
        topic_id: str | None = None,
        expected_revision: int | None = None,
    ) -> TopicRecord | None:
        if not run_id.strip():
            raise ValueError("run_id is required")
        if self.get_rollout_mode(site) != ROLLOUT_READY_FIRST:
            return None
        with self._lock(site):
            registry = self._load_registry(site)
            candidates: list[TopicRecord] = []
            if topic_id:
                resolved_id = self._resolve_topic_id(registry, topic_id)
                data = registry["topics"].get(resolved_id)
                if data:
                    candidates = [TopicRecord.from_dict(data)]
            else:
                candidates = [
                    TopicRecord.from_dict(data)
                    for data in registry["topics"].values()
                    if str(data.get("status") or "").upper() == TopicStatus.READY.value
                ]
                candidates.sort(
                    key=lambda topic: (
                        -topic.priority_score,
                        topic.updated_at,
                        topic.topic_id,
                    )
                )
            if not candidates:
                return None
            topic = candidates[0]
            if topic.status is TopicStatus.CLAIMED:
                return topic if topic.claim_run_id == run_id else None
            if topic.status not in {
                TopicStatus.READY,
                TopicStatus.SCHEDULED,
                TopicStatus.UPDATE_DUE,
            }:
                return None
            if expected_revision is not None and topic.revision != expected_revision:
                return None
            topic.status = TopicStatus.CLAIMED
            topic.claim_run_id = run_id
            topic.status_reason = f"claimed by {run_id}"
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][topic.topic_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    def claim_topic(
        self,
        site: str,
        topic_id: str,
        run_id: str,
        expected_revision: int | None = None,
    ) -> TopicRecord | None:
        return self.claim_ready_topic(
            site,
            run_id,
            topic_id=topic_id,
            expected_revision=expected_revision,
        )

    def release_claim(
        self,
        site: str,
        topic_id: str,
        run_id: str,
        status: TopicStatus | str = TopicStatus.READY,
        reason: str = "",
    ) -> TopicRecord | None:
        target = status if isinstance(status, TopicStatus) else TopicStatus(str(status).upper())
        if target not in {TopicStatus.READY, TopicStatus.HOLD, TopicStatus.STALE}:
            raise ValueError("Claims may only be released to READY, HOLD, or STALE")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                return None
            topic = TopicRecord.from_dict(data)
            if (
                topic.status not in {TopicStatus.CLAIMED, TopicStatus.GENERATED}
                or topic.claim_run_id != run_id
            ):
                return None
            topic.status = target
            topic.claim_run_id = ""
            topic.status_reason = reason or f"claim released by {run_id}"
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    # ---- rollout --------------------------------------------------------

    @staticmethod
    def _kst_datetime(value: str) -> datetime | None:
        if not value:
            return None
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(candidate[:10])
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(KST)

    @classmethod
    def _is_sunday_20_kst(cls, value: str) -> bool:
        selected = cls._kst_datetime(value)
        if selected is None:
            return False
        return selected.weekday() == 6 and selected.hour == 20

    @classmethod
    def _kst_iso_week(cls, value: str) -> str:
        selected = cls._kst_datetime(value)
        if selected is None:
            return ""
        iso_year, iso_week, _ = selected.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"

    def get_rollout_state(self, site: str) -> dict[str, Any]:
        registry = self._load_registry(site)
        default = _default_registry(site)["rollout"]
        state = {**default, **dict(registry.get("rollout") or {})}
        state["backfill"] = {
            **dict(default.get("backfill") or {}),
            **dict(state.get("backfill") or {}),
        }
        return deepcopy(state)

    def rollout_state(self, site: str) -> dict[str, Any]:
        return self.get_rollout_state(site)

    def get_rollout_mode(self, site: str) -> str:
        return str(self.get_rollout_state(site).get("mode") or ROLLOUT_SHADOW)

    def record_rollout_run(
        self,
        site: str,
        run_id: str,
        status: str,
        *,
        run_at: str = "",
        qualifying: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a collector run without double-counting reruns.

        Promotion requires two consecutive, distinct, successful Sunday runs.
        Once promoted, a degraded run temporarily selects the legacy fallback;
        the next healthy run returns to READY_FIRST without losing promotion.
        """

        if not run_id.strip():
            raise ValueError("run_id is required")
        normalized_status = status.strip().upper()
        if normalized_status not in {"SUCCESS", "DEGRADED", "FAILED"}:
            raise ValueError("rollout run status must be SUCCESS, DEGRADED, or FAILED")
        selected_at = run_at or utc_now()
        run_details = dict(details or {})
        run_type = str(run_details.get("run_type") or "")
        with self._lock(site):
            registry = self._load_registry(site)
            state = {
                **_default_registry(site)["rollout"],
                **dict(registry.get("rollout") or {}),
            }
            state["backfill"] = {
                **dict(_default_registry(site)["rollout"]["backfill"]),
                **dict(state.get("backfill") or {}),
            }
            recent_runs = list(state.get("recent_runs") or [])
            for prior in recent_runs:
                if prior.get("run_id") == run_id:
                    return deepcopy(state)

            promoted = bool(state.get("promoted"))
            count = int(state.get("consecutive_qualifying_runs") or 0)
            if run_type == "BACKFILL_RESEARCH" and (
                run_details.get("coverage_hash")
                or run_details.get("campaign_id")
            ):
                backfill_complete = (
                    normalized_status == "SUCCESS"
                    and bool(run_details.get("complete"))
                    and bool(run_details.get("schema_valid"))
                    and not list(run_details.get("unexplored_scope") or [])
                    and bool(str(run_details.get("coverage_hash") or "").strip())
                )
                state["backfill"] = {
                    "complete": backfill_complete,
                    "last_run_id": run_id,
                    "completed_at": selected_at if backfill_complete else "",
                    "coverage_hash": str(run_details.get("coverage_hash") or ""),
                    "logic_version": str(run_details.get("logic_version") or ""),
                    "unexplored_scope": list(
                        run_details.get("unexplored_scope") or []
                    ),
                }

            locator_coverage = float(
                run_details.get("ready_evidence_locator_coverage")
                if run_details.get("ready_evidence_locator_coverage") is not None
                else run_details.get("ready_evidence_url_coverage") or 0.0
            )
            required_checks = (
                run_type == "WEEKLY_RESEARCH",
                bool(state["backfill"].get("complete")),
                bool(run_details.get("complete")),
                bool(run_details.get("schema_valid")),
                locator_coverage == 1.0,
                int(run_details.get("synthetic_influence_count") or 0) == 0,
                int(run_details.get("blogger_duplicate_count") or 0) == 0,
                bool(run_details.get("auditor_passed")),
                int(run_details.get("source_count") or 0) > 0,
            )
            base_qualifies = (
                normalized_status == "SUCCESS"
                and self._is_sunday_20_kst(selected_at)
                and all(required_checks)
                and qualifying is not False
            )
            selected_datetime = self._kst_datetime(selected_at)
            selected_week = self._kst_iso_week(selected_at)
            prior_qualifying = [
                item
                for item in recent_runs
                if item.get("qualifying") is True
                and str((item.get("details") or {}).get("run_type") or "")
                == "WEEKLY_RESEARCH"
            ]
            prior_qualifying.sort(
                key=lambda item: str(item.get("run_at") or "")
            )
            last_qualifying = prior_qualifying[-1] if prior_qualifying else None
            last_datetime = (
                self._kst_datetime(str(last_qualifying.get("run_at") or ""))
                if last_qualifying
                else None
            )
            last_week = (
                str((last_qualifying.get("details") or {}).get("iso_week") or "")
                or self._kst_iso_week(str(last_qualifying.get("run_at") or ""))
                if last_qualifying
                else ""
            )
            same_or_older_week = bool(
                last_qualifying
                and (
                    selected_week == last_week
                    or (
                        selected_datetime is not None
                        and last_datetime is not None
                        and selected_datetime <= last_datetime
                    )
                )
            )
            qualifies = base_qualifies and not same_or_older_week
            run_details["backfill_complete"] = bool(
                state["backfill"].get("complete")
            )
            run_details["iso_week"] = selected_week
            if same_or_older_week and base_qualifies:
                run_details["qualification_reason"] = (
                    "same or older KST ISO week already counted"
                )
            elif not bool(state["backfill"].get("complete")):
                run_details["qualification_reason"] = (
                    "required backfill is incomplete"
                )
            elif qualifies:
                run_details["qualification_reason"] = "all rollout gates passed"
            else:
                run_details["qualification_reason"] = (
                    "one or more rollout gates failed"
                )
            if run_type != "WEEKLY_RESEARCH":
                # Backfills/audits belong in run history but cannot disturb the
                # operational weekly rollout streak or mode.
                mode = str(state.get("mode") or ROLLOUT_SHADOW)
            elif normalized_status in {"DEGRADED", "FAILED"}:
                if not promoted:
                    count = 0
                mode = ROLLOUT_DEGRADED
            elif qualifies:
                if not promoted:
                    if (
                        last_datetime is not None
                        and selected_datetime is not None
                        and (selected_datetime.date() - last_datetime.date()).days
                        != 7
                    ):
                        count = 1
                    else:
                        count += 1
                    promoted = count >= int(
                        state.get("required_qualifying_runs") or ROLLOUT_REQUIRED_RUNS
                    )
                mode = ROLLOUT_READY_FIRST if promoted else ROLLOUT_SHADOW
            elif same_or_older_week and base_qualifies:
                mode = (
                    ROLLOUT_READY_FIRST
                    if promoted
                    else str(state.get("mode") or ROLLOUT_SHADOW)
                )
            else:
                if not promoted:
                    count = 0
                    mode = ROLLOUT_SHADOW
                else:
                    # Promotion is remembered, but a healthy-looking run that
                    # misses any safety check selects the fallback until the
                    # next genuinely qualifying run.
                    mode = ROLLOUT_DEGRADED

            run_record = {
                "run_id": run_id,
                "run_at": selected_at,
                "status": normalized_status,
                "qualifying": qualifies,
                "mode_after": mode,
                "details": run_details,
            }
            recent_runs.append(run_record)
            state.update(
                {
                    "mode": mode,
                    "promoted": promoted,
                    "consecutive_qualifying_runs": count,
                    "recent_runs": recent_runs[-24:],
                }
            )
            if run_type == "WEEKLY_RESEARCH":
                state.update(
                    {
                        "last_run_id": run_id,
                        "last_run_at": selected_at,
                        "last_status": normalized_status,
                    }
                )
            registry["rollout"] = state
            self._save_registry(site, registry)
        return deepcopy(state)

    # Backwards-compatible name for callers built against the first draft.
    def record_shadow_run(
        self,
        site: str,
        success: bool,
        run_id: str = "",
        error: str = "",
        run_at: str = "",
        qualifying: bool | None = None,
    ) -> dict[str, Any]:
        return self.record_rollout_run(
            site,
            run_id or stable_id("run", site, utc_now()),
            "SUCCESS" if success else "DEGRADED",
            run_at=run_at,
            qualifying=qualifying,
            details={"error": error} if error else {},
        )

    # ---- publication mapping/outbox ------------------------------------

    def record_publication(
        self,
        site: str,
        topic_id: str,
        publication: PublicationRef | dict[str, Any],
        *,
        expected_revision: int | None = None,
        run_id: str = "",
    ) -> TopicRecord:
        """Record a publish result while enforcing the single-insert invariant."""
        return self._record_publication(
            site,
            topic_id,
            publication,
            expected_revision=expected_revision,
            run_id=run_id,
            reconcile_existing=False,
        )

    def reconcile_publication(
        self,
        site: str,
        topic_id: str,
        publication: PublicationRef | dict[str, Any],
    ) -> TopicRecord:
        """Reconcile a Blogger snapshot without treating history as a new insert.

        A live topic can legitimately have older posts that cover the same intent.
        Existing publication roles are authoritative during reconciliation, and a
        newly discovered post becomes historical when a NEW_POST topic already has
        a primary publication.
        """
        return self._record_publication(
            site,
            topic_id,
            publication,
            reconcile_existing=True,
        )

    def _record_publication(
        self,
        site: str,
        topic_id: str,
        publication: PublicationRef | dict[str, Any],
        *,
        expected_revision: int | None = None,
        run_id: str = "",
        reconcile_existing: bool,
    ) -> TopicRecord:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        key = publication_key(publication.blogger_post_id, publication.url)
        if not key or key == "url:":
            raise ValueError("Publication requires blogger_post_id or url")
        publication_keys = [
            selected
            for selected in (
                publication_key(publication.blogger_post_id, ""),
                publication_key("", publication.url),
            )
            if selected and selected != "url:"
        ]
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(data)
            if expected_revision is not None and topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if run_id and topic.claim_run_id and topic.claim_run_id != run_id:
                raise ValueError("Publication run_id does not own the active claim")
            if topic.action is TopicAction.NEW_POST:
                primary = [item for item in topic.publications if item.primary]
                existing_publication = next(
                    (
                        item
                        for item in topic.publications
                        if self._same_publication(item, publication)
                    ),
                    None,
                )
                if reconcile_existing and existing_publication is not None:
                    publication.primary = existing_publication.primary
                elif reconcile_existing and primary:
                    publication.primary = False
                elif primary and not any(
                    self._same_publication(item, publication) for item in primary
                ):
                    raise ValueError(
                        "NEW_POST topic already owns a different primary publication"
                    )
                else:
                    publication.primary = True
            index_changed = False
            for selected_key in publication_keys:
                owner = registry["publication_index"].get(selected_key)
                if owner and self._resolve_topic_id(registry, owner) != resolved_id:
                    raise ValueError(
                        f"Publication {selected_key} already belongs to {owner}"
                    )
                index_changed = index_changed or owner != resolved_id
            previous_publications = [
                item.to_dict() for item in topic.publications
            ]
            merged_publications = self._merge_publication_lists(
                topic.publications,
                [publication],
            )
            next_status = topic.status
            next_reason = topic.status_reason
            next_claim_run_id = topic.claim_run_id
            for selected_key in publication_keys:
                registry["publication_index"][selected_key] = resolved_id
            verified_live = (
                publication.last_verified_at
                and publication.status.upper() in {"LIVE", "PUBLISHED"}
            )
            if verified_live:
                next_status = TopicStatus.PUBLISHED
                next_claim_run_id = ""
                next_reason = "verified Blogger publication"
            elif topic.status is not TopicStatus.PUBLISHED:
                next_status = TopicStatus.LIVE_UNVERIFIED
                next_reason = "Blogger returned a publication; public URL is not verified"
            if (
                previous_publications
                == [item.to_dict() for item in merged_publications]
                and topic.status is next_status
                and topic.status_reason == next_reason
                and topic.claim_run_id == next_claim_run_id
                and not index_changed
            ):
                return topic
            topic.publications = merged_publications
            topic.status = next_status
            topic.status_reason = next_reason
            topic.claim_run_id = next_claim_run_id
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            for entry in registry["publication_outbox"]:
                if entry.get("publication_key") in publication_keys:
                    stages = dict(entry.get("stages") or {})
                    stages["registry"] = "SUCCESS"
                    if verified_live:
                        stages["blogger"] = "SUCCESS"
                    entry["stages"] = stages
                    entry["updated_at"] = utc_now()
            self._save_registry(site, registry)
        return topic

    def verify_publication(
        self,
        site: str,
        topic_id: str,
        *,
        blogger_post_id: str = "",
        url: str = "",
        verified_at: str = "",
        status: str = "LIVE",
    ) -> TopicRecord:
        key = publication_key(blogger_post_id, url)
        if not key or key == "url:":
            raise ValueError("blogger_post_id or url is required")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            data = registry["topics"].get(resolved_id)
            if not data:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(data)
            found = False
            for publication in topic.publications:
                if publication_key(publication.blogger_post_id, publication.url) == key:
                    publication.last_verified_at = verified_at or utc_now()
                    publication.status = status
                    if url:
                        publication.url = canonical_url(url)
                    found = True
                    break
            if not found:
                raise ValueError(f"Publication is not mapped to topic: {key}")
            if status.upper() in {"LIVE", "PUBLISHED"}:
                topic.status = TopicStatus.PUBLISHED
                topic.claim_run_id = ""
                topic.status_reason = "public URL verified"
            topic.revision += 1
            topic.updated_at = utc_now()
            registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
        return topic

    def enqueue_publication_sync(
        self,
        site: str,
        topic_id: str,
        publication: PublicationRef | dict[str, Any],
        error: str = "",
    ) -> dict[str, Any]:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        key = publication_key(publication.blogger_post_id, publication.url)
        if not key or key == "url:":
            raise ValueError("Publication requires blogger_post_id or url")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            if resolved_id not in registry["topics"]:
                raise ValueError(f"Unknown topic: {topic_id}")
            outbox_id = stable_id("pubsync", site, resolved_id, key)
            existing = next(
                (
                    item
                    for item in registry["publication_outbox"]
                    if item.get("outbox_id") == outbox_id
                ),
                None,
            )
            entry = {
                "outbox_id": outbox_id,
                "site": site,
                "topic_id": resolved_id,
                "publication_key": key,
                "publication": publication.to_dict(),
                "status": "PENDING",
                "attempts": int((existing or {}).get("attempts") or 0) + 1,
                "last_error": error,
                "stages": dict(
                    (existing or {}).get("stages")
                    or {
                        "blogger": "PENDING",
                        "registry": "PENDING",
                        "sheet": "PENDING",
                    }
                ),
                "next_retry_at": (existing or {}).get("next_retry_at") or "",
                "created_at": (existing or {}).get("created_at") or utc_now(),
                "updated_at": utc_now(),
            }
            registry["publication_outbox"] = [
                item
                for item in registry["publication_outbox"]
                if item.get("outbox_id") != outbox_id
            ]
            registry["publication_outbox"].append(entry)
            self._save_registry(site, registry)
        return entry

    def list_publication_outbox(self, site: str) -> list[dict[str, Any]]:
        return deepcopy(self._load_registry(site).get("publication_outbox") or [])

    def acknowledge_publication_sync(self, site: str, outbox_id: str) -> bool:
        with self._lock(site):
            registry = self._load_registry(site)
            entry = next(
                (
                    item
                    for item in registry["publication_outbox"]
                    if item.get("outbox_id") == outbox_id
                ),
                None,
            )
            if entry is None:
                return False
            stages = dict(entry.get("stages") or {})
            if not all(
                stages.get(stage) == "SUCCESS"
                for stage in ("blogger", "registry", "sheet")
            ):
                raise ValueError(
                    "Outbox may only be acknowledged after Blogger, Registry, and Sheet succeed"
                )
            before = len(registry["publication_outbox"])
            registry["publication_outbox"] = [
                item
                for item in registry["publication_outbox"]
                if item.get("outbox_id") != outbox_id
            ]
            if len(registry["publication_outbox"]) == before:
                return False
            self._save_registry(site, registry)
        return True

    def mark_publication_outbox_stage(
        self,
        site: str,
        outbox_id: str,
        stage: str,
        *,
        success: bool,
        error: str = "",
    ) -> dict[str, Any]:
        if stage not in {"blogger", "registry", "sheet"}:
            raise ValueError("Outbox stage must be blogger, registry, or sheet")
        with self._lock(site):
            registry = self._load_registry(site)
            entry = next(
                (
                    item
                    for item in registry["publication_outbox"]
                    if item.get("outbox_id") == outbox_id
                ),
                None,
            )
            if entry is None:
                raise ValueError(f"Unknown outbox item: {outbox_id}")
            stages = dict(entry.get("stages") or {})
            stages[stage] = "SUCCESS" if success else "FAILED"
            entry["stages"] = stages
            entry["last_error"] = "" if success else error
            entry["attempts"] = int(entry.get("attempts") or 0) + 1
            entry["updated_at"] = utc_now()
            if not success:
                delay_minutes = min(1440, 2 ** min(entry["attempts"], 10))
                entry["next_retry_at"] = (
                    datetime.now(tz=timezone.utc) + timedelta(minutes=delay_minutes)
                ).isoformat()
            self._save_registry(site, registry)
            return deepcopy(entry)

    def expire_stale_scheduled(
        self,
        site: str,
        older_than_hours: float,
        *,
        now: str = "",
    ) -> list[TopicRecord]:
        if older_than_hours <= 0:
            raise ValueError("older_than_hours must be positive")
        selected_now = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00"))
        if selected_now.tzinfo is None:
            selected_now = selected_now.replace(tzinfo=timezone.utc)
        expired: list[TopicRecord] = []
        with self._lock(site):
            registry = self._load_registry(site)
            for topic_id, raw in list(registry["topics"].items()):
                topic = TopicRecord.from_dict(raw)
                if topic.status is not TopicStatus.SCHEDULED:
                    continue
                try:
                    updated = datetime.fromisoformat(
                        topic.updated_at.replace("Z", "+00:00")
                    )
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                except ValueError:
                    updated = datetime.min.replace(tzinfo=timezone.utc)
                age_hours = (
                    selected_now.astimezone(timezone.utc)
                    - updated.astimezone(timezone.utc)
                ).total_seconds() / 3600
                if age_hours <= older_than_hours:
                    continue
                topic.status = TopicStatus.STALE
                topic.status_reason = (
                    f"scheduled claim expired after {age_hours:.1f} hours"
                )
                topic.claim_run_id = ""
                topic.revision += 1
                topic.updated_at = utc_now()
                registry["topics"][topic_id] = topic.to_dict()
                expired.append(topic)
            if expired:
                self._save_registry(site, registry)
        return expired

    # ---- merge and maintenance -----------------------------------------

    def merge_topics(
        self,
        site: str,
        source_topic_id: str,
        target_topic_id: str,
        reason: str = "",
        *,
        allow_published: bool = False,
    ) -> TopicRecord:
        if source_topic_id == target_topic_id:
            raise ValueError("Cannot merge a topic into itself")
        with self._lock(site):
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            # A source is deliberately loaded raw so it can become an alias.
            source_data = registry["topics"].get(source_topic_id)
            target_id = self._resolve_topic_id(registry, target_topic_id)
            target_data = registry["topics"].get(target_id)
            if not source_data or not target_data:
                raise ValueError("Source or target topic is missing")
            source = TopicRecord.from_dict(source_data)
            target = TopicRecord.from_dict(target_data)
            self._assert_no_blocking_external_attempts(
                registry,
                [source.topic_id, target.topic_id],
                mutation="merge",
            )
            if (
                not allow_published
                and (
                    source.publications
                    or target.publications
                    or source.status
                    in {TopicStatus.PUBLISHED, TopicStatus.LIVE_UNVERIFIED}
                    or target.status
                    in {TopicStatus.PUBLISHED, TopicStatus.LIVE_UNVERIFIED}
                )
            ):
                raise ValueError(
                    "Published clusters may only be merged through an approved monthly proposal"
                )
            if (
                source.cluster_id
                and target.cluster_id
                and self._resolve_cluster_id(registry, source.cluster_id)
                != self._resolve_cluster_id(registry, target.cluster_id)
            ):
                merged_cluster = self._merge_clusters_in_registry(
                    registry,
                    site,
                    source.cluster_id,
                    target.cluster_id,
                    reason=reason,
                    allow_published=allow_published,
                )
                source.cluster_id = merged_cluster.cluster_id
                target.cluster_id = merged_cluster.cluster_id
            target.question_ids = list(
                dict.fromkeys([*target.question_ids, *source.question_ids])
            )
            target.aliases = list(
                dict.fromkeys(
                    [
                        *target.aliases,
                        source.topic_id,
                        source.canonical_title,
                        *source.aliases,
                    ]
                )
            )
            target.reader_questions = list(
                dict.fromkeys([*target.reader_questions, *source.reader_questions])
            )
            target.publications = self._merge_publication_lists(
                target.publications,
                source.publications,
            )
            target.priority_score = max(target.priority_score, source.priority_score)
            if target.publications:
                target.status = (
                    TopicStatus.PUBLISHED
                    if any(item.last_verified_at for item in target.publications)
                    else TopicStatus.LIVE_UNVERIFIED
                )
            target.revision += 1
            target.updated_at = utc_now()

            source.status = TopicStatus.MERGED
            source.action = TopicAction.MERGE
            source.merged_into_topic_id = target.topic_id
            source.status_reason = reason or f"merged into {target.topic_id}"
            source.claim_run_id = ""
            source.revision += 1
            source.updated_at = utc_now()
            registry["topics"][target.topic_id] = target.to_dict()
            registry["topics"][source.topic_id] = source.to_dict()
            for alias in [source.topic_id, *source.aliases]:
                if alias != target.topic_id:
                    registry["aliases"][alias] = target.topic_id
            for publication in target.publications:
                key = publication_key(publication.blogger_post_id, publication.url)
                if key and key != "url:":
                    registry["publication_index"][key] = target.topic_id
            for question_id in source.question_ids:
                raw = inbox["questions"].get(question_id)
                if raw:
                    question = QuestionRecord.from_dict(raw)
                    question.topic_id = target.topic_id
                    inbox["questions"][question_id] = question.to_dict()
            self._save_inbox(site, inbox)
            self._save_registry(site, registry)
        return target

    def list_maintenance_topics(
        self,
        site: str,
        actions: tuple[str, ...] | tuple[TopicAction, ...] = (
            TopicAction.UPDATE_EXISTING,
            TopicAction.FAQ_ADD,
        ),
        statuses: tuple[str, ...] | tuple[TopicStatus, ...] = (
            TopicStatus.READY,
            TopicStatus.UPDATE_DUE,
        ),
    ) -> list[TopicRecord]:
        action_values = {
            item.value if isinstance(item, TopicAction) else str(item).upper()
            for item in actions
        }
        status_values = {
            item.value if isinstance(item, TopicStatus) else str(item).upper()
            for item in statuses
        }
        topics = [
            topic
            for topic in self.list_topics(site, include_merged=False)
            if topic.action.value in action_values and topic.status.value in status_values
        ]
        topics.sort(key=lambda item: (-item.priority_score, item.topic_id))
        return topics

    # ---- monthly proposal approval gate --------------------------------

    def create_monthly_proposal(
        self,
        site: str,
        kind: ProposalKind | str,
        payload: dict[str, Any],
        reason: str = "",
        proposal_id: str = "",
    ) -> MonthlyProposal:
        selected_kind = kind if isinstance(kind, ProposalKind) else ProposalKind(str(kind).upper())
        if proposal_id and not SAFE_PROPOSAL_ID_RE.fullmatch(proposal_id):
            raise ValueError(
                "proposal_id must match "
                f"{SAFE_PROPOSAL_ID_RE.pattern!r}: {proposal_id!r}"
            )
        stable_proposal_id = proposal_id or stable_id(
            "proposal",
            site,
            selected_kind.value,
            json.dumps(payload, sort_keys=True, ensure_ascii=False),
        )
        proposal = MonthlyProposal(
            proposal_id=stable_proposal_id,
            site=site,
            kind=selected_kind,
            payload=deepcopy(payload),
            reason=reason,
        )
        with self._lock(site):
            document = self._load_proposals(site)
            existing = document["proposals"].get(stable_proposal_id)
            if existing:
                existing_proposal = MonthlyProposal.from_dict(existing)
                if (
                    existing_proposal.site != proposal.site
                    or existing_proposal.kind is not proposal.kind
                    or existing_proposal.payload != proposal.payload
                    or existing_proposal.reason != proposal.reason
                ):
                    raise ValueError(
                        f"Proposal id collision with different immutable content: "
                        f"{stable_proposal_id}"
                    )
                return existing_proposal
            document["proposals"][stable_proposal_id] = proposal.to_dict()
            self._save_proposals(site, document)
        return proposal

    def list_monthly_proposals(self, site: str) -> list[MonthlyProposal]:
        document = self._load_proposals(site)
        return [
            MonthlyProposal.from_dict(item)
            for _, item in sorted(document["proposals"].items())
        ]

    def get_monthly_proposal(self, site: str, proposal_id: str) -> MonthlyProposal | None:
        data = self._load_proposals(site)["proposals"].get(proposal_id)
        return MonthlyProposal.from_dict(data) if isinstance(data, dict) else None

    def _proposal_threshold_errors(
        self,
        site: str,
        proposal: MonthlyProposal,
    ) -> list[str]:
        if proposal.kind not in {
            ProposalKind.CREATE_CATEGORY,
            ProposalKind.SPLIT_CATEGORY,
        }:
            return []
        registry = self._load_registry(site)
        payload = proposal.payload
        valid_weekly_run_ids = {
            str(item.get("run_id") or "")
            for item in registry.get("rollout", {}).get("recent_runs", [])
            if item.get("qualifying") is True
            and item.get("status") == "SUCCESS"
            and item.get("details", {}).get("run_type") == "WEEKLY_RESEARCH"
        }

        errors: list[str] = []

        def unique_cluster_ids(value: Any, label: str) -> list[str]:
            if not isinstance(value, list):
                errors.append(f"{label} cluster_ids must be a list")
                return []
            selected: list[str] = []
            seen: set[str] = set()
            duplicates: set[str] = set()
            for raw_cluster_id in value:
                cluster_id = str(raw_cluster_id or "").strip()
                if not cluster_id:
                    errors.append(f"{label} contains an empty cluster ID")
                    continue
                if cluster_id in seen:
                    duplicates.add(cluster_id)
                    continue
                seen.add(cluster_id)
                selected.append(cluster_id)
            if duplicates:
                errors.append(
                    f"{label} contains duplicate cluster IDs: "
                    + ", ".join(sorted(duplicates))
                )
            return selected

        def counts(cluster_ids: list[str]) -> tuple[int, int, int]:
            clusters = [
                ClusterRecord.from_dict(registry["clusters"][cluster_id])
                for cluster_id in cluster_ids
                if cluster_id in registry["clusters"]
            ]
            clusters = [
                cluster
                for cluster in clusters
                if cluster.site == site and not cluster.merged_into_cluster_id
            ]
            run_ids = {
                run_id
                for cluster in clusters
                for run_id in cluster.observation_run_ids
                if run_id in valid_weekly_run_ids
            }
            topic_ids = {
                topic_id for cluster in clusters for topic_id in cluster.topic_ids
            }
            ready_published = sum(
                1
                for topic_id in topic_ids
                if topic_id in registry["topics"]
                and TopicRecord.from_dict(registry["topics"][topic_id]).status
                in {
                    TopicStatus.READY,
                    TopicStatus.PUBLISHED,
                }
            )
            return len(clusters), len(run_ids), ready_published

        if proposal.kind is ProposalKind.CREATE_CATEGORY:
            cluster_ids = unique_cluster_ids(
                payload.get("cluster_ids") or [],
                "CREATE_CATEGORY",
            )
            cluster_count, run_count, topic_count = counts(cluster_ids)
            if cluster_count < 5 or run_count < 3 or topic_count < 3:
                errors.append(
                    "CREATE_CATEGORY needs 5 active clusters, 3 weekly observations, "
                    "and 3 READY/PUBLISHED topics"
                )
        else:
            groups = payload.get("groups") or payload.get("new_categories") or []
            if not isinstance(groups, list):
                errors.append("SPLIT_CATEGORY groups/new_categories must be a list")
                groups = []
            elif not groups:
                errors.append("SPLIT_CATEGORY requires groups/new_categories")
            assigned_cluster_ids: set[str] = set()
            for index, group in enumerate(groups):
                if not isinstance(group, dict):
                    errors.append(f"SPLIT_CATEGORY group {index} must be an object")
                    continue
                cluster_ids = unique_cluster_ids(
                    group.get("cluster_ids") or [],
                    f"SPLIT_CATEGORY group {index}",
                )
                cross_group_duplicates = assigned_cluster_ids.intersection(cluster_ids)
                if cross_group_duplicates:
                    errors.append(
                        "SPLIT_CATEGORY assigns cluster IDs to multiple groups: "
                        + ", ".join(sorted(cross_group_duplicates))
                    )
                assigned_cluster_ids.update(cluster_ids)
                cluster_count, _, topic_count = counts(cluster_ids)
                if cluster_count < 4 or topic_count < 2:
                    errors.append(
                        f"SPLIT_CATEGORY group {index} needs 4 clusters and "
                        "2 READY/PUBLISHED topics"
                    )
        return errors

    def approve_monthly_proposal(
        self,
        site: str,
        proposal_id: str,
        approved_by: str,
        reason: str = "",
    ) -> MonthlyProposal:
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        with self._lock(site):
            document = self._load_proposals(site)
            data = document["proposals"].get(proposal_id)
            if not data:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(data)
            if proposal.status is ProposalStatus.APPROVED:
                return proposal
            if proposal.status is not ProposalStatus.PROPOSED:
                raise ValueError(
                    f"Only PROPOSED items may be approved; found {proposal.status.value}"
                )
            threshold_errors = self._proposal_threshold_errors(site, proposal)
            if threshold_errors:
                raise ValueError("; ".join(threshold_errors))
            proposal.status = ProposalStatus.APPROVED
            proposal.approved_by = approved_by.strip()
            proposal.approved_at = utc_now()
            proposal.reviewer_notes = reason
            document["proposals"][proposal_id] = proposal.to_dict()
            self._save_proposals(site, document)
        return proposal

    def reject_monthly_proposal(
        self,
        site: str,
        proposal_id: str,
        rejected_by: str,
        reason: str = "",
    ) -> MonthlyProposal:
        if not rejected_by.strip():
            raise ValueError("rejected_by is required")
        with self._lock(site):
            document = self._load_proposals(site)
            data = document["proposals"].get(proposal_id)
            if not data:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(data)
            if proposal.status is not ProposalStatus.PROPOSED:
                raise ValueError("Only PROPOSED items may be rejected")
            proposal.status = ProposalStatus.REJECTED
            proposal.approved_by = rejected_by.strip()
            proposal.approved_at = utc_now()
            proposal.reviewer_notes = reason
            document["proposals"][proposal_id] = proposal.to_dict()
            self._save_proposals(site, document)
        return proposal

    @staticmethod
    def _proposal_snapshot(
        categories: dict[str, Any],
        registry: dict[str, Any],
        inbox: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "captured_at": utc_now(),
            "categories": deepcopy(categories),
            "topics": deepcopy(registry.get("topics") or {}),
            "clusters": deepcopy(registry.get("clusters") or {}),
            "aliases": deepcopy(registry.get("aliases") or {}),
            "cluster_aliases": deepcopy(registry.get("cluster_aliases") or {}),
            "publication_index": deepcopy(registry.get("publication_index") or {}),
            "question_topic_links": {
                question_id: str(raw.get("topic_id") or "")
                for question_id, raw in (inbox.get("questions") or {}).items()
            },
        }

    @staticmethod
    def _proposal_label_rollback_payload(
        proposal: MonthlyProposal,
        categories_after: dict[str, Any],
        registry_after: dict[str, Any],
    ) -> dict[str, Any]:
        before = proposal.label_snapshot
        before_categories = dict(
            (before.get("categories") or {}).get("categories") or {}
        )
        after_categories = dict(categories_after.get("categories") or {})
        before_topics = dict(before.get("topics") or {})
        affected: list[dict[str, str]] = []
        for topic_id, after_raw in sorted(
            (registry_after.get("topics") or {}).items()
        ):
            before_raw = before_topics.get(topic_id)
            if not isinstance(before_raw, dict):
                continue
            before_topic = TopicRecord.from_dict(before_raw)
            after_topic = TopicRecord.from_dict(after_raw)
            before_category = before_categories.get(before_topic.category_id) or {}
            after_category = after_categories.get(after_topic.category_id) or {}
            old_label = str(before_category.get("blogger_label") or "")
            new_label = str(after_category.get("blogger_label") or "")
            if not old_label or not new_label or old_label == new_label:
                continue
            for publication in after_topic.publications:
                if not publication.blogger_post_id:
                    continue
                affected.append(
                    {
                        "topic_id": topic_id,
                        "blogger_post_id": publication.blogger_post_id,
                        "url": publication.url,
                        "old_category_id": before_topic.category_id,
                        "new_category_id": after_topic.category_id,
                        "old_label": old_label,
                        "new_label": new_label,
                    }
                )
        return {
            "schema_version": 1,
            "proposal_id": proposal.proposal_id,
            "site": proposal.site,
            "snapshot_path": proposal.snapshot_path,
            "prepared_at": utc_now(),
            "affected_publications": affected,
        }

    def apply_monthly_proposal(self, site: str, proposal_id: str) -> MonthlyProposal:
        with self._lock(site):
            proposal_document = self._load_proposals(site)
            raw = proposal_document["proposals"].get(proposal_id)
            if not raw:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(raw)
            if proposal.status is ProposalStatus.APPLIED:
                return proposal
            if proposal.publication_sync_pending:
                return proposal
            if proposal.status is not ProposalStatus.APPROVED:
                raise ValueError("Proposal must be APPROVED before it can be applied")
            threshold_errors = self._proposal_threshold_errors(site, proposal)
            if threshold_errors:
                raise ValueError("; ".join(threshold_errors))

            categories = self._load_categories(site)
            registry = self._load_registry(site)
            inbox = self._load_inbox(site)
            snapshot_path = (
                self.site_dir(site)
                / "snapshots"
                / f"{proposal.proposal_id}.before.json"
            )
            candidate_snapshot = self._proposal_snapshot(categories, registry, inbox)
            if snapshot_path.exists():
                existing_snapshot = self._read_json(snapshot_path, {})
                existing_structural = {
                    key: value
                    for key, value in existing_snapshot.items()
                    if key != "captured_at"
                }
                candidate_structural = {
                    key: value
                    for key, value in candidate_snapshot.items()
                    if key != "captured_at"
                }
                if existing_structural != candidate_structural:
                    raise ValueError(
                        f"Immutable proposal snapshot already differs: {snapshot_path}"
                    )
                proposal.label_snapshot = existing_snapshot
            else:
                proposal.label_snapshot = candidate_snapshot
                self._atomic_write(snapshot_path, proposal.label_snapshot)
            proposal.snapshot_path = str(snapshot_path)
            payload = proposal.payload

            if proposal.kind is ProposalKind.CREATE_CATEGORY:
                category_raw = dict(payload.get("category") or payload)
                name = str(category_raw.get("name") or "").strip()
                if not name:
                    raise ValueError("CREATE_CATEGORY requires category.name")
                category = CategoryRecord.from_dict(
                    {
                        **category_raw,
                        "site": site,
                        "category_id": category_raw.get("category_id")
                        or category_id_for(site, name),
                    }
                )
                categories["categories"][category.category_id] = category.to_dict()

            elif proposal.kind in {
                ProposalKind.RENAME_CATEGORY,
                ProposalKind.LABEL_CHANGE,
            }:
                category_id = str(payload.get("category_id") or "")
                data = categories["categories"].get(category_id)
                if not data:
                    raise ValueError(f"Unknown category: {category_id}")
                category = CategoryRecord.from_dict(data)
                old_name = category.name
                if proposal.kind is ProposalKind.RENAME_CATEGORY:
                    category.name = str(payload.get("name") or "").strip()
                    if not category.name:
                        raise ValueError("RENAME_CATEGORY requires name")
                    if old_name and old_name != category.name:
                        category.aliases = list(
                            dict.fromkeys([*category.aliases, old_name])
                        )
                if "blogger_label" in payload:
                    category.blogger_label = str(payload.get("blogger_label") or "").strip()
                category.updated_at = utc_now()
                categories["categories"][category_id] = category.to_dict()

            elif proposal.kind is ProposalKind.MERGE_CATEGORY:
                source_id = str(payload.get("source_category_id") or "")
                target_id = str(payload.get("target_category_id") or "")
                if source_id == target_id:
                    raise ValueError("Category merge source and target must differ")
                source_raw = categories["categories"].get(source_id)
                target_raw = categories["categories"].get(target_id)
                if not source_raw or not target_raw:
                    raise ValueError("Category merge source or target is missing")
                affected_topic_ids = [
                    topic_id
                    for topic_id, topic_raw in registry["topics"].items()
                    if TopicRecord.from_dict(topic_raw).category_id == source_id
                ]
                self._assert_no_blocking_external_attempts(
                    registry,
                    affected_topic_ids,
                    mutation="reassign category for",
                )
                source = CategoryRecord.from_dict(source_raw)
                target = CategoryRecord.from_dict(target_raw)
                target.aliases = list(
                    dict.fromkeys(
                        [
                            *target.aliases,
                            source.category_id,
                            source.name,
                            source.blogger_label,
                            *source.aliases,
                        ]
                    )
                )
                source.status = "MERGED"
                source.updated_at = utc_now()
                target.updated_at = utc_now()
                categories["categories"][source_id] = source.to_dict()
                categories["categories"][target_id] = target.to_dict()
                for topic_id, topic_raw in registry["topics"].items():
                    topic = TopicRecord.from_dict(topic_raw)
                    if topic.category_id == source_id:
                        topic.category_id = target_id
                        topic.revision += 1
                        topic.updated_at = utc_now()
                        registry["topics"][topic_id] = topic.to_dict()

            elif proposal.kind in {
                ProposalKind.REASSIGN_CATEGORY,
                ProposalKind.SPLIT_CATEGORY,
            }:
                for category_raw in payload.get("new_categories", []):
                    name = str(category_raw.get("name") or "").strip()
                    if not name:
                        raise ValueError("New split category requires name")
                    category = CategoryRecord.from_dict(
                        {
                            **category_raw,
                            "site": site,
                            "category_id": category_raw.get("category_id")
                            or category_id_for(site, name),
                        }
                    )
                    categories["categories"][category.category_id] = category.to_dict()
                assignments = dict(payload.get("assignments") or {})
                if proposal.kind is ProposalKind.REASSIGN_CATEGORY and not assignments:
                    topic_id = str(payload.get("topic_id") or "")
                    category_id = str(payload.get("category_id") or "")
                    assignments = {topic_id: category_id}
                for topic_id, category_id in assignments.items():
                    if category_id not in categories["categories"]:
                        raise ValueError(f"Unknown reassignment category: {category_id}")
                    resolved_id = self._resolve_topic_id(registry, topic_id)
                    topic_raw = registry["topics"].get(resolved_id)
                    if not topic_raw:
                        raise ValueError(f"Unknown reassignment topic: {topic_id}")
                    self._assert_no_blocking_external_attempts(
                        registry,
                        [resolved_id],
                        mutation="reassign category for",
                    )
                    topic = TopicRecord.from_dict(topic_raw)
                    topic.category_id = category_id
                    topic.revision += 1
                    topic.updated_at = utc_now()
                    registry["topics"][resolved_id] = topic.to_dict()

            elif proposal.kind is ProposalKind.MERGE_CLUSTER:
                source_id = str(
                    payload.get("source_cluster_id")
                    or payload.get("source_topic_id")
                    or ""
                )
                target_id = str(
                    payload.get("target_cluster_id")
                    or payload.get("target_topic_id")
                    or ""
                )
                self._merge_clusters_in_registry(
                    registry,
                    site,
                    source_id,
                    target_id,
                    reason=proposal.reason,
                    allow_published=True,
                )

            elif proposal.kind is ProposalKind.SPLIT_CLUSTER:
                source_id = self._resolve_cluster_id(
                    registry,
                    str(
                        payload.get("source_cluster_id")
                        or payload.get("source_topic_id")
                        or ""
                    ),
                )
                source_raw = registry["clusters"].get(source_id)
                if not source_raw:
                    raise ValueError("SPLIT_CLUSTER source cluster is missing")
                source = ClusterRecord.from_dict(source_raw)
                assigned_questions: set[str] = set()
                assigned_topics: set[str] = set()
                new_clusters = payload.get("new_clusters") or []
                if not new_clusters:
                    raise ValueError("SPLIT_CLUSTER requires new_clusters")
                moved_topic_ids = {
                    str(topic_id)
                    for new_raw in new_clusters
                    for topic_id in new_raw.get("topic_ids", [])
                    if str(topic_id) in source.topic_ids
                }
                self._assert_no_blocking_external_attempts(
                    registry,
                    moved_topic_ids,
                    mutation="split cluster identity for",
                )
                for new_raw in new_clusters:
                    signature = str(
                        new_raw.get("problem_signature")
                        or new_raw.get("canonical_label")
                        or ""
                    ).strip()
                    new_cluster_id = str(
                        new_raw.get("cluster_id")
                        or stable_id("cluster", site, signature)
                    )
                    if not signature or new_cluster_id in registry["clusters"]:
                        raise ValueError(
                            "Split cluster requires a unique id and problem_signature"
                        )
                    question_ids = [
                        item
                        for item in new_raw.get("question_ids", [])
                        if item in source.question_ids
                    ]
                    topic_ids = [
                        item
                        for item in new_raw.get("topic_ids", [])
                        if item in source.topic_ids
                    ]
                    assigned_questions.update(question_ids)
                    assigned_topics.update(topic_ids)
                    new_cluster = ClusterRecord.from_dict(
                        {
                            **new_raw,
                            "cluster_id": new_cluster_id,
                            "site": site,
                            "problem_signature": signature,
                            "question_ids": question_ids,
                            "topic_ids": topic_ids,
                            "observation_run_ids": source.observation_run_ids,
                        }
                    )
                    registry["clusters"][new_cluster_id] = new_cluster.to_dict()
                    for topic_id in topic_ids:
                        topic = TopicRecord.from_dict(registry["topics"][topic_id])
                        topic.cluster_id = new_cluster_id
                        topic.revision += 1
                        topic.updated_at = utc_now()
                        registry["topics"][topic_id] = topic.to_dict()
                source.question_ids = [
                    item for item in source.question_ids if item not in assigned_questions
                ]
                source.topic_ids = [
                    item for item in source.topic_ids if item not in assigned_topics
                ]
                source.revision += 1
                source.updated_at = utc_now()
                registry["clusters"][source_id] = source.to_dict()

            else:
                raise ValueError(f"Unsupported proposal kind: {proposal.kind.value}")

            proposal.applied_at = utc_now()
            label_affecting = proposal.kind in {
                ProposalKind.RENAME_CATEGORY,
                ProposalKind.MERGE_CATEGORY,
                ProposalKind.SPLIT_CATEGORY,
                ProposalKind.LABEL_CHANGE,
                ProposalKind.REASSIGN_CATEGORY,
            }
            rollback_path = (
                self.site_dir(site)
                / "snapshots"
                / f"{proposal.proposal_id}.rollback.json"
            )
            rollback_payload = self._proposal_label_rollback_payload(
                proposal,
                categories,
                registry,
            )
            if rollback_path.exists():
                existing_rollback = self._read_json(rollback_path, {})
                existing_structural = {
                    key: value
                    for key, value in existing_rollback.items()
                    if key != "prepared_at"
                }
                candidate_structural = {
                    key: value
                    for key, value in rollback_payload.items()
                    if key != "prepared_at"
                }
                if existing_structural != candidate_structural:
                    raise ValueError(
                        "Immutable rollback payload already differs: "
                        f"{rollback_path}"
                    )
            else:
                self._atomic_write(rollback_path, rollback_payload)
            proposal.rollback_path = str(rollback_path)
            proposal.publication_sync_pending = bool(
                label_affecting
                and rollback_payload["affected_publications"]
            )
            proposal.status = (
                ProposalStatus.APPROVED
                if proposal.publication_sync_pending
                else ProposalStatus.APPLIED
            )
            proposal_document["proposals"][proposal_id] = proposal.to_dict()
            self._save_categories(site, categories)
            self._save_inbox(site, inbox)
            self._save_registry(site, registry)
            self._save_proposals(site, proposal_document)
        return proposal

    def rollback_monthly_proposal(self, site: str, proposal_id: str) -> MonthlyProposal:
        with self._lock(site):
            proposal_document = self._load_proposals(site)
            raw = proposal_document["proposals"].get(proposal_id)
            if not raw:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(raw)
            if proposal.status is ProposalStatus.ROLLED_BACK:
                return proposal
            if proposal.status is not ProposalStatus.APPLIED and not proposal.publication_sync_pending:
                raise ValueError("Only applied/pending-sync proposals may be rolled back")
            snapshot = proposal.label_snapshot
            if not snapshot:
                raise ValueError("Proposal has no rollback snapshot")
            if not proposal.rollback_path:
                raise ValueError("Proposal has no prepared rollback payload")
            rollback_payload = self._read_json(
                Path(proposal.rollback_path),
                {},
            )
            if (
                rollback_payload.get("proposal_id") != proposal.proposal_id
                or rollback_payload.get("snapshot_path") != proposal.snapshot_path
            ):
                raise ValueError("Prepared rollback payload does not match proposal")
            categories = deepcopy(snapshot.get("categories") or {})
            if not categories:
                raise ValueError("Proposal category snapshot is missing")
            registry = self._load_registry(site)
            registry["topics"] = deepcopy(snapshot.get("topics") or {})
            registry["clusters"] = deepcopy(snapshot.get("clusters") or {})
            registry["aliases"] = deepcopy(snapshot.get("aliases") or {})
            registry["cluster_aliases"] = deepcopy(
                snapshot.get("cluster_aliases") or {}
            )
            registry["publication_index"] = deepcopy(
                snapshot.get("publication_index") or {}
            )
            inbox = self._load_inbox(site)
            for question_id, topic_id in dict(
                snapshot.get("question_topic_links") or {}
            ).items():
                raw_question = inbox["questions"].get(question_id)
                if raw_question:
                    question = QuestionRecord.from_dict(raw_question)
                    question.topic_id = topic_id
                    inbox["questions"][question_id] = question.to_dict()
            proposal.status = ProposalStatus.ROLLED_BACK
            proposal.publication_sync_pending = False
            proposal.rolled_back_at = utc_now()
            rollback_audit_path = (
                self.site_dir(site)
                / "snapshots"
                / f"{proposal.proposal_id}.rollback.audit.json"
            )
            rollback_audit = {
                "proposal_id": proposal.proposal_id,
                "rollback_path": proposal.rollback_path,
                "snapshot_path": proposal.snapshot_path,
                "rolled_back_at": proposal.rolled_back_at,
                "affected_publication_count": len(
                    rollback_payload.get("affected_publications") or []
                ),
            }
            if not rollback_audit_path.exists():
                self._atomic_write(rollback_audit_path, rollback_audit)
            proposal.rollback_audit_path = str(rollback_audit_path)
            proposal_document["proposals"][proposal_id] = proposal.to_dict()
            self._save_categories(site, categories)
            self._save_inbox(site, inbox)
            self._save_registry(site, registry)
            self._save_proposals(site, proposal_document)
        return proposal

    def mark_proposal_publication_sync(
        self,
        site: str,
        proposal_id: str,
        *,
        success: bool,
        error: str = "",
    ) -> MonthlyProposal:
        with self._lock(site):
            document = self._load_proposals(site)
            raw = document["proposals"].get(proposal_id)
            if not raw:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(raw)
            if not proposal.publication_sync_pending:
                raise ValueError("Proposal has no pending publication-label sync")
            if success:
                proposal.publication_sync_pending = False
                proposal.publication_sync_error = ""
                proposal.status = ProposalStatus.APPLIED
            else:
                proposal.publication_sync_error = error or "external label sync failed"
                proposal.status = ProposalStatus.APPROVED
            document["proposals"][proposal_id] = proposal.to_dict()
            self._save_proposals(site, document)
        return proposal

    def prepare_proposal_label_sync_snapshot(
        self,
        site: str,
        proposal_id: str,
        posts: list[dict[str, Any]],
    ) -> MonthlyProposal:
        """Persist the exact pre-mutation Blogger labels once, immutably."""

        with self._lock(site):
            document = self._load_proposals(site)
            raw = document["proposals"].get(proposal_id)
            if not raw:
                raise ValueError(f"Unknown proposal: {proposal_id}")
            proposal = MonthlyProposal.from_dict(raw)
            if (
                proposal.status is not ProposalStatus.APPROVED
                or not proposal.publication_sync_pending
            ):
                raise ValueError(
                    "Approved pending-sync proposal is required before Blogger GET snapshot"
                )
            if (
                not proposal.snapshot_path
                or not Path(proposal.snapshot_path).exists()
                or not proposal.rollback_path
                or not Path(proposal.rollback_path).exists()
            ):
                raise ValueError(
                    "Proposal snapshot and prepared rollback payload must exist"
                )
            snapshot_path = (
                self.site_dir(site)
                / "snapshots"
                / f"{proposal.proposal_id}.blogger-labels.before.json"
            )
            payload = {
                "schema_version": 1,
                "proposal_id": proposal.proposal_id,
                "site": site,
                "captured_at": utc_now(),
                "posts": sorted(
                    [
                        {
                            "blogger_post_id": str(
                                post.get("blogger_post_id")
                                or post.get("id")
                                or ""
                            ),
                            "url": canonical_url(str(post.get("url") or "")),
                            "title": str(post.get("title") or ""),
                            "labels": [
                                str(label)
                                for label in post.get("labels", [])
                                if str(label)
                            ],
                        }
                        for post in posts
                    ],
                    key=lambda item: item["blogger_post_id"],
                ),
            }
            if not snapshot_path.exists():
                self._atomic_write(snapshot_path, payload)
            proposal.label_sync_snapshot_path = str(snapshot_path)
            document["proposals"][proposal_id] = proposal.to_dict()
            self._save_proposals(site, document)
        return proposal

    # ---- validation -----------------------------------------------------

    def validate_site(self, site: str) -> list[ValidationIssue]:
        registry = self._load_registry(site)
        inbox = self._load_inbox(site)
        categories = self._load_categories(site)
        self._load_proposals(site)
        issues = validate_documents(
            site=site,
            topics=[
                TopicRecord.from_dict(item)
                for item in registry["topics"].values()
            ],
            questions=[
                QuestionRecord.from_dict(item)
                for item in inbox["questions"].values()
            ],
            categories=[
                CategoryRecord.from_dict(item)
                for item in categories["categories"].values()
            ],
            clusters=[
                ClusterRecord.from_dict(item)
                for item in registry["clusters"].values()
            ],
            aliases=dict(registry.get("aliases") or {}),
            cluster_aliases=dict(registry.get("cluster_aliases") or {}),
            publication_index=dict(registry.get("publication_index") or {}),
            rollout=dict(registry.get("rollout") or {}),
        )
        runs_dir = self.site_dir(site) / "runs"
        if runs_dir.exists():
            for path in sorted(runs_dir.glob("*.json")):
                try:
                    bundle = self._read_json(path, {})
                    validate_weekly_bundle(bundle)
                    if bundle.get("site") != site:
                        raise ValueError(f"run site must be {site}")
                    if path.stem != bundle.get("run_id"):
                        raise ValueError("run filename must match run_id")
                except ValueError as exc:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "RUN_ARCHIVE_INVALID",
                            str(exc),
                            str(path),
                        )
                    )
        return issues

    def list_run_archives(self, site: str) -> list[dict[str, Any]]:
        runs_dir = self.site_dir(site) / "runs"
        if not runs_dir.exists():
            return []
        results = []
        for path in sorted(runs_dir.glob("*.json")):
            bundle = self._read_json(path, {})
            validate_weekly_bundle(bundle)
            results.append(bundle)
        return results

    # ---- publication-attempt audit leases ------------------------------

    @staticmethod
    def _audit_time(value: str = "") -> datetime:
        selected = datetime.fromisoformat((value or utc_now()).replace("Z", "+00:00"))
        if selected.tzinfo is None:
            selected = selected.replace(tzinfo=timezone.utc)
        return selected.astimezone(timezone.utc)

    @staticmethod
    def _same_publication(
        left: PublicationRef,
        right: PublicationRef,
    ) -> bool:
        if (
            left.blogger_post_id
            and right.blogger_post_id
            and left.blogger_post_id == right.blogger_post_id
        ):
            return True
        left_url = canonical_url(left.url)
        right_url = canonical_url(right.url)
        return bool(left_url and right_url and left_url == right_url)

    @staticmethod
    def _blocking_external_attempt(
        registry: dict[str, Any],
        topic_id: str,
    ) -> dict[str, Any] | None:
        attempt = (registry.get("publish_attempts") or {}).get(topic_id)
        if not isinstance(attempt, dict):
            return None
        if str(attempt.get("status") or "").upper() not in {
            "LEASED",
            "INSERTING",
            "UPDATE_STARTED",
            "UNKNOWN",
        }:
            return None
        return attempt

    @staticmethod
    def _assert_no_blocking_external_attempts(
        registry: dict[str, Any],
        topic_ids: list[str] | tuple[str, ...] | set[str],
        *,
        mutation: str,
    ) -> None:
        for topic_id in dict.fromkeys(str(item) for item in topic_ids if item):
            attempt = TopicStore._blocking_external_attempt(registry, topic_id)
            if attempt is None:
                continue
            raise ValueError(
                f"Cannot {mutation} topic {topic_id} while external attempt "
                f"{attempt.get('attempt_id') or 'unknown'} is "
                f"{attempt.get('status') or 'UNKNOWN'}; reconcile or expire it first"
            )

    def begin_publish_attempt(
        self,
        site: str,
        topic_id: str,
        *,
        run_id: str,
        expected_revision: int,
        lease_seconds: int = 1800,
        now: str = "",
    ) -> dict[str, Any]:
        if not run_id.strip():
            raise ValueError("run_id is required")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise ValueError("expected_revision must be a positive integer")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            attempts = registry.setdefault("publish_attempts", {})
            resolved_id = self._resolve_topic_id(registry, topic_id)
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if topic.action is not TopicAction.NEW_POST:
                raise ValueError("Only NEW_POST topics may acquire an insert attempt")
            if topic.status is not TopicStatus.GENERATED:
                raise ValueError(
                    f"Topic {resolved_id} is {topic.status.value}, not GENERATED"
                )
            if topic.claim_run_id != run_id:
                raise ValueError("Publish attempt does not own the active claim")
            if any(publication.primary for publication in topic.publications):
                raise ValueError("NEW_POST topic already owns a primary publication")

            attempt_id = stable_id(
                "attempt",
                site,
                resolved_id,
                run_id,
                expected_revision,
            )
            existing = attempts.get(resolved_id)
            if isinstance(existing, dict):
                if existing.get("attempt_id") == attempt_id:
                    return {**deepcopy(existing), "acquired": False}
                if existing.get("status") != "ABORTED_PRE_INSERT":
                    return {**deepcopy(existing), "acquired": False}

            from datetime import timedelta

            attempt = {
                "attempt_id": attempt_id,
                "site": site,
                "topic_id": resolved_id,
                "run_id": run_id,
                "topic_revision": expected_revision,
                "operation": "INSERT",
                "action": TopicAction.NEW_POST.value,
                "status": "LEASED",
                "started_at": selected_now.isoformat(),
                "expires_at": (
                    selected_now + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "insert_started_at": "",
                "receipt_recorded_at": "",
                "publication": {},
                "last_error": "",
                "prior_attempts": (
                    [
                        *list(existing.get("prior_attempts") or []),
                        deepcopy(existing),
                    ]
                    if isinstance(existing, dict)
                    else []
                ),
            }
            attempts[resolved_id] = attempt
            reservations = registry.setdefault("topic_reservations", {})
            reservation = dict(reservations.get(resolved_id) or {})
            reservation.update(
                {
                    "kind": str(reservation.get("kind") or "CLAIM"),
                    "topic_id": resolved_id,
                    "run_id": run_id,
                    "started_at": str(
                        reservation.get("started_at")
                        or selected_now.isoformat()
                    ),
                    "expires_at": attempt["expires_at"],
                    "status": "ACTIVE",
                    "publish_attempt_id": attempt_id,
                }
            )
            reservations[resolved_id] = reservation
            self._save_registry(site, registry)
        return {**deepcopy(attempt), "acquired": True}

    def mark_publish_insert_started(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        run_id: str,
        now: str = "",
    ) -> dict[str, Any]:
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = (registry.setdefault("publish_attempts", {})).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Publish attempt is missing or changed")
            if attempt.get("run_id") != run_id:
                raise ValueError("Publish attempt is owned by another run")
            if attempt.get("status") != "LEASED":
                raise ValueError(
                    f"Publish attempt is {attempt.get('status')}, not LEASED"
                )
            if self._audit_time(str(attempt.get("expires_at") or "")) <= selected_now:
                raise ValueError("Publish attempt lease expired before insert")
            attempt["status"] = "INSERTING"
            attempt["insert_started_at"] = selected_now.isoformat()
            attempt["updated_at"] = selected_now.isoformat()
            self._save_registry(site, registry)
            return deepcopy(attempt)

    def mark_publish_attempt_unknown(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        run_id: str,
        error: str = "",
        now: str = "",
    ) -> dict[str, Any]:
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Publish attempt is missing or changed")
            if run_id and attempt.get("run_id") != run_id:
                raise ValueError("Publish attempt is owned by another run")
            if attempt.get("status") == "RECEIPT_RECORDED":
                return deepcopy(attempt)
            attempt["status"] = "UNKNOWN"
            attempt["last_error"] = error
            attempt["updated_at"] = selected_now.isoformat()
            raw = registry["topics"].get(resolved_id)
            if raw:
                topic = TopicRecord.from_dict(raw)
                if topic.status not in {
                    TopicStatus.PUBLISHED,
                    TopicStatus.LIVE_UNVERIFIED,
                }:
                    topic.status = TopicStatus.HOLD
                    topic.status_reason = (
                        f"Blogger insert outcome unknown for {attempt_id}; "
                        "publication reconciliation required"
                    )
                    topic.claim_run_id = ""
                    topic.revision += 1
                    topic.updated_at = selected_now.isoformat()
                    registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
            return deepcopy(attempt)

    def record_publish_receipt(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        publication: PublicationRef | dict[str, Any],
        expected_revision: int,
        run_id: str,
        now: str = "",
    ) -> TopicRecord:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise ValueError("expected_revision must be a positive integer")
        if not publication.blogger_post_id and not canonical_url(publication.url):
            raise ValueError("Publication receipt requires Blogger post ID or URL")
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Publish attempt is missing or changed")
            if attempt.get("run_id") != run_id:
                raise ValueError("Publish receipt run_id does not own the attempt")
            if attempt.get("status") == "RECEIPT_RECORDED":
                prior = PublicationRef.from_dict(attempt.get("publication") or {})
                if not self._same_publication(prior, publication):
                    raise ValueError(
                        "Publish attempt already has a different Blogger receipt"
                    )
                raw = registry["topics"].get(resolved_id)
                if not raw:
                    raise ValueError(f"Unknown topic: {topic_id}")
                return TopicRecord.from_dict(raw)
            if attempt.get("status") not in {"INSERTING", "UNKNOWN"}:
                raise ValueError(
                    f"Publish attempt cannot accept a receipt in {attempt.get('status')}"
                )
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            reconciling_unknown = (
                attempt.get("status") == "UNKNOWN"
                and topic.status is TopicStatus.HOLD
                and int(attempt.get("topic_revision") or 0) == expected_revision
            )
            if not reconciling_unknown and topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if topic.action is not TopicAction.NEW_POST:
                raise ValueError("Publish receipt action is no longer NEW_POST")
            if not reconciling_unknown and topic.claim_run_id != run_id:
                raise ValueError("Publish receipt does not own the active claim")

            primary = [
                item for item in topic.publications if item.primary
            ]
            if primary and not any(
                self._same_publication(item, publication) for item in primary
            ):
                raise ValueError(
                    "NEW_POST topic already owns a different primary publication"
                )
            publication.primary = True
            for key in (
                publication_key(publication.blogger_post_id, ""),
                publication_key("", publication.url),
            ):
                if not key or key == "url:":
                    continue
                owner = registry["publication_index"].get(key)
                if owner and self._resolve_topic_id(registry, owner) != resolved_id:
                    raise ValueError(f"Publication {key} already belongs to {owner}")
                registry["publication_index"][key] = resolved_id

            merged_publications: list[PublicationRef] = []
            merged = False
            for existing_publication in topic.publications:
                if self._same_publication(existing_publication, publication):
                    merged_publications.append(
                        PublicationRef(
                            blogger_post_id=(
                                publication.blogger_post_id
                                or existing_publication.blogger_post_id
                            ),
                            url=publication.url or existing_publication.url,
                            title=publication.title or existing_publication.title,
                            status=publication.status or existing_publication.status,
                            published_at=(
                                publication.published_at
                                or existing_publication.published_at
                            ),
                            updated_at=(
                                publication.updated_at
                                or existing_publication.updated_at
                            ),
                            last_verified_at=(
                                publication.last_verified_at
                                or existing_publication.last_verified_at
                            ),
                            primary=True,
                        )
                    )
                    merged = True
                else:
                    merged_publications.append(existing_publication)
            if not merged:
                merged_publications.append(publication)
            topic.publications = merged_publications
            topic.status = (
                TopicStatus.PUBLISHED
                if publication.last_verified_at
                and publication.status.upper() in {"LIVE", "PUBLISHED"}
                else TopicStatus.LIVE_UNVERIFIED
            )
            topic.status_reason = (
                "verified Blogger publication"
                if topic.status is TopicStatus.PUBLISHED
                else "Blogger receipt recorded; public URL is not verified"
            )
            topic.claim_run_id = ""
            topic.revision += 1
            topic.updated_at = selected_now.isoformat()
            registry["topics"][resolved_id] = topic.to_dict()
            attempt["status"] = "RECEIPT_RECORDED"
            attempt["publication"] = publication.to_dict()
            attempt["receipt_recorded_at"] = selected_now.isoformat()
            attempt["updated_at"] = selected_now.isoformat()
            registry.setdefault("publication_receipts", {})[attempt_id] = {
                "attempt_id": attempt_id,
                "topic_id": resolved_id,
                "run_id": run_id,
                "topic_revision": expected_revision,
                "operation": "INSERT",
                "action": TopicAction.NEW_POST.value,
                "publication": publication.to_dict(),
                "status": "RECORDED",
                "recorded_at": selected_now.isoformat(),
                "last_error": "",
            }
            self._save_registry(site, registry)
        return topic

    def begin_update_attempt(
        self,
        site: str,
        topic_id: str,
        *,
        action: TopicAction | str,
        blogger_post_id: str,
        url: str,
        run_id: str,
        expected_revision: int,
        lease_seconds: int = 1800,
        now: str = "",
    ) -> dict[str, Any]:
        selected_action = (
            action
            if isinstance(action, TopicAction)
            else TopicAction(str(action).strip().upper())
        )
        if selected_action not in {
            TopicAction.UPDATE_EXISTING,
            TopicAction.FAQ_ADD,
        }:
            raise ValueError("Update attempts require UPDATE_EXISTING or FAQ_ADD")
        target_post_id = str(blogger_post_id or "").strip()
        target_url = canonical_url(url)
        if not target_post_id or not target_url:
            raise ValueError(
                "Update attempts require the existing Blogger post ID and canonical URL"
            )
        if not run_id.strip():
            raise ValueError("run_id is required")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise ValueError("expected_revision must be a positive integer")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if topic.action is not selected_action:
                raise ValueError(
                    f"Update action changed from {selected_action.value} "
                    f"to {topic.action.value}"
                )
            if topic.status is not TopicStatus.CLAIMED:
                raise ValueError(
                    f"Topic {resolved_id} is {topic.status.value}, not CLAIMED"
                )
            if topic.claim_run_id != run_id:
                raise ValueError("Update attempt does not own the active claim")

            target_publication = next(
                (
                    publication
                    for publication in topic.publications
                    if publication.blogger_post_id == target_post_id
                    and canonical_url(publication.url) == target_url
                ),
                None,
            )
            if target_publication is None:
                raise ValueError(
                    "Update target is not an exact publication owned by the topic"
                )
            if not target_publication.primary:
                raise ValueError("Update target must be the topic's primary publication")
            if target_publication.status.upper() not in {"LIVE", "PUBLISHED"}:
                raise ValueError("Update target must have LIVE or PUBLISHED status")
            for key in (
                publication_key(target_post_id, ""),
                publication_key("", target_url),
            ):
                owner = registry["publication_index"].get(key)
                if owner and self._resolve_topic_id(registry, owner) != resolved_id:
                    raise ValueError(f"Update target {key} belongs to {owner}")

            attempt_id = stable_id(
                "update-attempt",
                site,
                resolved_id,
                selected_action.value,
                target_post_id,
                target_url,
                run_id,
                expected_revision,
            )
            attempts = registry.setdefault("publish_attempts", {})
            existing = attempts.get(resolved_id)
            if isinstance(existing, dict):
                if existing.get("attempt_id") == attempt_id:
                    return {**deepcopy(existing), "acquired": False}
                if str(existing.get("status") or "") not in {
                    "ABORTED_PRE_INSERT",
                    "ABORTED_PRE_UPDATE",
                    "RECEIPT_RECORDED",
                }:
                    return {**deepcopy(existing), "acquired": False}

            archived_existing = (
                {
                    key: deepcopy(value)
                    for key, value in existing.items()
                    if key != "prior_attempts"
                }
                if isinstance(existing, dict)
                else None
            )
            if archived_existing is not None:
                archived_existing["prior_attempts"] = []
            prior_attempts = (
                [
                    *list(existing.get("prior_attempts") or []),
                    archived_existing,
                ]
                if isinstance(existing, dict) and archived_existing is not None
                else []
            )
            attempt = {
                "attempt_id": attempt_id,
                "site": site,
                "topic_id": resolved_id,
                "run_id": run_id,
                "topic_revision": expected_revision,
                "operation": "UPDATE",
                "action": selected_action.value,
                "target_blogger_post_id": target_post_id,
                "target_url": target_url,
                "target_primary": bool(target_publication.primary),
                "status": "LEASED",
                "started_at": selected_now.isoformat(),
                "expires_at": (
                    selected_now + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "update_started_at": "",
                "receipt_recorded_at": "",
                "publication": {},
                "last_error": "",
                "prior_attempts": prior_attempts,
            }
            attempts[resolved_id] = attempt
            reservations = registry.setdefault("topic_reservations", {})
            reservation = dict(reservations.get(resolved_id) or {})
            reservation.update(
                {
                    "kind": "UPDATE",
                    "topic_id": resolved_id,
                    "run_id": run_id,
                    "started_at": selected_now.isoformat(),
                    "expires_at": attempt["expires_at"],
                    "status": "ACTIVE",
                    "update_attempt_id": attempt_id,
                    "target_blogger_post_id": target_post_id,
                    "target_url": target_url,
                }
            )
            reservations[resolved_id] = reservation
            self._save_registry(site, registry)
        return {**deepcopy(attempt), "acquired": True}

    def mark_update_started(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        run_id: str,
        now: str = "",
    ) -> dict[str, Any]:
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Update attempt is missing or changed")
            if attempt.get("operation") != "UPDATE":
                raise ValueError("External attempt is not a maintenance update")
            if attempt.get("run_id") != run_id:
                raise ValueError("Update attempt is owned by another run")
            if attempt.get("status") == "UPDATE_STARTED":
                return {**deepcopy(attempt), "started": False}
            if attempt.get("status") != "LEASED":
                raise ValueError(
                    f"Update attempt is {attempt.get('status')}, not LEASED"
                )
            if self._audit_time(str(attempt.get("expires_at") or "")) <= selected_now:
                raise ValueError("Update attempt lease expired before Blogger update")

            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if (
                topic.status is not TopicStatus.CLAIMED
                or topic.claim_run_id != run_id
                or topic.revision != int(attempt.get("topic_revision") or 0)
                or topic.action.value != str(attempt.get("action") or "")
            ):
                raise ValueError("Update attempt lost topic ownership or revision")

            attempt["status"] = "UPDATE_STARTED"
            attempt["update_started_at"] = selected_now.isoformat()
            attempt["updated_at"] = selected_now.isoformat()
            reservation = dict(
                registry.setdefault("topic_reservations", {}).get(resolved_id) or {}
            )
            reservation["status"] = "UPDATE_STARTED"
            reservation["updated_at"] = selected_now.isoformat()
            registry["topic_reservations"][resolved_id] = reservation
            self._save_registry(site, registry)
            return {**deepcopy(attempt), "started": True}

    def mark_update_unknown(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        run_id: str,
        error: str = "",
        now: str = "",
    ) -> dict[str, Any]:
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Update attempt is missing or changed")
            if attempt.get("operation") != "UPDATE":
                raise ValueError("External attempt is not a maintenance update")
            if attempt.get("run_id") != run_id:
                raise ValueError("Update attempt is owned by another run")
            if attempt.get("status") == "RECEIPT_RECORDED":
                return deepcopy(attempt)
            if attempt.get("status") == "UNKNOWN":
                return deepcopy(attempt)
            if attempt.get("status") != "UPDATE_STARTED":
                raise ValueError(
                    "Only an UPDATE_STARTED attempt may become outcome-unknown"
                )

            attempt["status"] = "UNKNOWN"
            attempt["last_error"] = error
            attempt["updated_at"] = selected_now.isoformat()
            raw = registry["topics"].get(resolved_id)
            if raw:
                topic = TopicRecord.from_dict(raw)
                topic.status = TopicStatus.HOLD
                topic.status_reason = (
                    f"Blogger update outcome unknown for {attempt_id}; "
                    "publication reconciliation required"
                )
                topic.claim_run_id = ""
                topic.revision += 1
                topic.updated_at = selected_now.isoformat()
                registry["topics"][resolved_id] = topic.to_dict()
            reservation = dict(
                registry.setdefault("topic_reservations", {}).get(resolved_id) or {}
            )
            reservation.update(
                {
                    "status": "UNKNOWN",
                    "outcome": "HOLD_RECONCILE",
                    "updated_at": selected_now.isoformat(),
                }
            )
            registry["topic_reservations"][resolved_id] = reservation
            self._save_registry(site, registry)
            return deepcopy(attempt)

    def record_update_receipt(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        publication: PublicationRef | dict[str, Any],
        expected_revision: int,
        run_id: str,
        now: str = "",
    ) -> TopicRecord:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise ValueError("expected_revision must be a positive integer")
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Update attempt is missing or changed")
            if attempt.get("operation") != "UPDATE":
                raise ValueError("External attempt is not a maintenance update")
            if attempt.get("run_id") != run_id:
                raise ValueError("Update receipt run_id does not own the attempt")
            target_post_id = str(attempt.get("target_blogger_post_id") or "")
            target_url = canonical_url(str(attempt.get("target_url") or ""))
            if (
                publication.blogger_post_id != target_post_id
                or canonical_url(publication.url) != target_url
            ):
                raise ValueError(
                    "Blogger update receipt does not match the reserved target ID/URL"
                )
            if attempt.get("status") == "RECEIPT_RECORDED":
                prior = PublicationRef.from_dict(attempt.get("publication") or {})
                if (
                    prior.blogger_post_id != publication.blogger_post_id
                    or canonical_url(prior.url) != canonical_url(publication.url)
                ):
                    raise ValueError(
                        "Update attempt already has a different Blogger receipt"
                    )
                raw = registry["topics"].get(resolved_id)
                if not raw:
                    raise ValueError(f"Unknown topic: {topic_id}")
                return TopicRecord.from_dict(raw)
            if attempt.get("status") not in {"UPDATE_STARTED", "UNKNOWN"}:
                raise ValueError(
                    f"Update attempt cannot accept a receipt in {attempt.get('status')}"
                )

            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            reconciling_unknown = (
                attempt.get("status") == "UNKNOWN"
                and topic.status is TopicStatus.HOLD
                and int(attempt.get("topic_revision") or 0) == expected_revision
            )
            if not reconciling_unknown and topic.revision != expected_revision:
                raise ValueError(
                    f"Revision conflict for {resolved_id}: "
                    f"expected {expected_revision}, found {topic.revision}"
                )
            if topic.action.value != str(attempt.get("action") or ""):
                raise ValueError("Update receipt action no longer matches the topic")
            if not reconciling_unknown and topic.claim_run_id != run_id:
                raise ValueError("Update receipt does not own the active claim")

            target_publication = next(
                (
                    item
                    for item in topic.publications
                    if item.blogger_post_id == target_post_id
                    and canonical_url(item.url) == target_url
                ),
                None,
            )
            if target_publication is None:
                raise ValueError("Reserved update target is no longer owned by the topic")
            publication.primary = bool(target_publication.primary)
            publication.title = publication.title or target_publication.title
            publication.published_at = (
                publication.published_at or target_publication.published_at
            )
            for key in (
                publication_key(target_post_id, ""),
                publication_key("", target_url),
            ):
                owner = registry["publication_index"].get(key)
                if owner and self._resolve_topic_id(registry, owner) != resolved_id:
                    raise ValueError(f"Update target {key} belongs to {owner}")
                registry["publication_index"][key] = resolved_id

            topic.publications = self._merge_publication_lists(
                topic.publications,
                [publication],
            )
            topic.status = (
                TopicStatus.PUBLISHED
                if publication.last_verified_at
                and publication.status.upper() in {"LIVE", "PUBLISHED"}
                else TopicStatus.LIVE_UNVERIFIED
            )
            topic.status_reason = (
                "verified Blogger maintenance update"
                if topic.status is TopicStatus.PUBLISHED
                else "Blogger maintenance receipt recorded; public URL is not verified"
            )
            topic.claim_run_id = ""
            topic.revision += 1
            topic.updated_at = selected_now.isoformat()
            registry["topics"][resolved_id] = topic.to_dict()

            attempt["status"] = "RECEIPT_RECORDED"
            attempt["publication"] = publication.to_dict()
            attempt["receipt_recorded_at"] = selected_now.isoformat()
            attempt["updated_at"] = selected_now.isoformat()
            pending_receipt = dict(
                registry.setdefault("publication_receipts", {}).get(attempt_id) or {}
            )
            recorded_receipt = {
                "attempt_id": attempt_id,
                "topic_id": resolved_id,
                "run_id": run_id,
                "topic_revision": expected_revision,
                "operation": "UPDATE",
                "action": str(attempt.get("action") or ""),
                "target_blogger_post_id": target_post_id,
                "target_url": target_url,
                "publication": publication.to_dict(),
                "status": "RECORDED",
                "recorded_at": selected_now.isoformat(),
                "last_error": "",
            }
            if pending_receipt.get("outbox_id"):
                recorded_receipt["outbox_id"] = str(
                    pending_receipt.get("outbox_id") or ""
                )
            registry["publication_receipts"][attempt_id] = recorded_receipt
            for entry in registry.setdefault("publication_outbox", []):
                if (
                    entry.get("update_attempt_id") != attempt_id
                    and entry.get("attempt_id") != attempt_id
                ):
                    continue
                stages = dict(entry.get("stages") or {})
                stages["blogger"] = "SUCCESS"
                stages["registry"] = "SUCCESS"
                entry["stages"] = stages
                entry["last_error"] = ""
                entry["updated_at"] = selected_now.isoformat()
            reservation = dict(
                registry.setdefault("topic_reservations", {}).get(resolved_id) or {}
            )
            reservation.update(
                {
                    "status": "COMPLETED",
                    "outcome": "RECEIPT_RECORDED",
                    "completed_at": selected_now.isoformat(),
                }
            )
            registry["topic_reservations"][resolved_id] = reservation
            self._save_registry(site, registry)
        return topic

    def enqueue_update_receipt(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        publication: PublicationRef | dict[str, Any],
        run_id: str,
        error: str = "",
        now: str = "",
    ) -> dict[str, Any]:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        if not run_id.strip():
            raise ValueError("run_id is required")
        selected_now = self._audit_time(now)
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Update attempt is missing or changed")
            if attempt.get("operation") != "UPDATE":
                raise ValueError("External attempt is not a maintenance update")
            if attempt.get("run_id") != run_id:
                raise ValueError("Update receipt run_id does not own the attempt")
            target_post_id = str(attempt.get("target_blogger_post_id") or "")
            target_url = canonical_url(str(attempt.get("target_url") or ""))
            if (
                publication.blogger_post_id != target_post_id
                or canonical_url(publication.url) != target_url
            ):
                raise ValueError(
                    "Blogger update receipt does not match the reserved target ID/URL"
                )
            if attempt.get("status") == "RECEIPT_RECORDED":
                prior = PublicationRef.from_dict(attempt.get("publication") or {})
                if (
                    prior.blogger_post_id != publication.blogger_post_id
                    or canonical_url(prior.url) != canonical_url(publication.url)
                ):
                    raise ValueError(
                        "Update attempt already has a different Blogger receipt"
                    )
                existing_recorded = next(
                    (
                        item
                        for item in registry.setdefault("publication_outbox", [])
                        if (
                            item.get("update_attempt_id") == attempt_id
                            or item.get("attempt_id") == attempt_id
                        )
                    ),
                    None,
                )
                if existing_recorded is not None:
                    return deepcopy(existing_recorded)
                raise ValueError("Update receipt is already recorded in Registry")
            if attempt.get("status") not in {"UPDATE_STARTED", "UNKNOWN"}:
                raise ValueError(
                    f"Update attempt cannot enqueue a receipt in {attempt.get('status')}"
                )

            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if topic.action.value != str(attempt.get("action") or ""):
                raise ValueError("Update receipt action no longer matches the topic")
            target_publication = next(
                (
                    item
                    for item in topic.publications
                    if item.blogger_post_id == target_post_id
                    and canonical_url(item.url) == target_url
                ),
                None,
            )
            if target_publication is None:
                raise ValueError("Reserved update target is no longer owned by the topic")

            publication.primary = bool(target_publication.primary)
            publication.title = publication.title or target_publication.title
            publication.published_at = (
                publication.published_at or target_publication.published_at
            )
            key = publication_key(target_post_id, target_url)
            outbox_id = stable_id(
                "update-receipt",
                site,
                resolved_id,
                attempt_id,
                target_post_id,
                target_url,
            )
            outbox = registry.setdefault("publication_outbox", [])
            existing = next(
                (
                    item
                    for item in outbox
                    if item.get("outbox_id") == outbox_id
                ),
                None,
            )
            entry = {
                "outbox_id": outbox_id,
                "site": site,
                "topic_id": resolved_id,
                "attempt_id": attempt_id,
                "update_attempt_id": attempt_id,
                "publication_key": key,
                "publication": publication.to_dict(),
                "status": "PENDING",
                "attempts": int((existing or {}).get("attempts") or 0) + 1,
                "last_error": error,
                "stages": {
                    "blogger": "SUCCESS",
                    "registry": "PENDING",
                    "sheet": "PENDING",
                },
                "next_retry_at": "",
                "created_at": (
                    (existing or {}).get("created_at")
                    or selected_now.isoformat()
                ),
                "updated_at": selected_now.isoformat(),
            }
            registry["publication_outbox"] = [
                item
                for item in outbox
                if item.get("outbox_id") != outbox_id
            ]
            registry["publication_outbox"].append(entry)

            attempt["status"] = "UNKNOWN"
            attempt["publication"] = publication.to_dict()
            attempt["last_error"] = error
            attempt["outbox_id"] = outbox_id
            attempt["updated_at"] = selected_now.isoformat()
            registry.setdefault("publication_receipts", {})[attempt_id] = {
                "attempt_id": attempt_id,
                "topic_id": resolved_id,
                "run_id": run_id,
                "topic_revision": int(attempt.get("topic_revision") or 0),
                "operation": "UPDATE",
                "action": str(attempt.get("action") or ""),
                "target_blogger_post_id": target_post_id,
                "target_url": target_url,
                "publication": publication.to_dict(),
                "status": "PENDING",
                "recorded_at": selected_now.isoformat(),
                "last_error": error,
                "outbox_id": outbox_id,
            }

            topic_changed = (
                topic.status is not TopicStatus.HOLD
                or bool(topic.claim_run_id)
                or "pending Registry reconciliation" not in topic.status_reason
            )
            topic.status = TopicStatus.HOLD
            topic.status_reason = (
                f"Blogger update receipt for {attempt_id} is pending "
                "Registry reconciliation"
            )
            topic.claim_run_id = ""
            if topic_changed:
                topic.revision += 1
            topic.updated_at = selected_now.isoformat()
            registry["topics"][resolved_id] = topic.to_dict()
            reservation = dict(
                registry.setdefault("topic_reservations", {}).get(resolved_id) or {}
            )
            reservation.update(
                {
                    "status": "UNKNOWN",
                    "outcome": "HOLD_RECONCILE",
                    "outbox_id": outbox_id,
                    "updated_at": selected_now.isoformat(),
                }
            )
            registry["topic_reservations"][resolved_id] = reservation
            self._save_registry(site, registry)
            return deepcopy(entry)

    def enqueue_publish_receipt(
        self,
        site: str,
        topic_id: str,
        *,
        attempt_id: str,
        publication: PublicationRef | dict[str, Any],
        error: str = "",
    ) -> dict[str, Any]:
        if isinstance(publication, dict):
            publication = PublicationRef.from_dict(publication)
        key = publication_key(publication.blogger_post_id, publication.url)
        if not key or key == "url:":
            raise ValueError("Publication receipt requires Blogger post ID or URL")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            attempt = registry.setdefault("publish_attempts", {}).get(resolved_id)
            if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                raise ValueError("Publish attempt is missing or changed")
            outbox_id = stable_id(
                "pubreceipt",
                site,
                resolved_id,
                attempt_id,
                key,
            )
            existing = next(
                (
                    item
                    for item in registry["publication_outbox"]
                    if item.get("outbox_id") == outbox_id
                ),
                None,
            )
            entry = {
                "outbox_id": outbox_id,
                "site": site,
                "topic_id": resolved_id,
                "attempt_id": attempt_id,
                "publication_key": key,
                "publication": publication.to_dict(),
                "status": "PENDING",
                "attempts": int((existing or {}).get("attempts") or 0) + 1,
                "last_error": error,
                "stages": {
                    "blogger": "SUCCESS",
                    "registry": "PENDING",
                    "sheet": "PENDING",
                },
                "next_retry_at": "",
                "created_at": (existing or {}).get("created_at") or utc_now(),
                "updated_at": utc_now(),
            }
            registry["publication_outbox"] = [
                item
                for item in registry["publication_outbox"]
                if item.get("outbox_id") != outbox_id
            ]
            registry["publication_outbox"].append(entry)
            attempt["status"] = "UNKNOWN"
            attempt["publication"] = publication.to_dict()
            attempt["last_error"] = error
            attempt["updated_at"] = utc_now()
            registry.setdefault("publication_receipts", {})[attempt_id] = {
                "attempt_id": attempt_id,
                "topic_id": resolved_id,
                "run_id": str(attempt.get("run_id") or ""),
                "topic_revision": int(attempt.get("topic_revision") or 0),
                "operation": "INSERT",
                "action": TopicAction.NEW_POST.value,
                "publication": publication.to_dict(),
                "status": "PENDING",
                "recorded_at": utc_now(),
                "last_error": error,
                "outbox_id": outbox_id,
            }
            raw = registry["topics"].get(resolved_id)
            if raw:
                topic = TopicRecord.from_dict(raw)
                if topic.status not in {
                    TopicStatus.PUBLISHED,
                    TopicStatus.LIVE_UNVERIFIED,
                }:
                    topic.status = TopicStatus.HOLD
                    topic.status_reason = (
                        f"Blogger receipt for {attempt_id} is pending Registry reconciliation"
                    )
                    topic.claim_run_id = ""
                    topic.revision += 1
                    topic.updated_at = utc_now()
                    registry["topics"][resolved_id] = topic.to_dict()
            self._save_registry(site, registry)
            return deepcopy(entry)

    def publication_owner(
        self,
        site: str,
        *,
        blogger_post_id: str = "",
        url: str = "",
    ) -> str:
        registry = self._load_registry(site)
        candidates: set[str] = set()
        for key in (
            publication_key(blogger_post_id, ""),
            publication_key("", url),
        ):
            if not key or key == "url:":
                continue
            owner = registry["publication_index"].get(key)
            if owner:
                candidates.add(self._resolve_topic_id(registry, owner))
        for topic_id, raw in registry["topics"].items():
            topic = TopicRecord.from_dict(raw)
            if any(
                (
                    blogger_post_id
                    and item.blogger_post_id == blogger_post_id
                )
                or (
                    canonical_url(url)
                    and canonical_url(item.url) == canonical_url(url)
                )
                for item in topic.publications
            ):
                candidates.add(self._resolve_topic_id(registry, topic_id))
        if len(candidates) > 1:
            raise ValueError("Publication ID/URL resolve to different topics")
        return next(iter(candidates), "")

    def record_schedule_reservation(
        self,
        site: str,
        topic_id: str,
        *,
        expected_revision: int,
        scheduled_for: str,
        expires_at: str,
        now: str = "",
    ) -> dict[str, Any]:
        selected_now = self._audit_time(now)
        expiry = self._audit_time(expires_at)
        if expiry <= selected_now:
            raise ValueError("Schedule reservation expiry must be in the future")
        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if topic.status is not TopicStatus.SCHEDULED:
                raise ValueError("Schedule reservation requires SCHEDULED status")
            if topic.revision != int(expected_revision):
                raise ValueError("Schedule reservation revision conflict")
            reservation = {
                "kind": "SCHEDULE",
                "topic_id": resolved_id,
                "started_at": selected_now.isoformat(),
                "expires_at": expiry.isoformat(),
                "scheduled_for": scheduled_for,
                "run_id": "",
                "status": "ACTIVE",
            }
            registry.setdefault("topic_reservations", {})[resolved_id] = reservation
            self._save_registry(site, registry)
            return deepcopy(reservation)

    def record_claim_reservation(
        self,
        site: str,
        topic_id: str,
        *,
        run_id: str,
        expected_revision: int,
        lease_seconds: int = 7200,
        now: str = "",
    ) -> dict[str, Any]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        selected_now = self._audit_time(now)
        from datetime import timedelta

        with self._lock(site):
            registry = self._load_registry(site)
            resolved_id = self._resolve_topic_id(registry, topic_id)
            raw = registry["topics"].get(resolved_id)
            if not raw:
                raise ValueError(f"Unknown topic: {topic_id}")
            topic = TopicRecord.from_dict(raw)
            if (
                topic.status is not TopicStatus.CLAIMED
                or topic.claim_run_id != run_id
                or topic.revision != int(expected_revision)
            ):
                raise ValueError("Claim reservation ownership/revision conflict")
            reservation = {
                "kind": "CLAIM",
                "topic_id": resolved_id,
                "run_id": run_id,
                "started_at": selected_now.isoformat(),
                "expires_at": (
                    selected_now + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "status": "ACTIVE",
            }
            registry.setdefault("topic_reservations", {})[resolved_id] = reservation
            self._save_registry(site, registry)
            return deepcopy(reservation)

    def sweep_expired_reservations(
        self,
        site: str,
        *,
        now: str = "",
        legacy_schedule_hours: float = 8 * 24,
        legacy_claim_hours: float = 2,
    ) -> list[dict[str, Any]]:
        selected_now = self._audit_time(now)
        swept: list[dict[str, Any]] = []
        with self._lock(site):
            registry = self._load_registry(site)
            reservations = registry.setdefault("topic_reservations", {})
            attempts = registry.setdefault("publish_attempts", {})
            changed = False
            for topic_id, raw in list(registry["topics"].items()):
                topic = TopicRecord.from_dict(raw)
                if topic.status not in {
                    TopicStatus.SCHEDULED,
                    TopicStatus.CLAIMED,
                    TopicStatus.GENERATED,
                }:
                    continue
                reservation = dict(reservations.get(topic_id) or {})
                attempt = attempts.get(topic_id)
                attempt_status = (
                    str(attempt.get("status") or "").upper()
                    if isinstance(attempt, dict)
                    else ""
                )
                attempt_expiry = (
                    str(attempt.get("expires_at") or "")
                    if isinstance(attempt, dict)
                    and attempt_status
                    in {"LEASED", "INSERTING", "UPDATE_STARTED"}
                    else ""
                )
                expires_at = attempt_expiry or str(
                    reservation.get("expires_at") or ""
                )
                expired = False
                if expires_at:
                    try:
                        expired = self._audit_time(expires_at) <= selected_now
                    except ValueError:
                        expired = True
                else:
                    try:
                        updated = self._audit_time(topic.updated_at)
                    except ValueError:
                        updated = datetime.min.replace(tzinfo=timezone.utc)
                    age_hours = (selected_now - updated).total_seconds() / 3600
                    threshold = (
                        legacy_schedule_hours
                        if topic.status is TopicStatus.SCHEDULED
                        else legacy_claim_hours
                    )
                    expired = age_hours > threshold
                if not expired:
                    continue

                operation = (
                    str(attempt.get("operation") or "").upper()
                    if isinstance(attempt, dict)
                    else ""
                )
                if not operation and isinstance(attempt, dict):
                    operation = (
                        "UPDATE"
                        if str(attempt.get("action") or "").upper()
                        in {
                            TopicAction.UPDATE_EXISTING.value,
                            TopicAction.FAQ_ADD.value,
                        }
                        else "INSERT"
                    )
                external_mutation_trace = isinstance(attempt, dict) and bool(
                    attempt.get("insert_started_at")
                    or attempt.get("update_started_at")
                    or attempt_status
                    in {
                        "INSERTING",
                        "UPDATE_STARTED",
                        "UNKNOWN",
                        "RECEIPT_RECORDED",
                    }
                )
                if external_mutation_trace:
                    if topic.status not in {
                        TopicStatus.PUBLISHED,
                        TopicStatus.LIVE_UNVERIFIED,
                    }:
                        topic.status = TopicStatus.HOLD
                        topic.status_reason = (
                            "Expired claim has a Blogger mutation trace; "
                            "publication reconciliation required"
                        )
                    if attempt_status in {"INSERTING", "UPDATE_STARTED"}:
                        attempt["status"] = "UNKNOWN"
                        attempt["last_error"] = (
                            f"{operation.lower()} lease expired without receipt"
                        )
                        attempt["updated_at"] = selected_now.isoformat()
                    outcome = "HOLD_RECONCILE"
                else:
                    topic.status = TopicStatus.READY
                    topic.status_reason = (
                        "Expired pre-mutation reservation returned to READY"
                    )
                    if isinstance(attempt, dict) and attempt_status == "LEASED":
                        attempt["status"] = (
                            "ABORTED_PRE_UPDATE"
                            if operation == "UPDATE"
                            else "ABORTED_PRE_INSERT"
                        )
                        attempt["last_error"] = (
                            f"pre-{operation.lower()} lease expired"
                        )
                        attempt["updated_at"] = selected_now.isoformat()
                    outcome = "READY"
                topic.claim_run_id = ""
                topic.revision += 1
                topic.updated_at = selected_now.isoformat()
                registry["topics"][topic_id] = topic.to_dict()
                reservation["status"] = "EXPIRED"
                reservation["expired_at"] = selected_now.isoformat()
                reservation["outcome"] = outcome
                reservations[topic_id] = reservation
                swept.append(
                    {
                        "topic_id": topic_id,
                        "outcome": outcome,
                        "attempt_id": (
                            str(attempt.get("attempt_id") or "")
                            if isinstance(attempt, dict)
                            else ""
                        ),
                    }
                )
                changed = True
            if changed:
                self._save_registry(site, registry)
        return swept
