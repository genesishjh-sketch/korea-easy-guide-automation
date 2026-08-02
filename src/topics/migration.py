from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from src.content.topic_scoring import infer_category
from src.sites import get_site_profile
from src.topics.defaults import default_categories
from src.topics.ids import canonical_url
from src.topics.ids import normalize_text
from src.topics.ids import stable_id
from src.topics.models import EvidenceType
from src.topics.models import ClusterRecord
from src.topics.models import PublicationRef
from src.topics.models import QuestionRecord
from src.topics.models import TopicAction
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.models import utc_now
from src.topics.schema import validate_weekly_bundle
from src.topics.store import TopicStore
from src.topics.validation import evidence_gate


DATE_DIRECTORY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOPIC_MARKER_PATTERNS = (
    re.compile(r"""data-topic-id=["']([A-Za-z0-9._-]+)["']""", re.IGNORECASE),
    re.compile(r"""<!--\s*topic[_-]id\s*:\s*([A-Za-z0-9._-]+)\s*-->""", re.IGNORECASE),
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc


def _category_for_text(store: TopicStore, site: str, text: str) -> str:
    profile = get_site_profile(site)
    name = infer_category(text, profile.content_domain)
    category = store.find_category(site, name)
    if category is None:
        raise ValueError(f"Default category is missing for {site}: {name}")
    return category.category_id


def _site_metadata_paths(site: str, generated_root: Path) -> list[Path]:
    paths: list[Path] = []
    site_root = generated_root / site
    if site_root.exists():
        paths.extend(site_root.rglob("metadata.json"))
    if site == "korea_easy_guide" and generated_root.exists():
        for child in generated_root.iterdir():
            if child.is_dir() and DATE_DIRECTORY.match(child.name):
                paths.extend(child.rglob("metadata.json"))
    return sorted(set(paths))


def _metadata_identity(metadata: dict[str, Any], fallback: str) -> tuple[str, str, str]:
    article = metadata.get("article") if isinstance(metadata.get("article"), dict) else {}
    candidate = (
        metadata.get("candidate")
        if isinstance(metadata.get("candidate"), dict)
        else {}
    )
    keyword = str(candidate.get("keyword") or "").strip()
    title = str(article.get("title") or keyword or fallback).strip()
    category = str(article.get("category") or candidate.get("category") or "").strip()
    return keyword or title, title, category


def _publication_from_directory(
    directory: Path,
    title: str,
) -> PublicationRef | None:
    # A publish result is the authoritative local mapping. Update/refresh files
    # may describe the same post but do not prove that its public URL is live.
    path = directory / "blogger_publish_result.json"
    if not path.exists():
        return None
    data = _read_json(path)
    blogger = data.get("blogger") if isinstance(data, dict) else None
    if not isinstance(blogger, dict):
        return None
    publication = PublicationRef.from_dict(
        {
            **blogger,
            "title": title,
            "last_verified_at": "",
        }
    )
    if not publication.blogger_post_id and not publication.url:
        return None
    return publication


def _migration_publication_rank(
    path: Path,
    publication: PublicationRef,
) -> tuple[int, int, int, int, str]:
    """Rank duplicate local receipts without treating a bare post ID as proof.

    A few legacy generation directories contain a copied
    ``blogger_publish_result.json`` with only an ``id``.  A receipt carrying
    the public URL and Blogger timestamps is stronger evidence of ownership.
    The path is the final stable tie-breaker so a fresh backfill is
    deterministic regardless of filesystem iteration order.
    """

    return (
        -int(bool(canonical_url(publication.url))),
        -int(bool(publication.published_at)),
        -int(bool(publication.updated_at)),
        -int(bool(publication.status)),
        str(path),
    )


def _duplicate_publication_owners(
    artifacts: list[dict[str, Any]],
) -> dict[Path, Path]:
    """Return secondary-artifact -> authoritative-artifact mappings.

    This arbitration is intentionally scoped to the initial local-history
    migration.  Runtime publication reconciliation still fails closed on
    cross-topic publication ownership conflicts.
    """

    by_post_id: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        publication = artifact.get("publication")
        if not isinstance(publication, PublicationRef):
            continue
        if publication.blogger_post_id:
            by_post_id.setdefault(publication.blogger_post_id, []).append(artifact)

    secondary_to_owner: dict[Path, Path] = {}
    for candidates in by_post_id.values():
        if len(candidates) < 2:
            continue
        owner = min(
            candidates,
            key=lambda item: _migration_publication_rank(
                item["path"],
                item["publication"],
            ),
        )
        for candidate in candidates:
            if candidate["path"] != owner["path"]:
                secondary_to_owner[candidate["path"]] = owner["path"]
    return secondary_to_owner


def _normalize_migration_primary_publications(
    store: TopicStore,
    site: str,
) -> list[dict[str, Any]]:
    """Keep exactly one deterministic primary for legacy NEW_POST history."""

    resolutions: list[dict[str, Any]] = []
    for topic in store.list_topics(site):
        if topic.action is not TopicAction.NEW_POST or not topic.publications:
            continue
        selected = max(
            topic.publications,
            key=lambda item: (
                item.last_verified_at,
                item.updated_at,
                item.published_at,
                item.blogger_post_id,
                canonical_url(item.url),
            ),
        )
        selected_key = (
            selected.blogger_post_id,
            canonical_url(selected.url),
        )
        updated = TopicRecord.from_dict(topic.to_dict())
        changed = False
        for publication in updated.publications:
            should_be_primary = (
                publication.blogger_post_id,
                canonical_url(publication.url),
            ) == selected_key
            if publication.primary != should_be_primary:
                publication.primary = should_be_primary
                changed = True
        if not changed:
            continue
        saved = store.upsert_topic(
            site,
            updated,
            expected_revision=topic.revision,
        )
        resolutions.append(
            {
                "topic_id": saved.topic_id,
                "primary_post_id": selected.blogger_post_id,
                "publication_count": len(saved.publications),
            }
        )
    return resolutions


def backfill_local_history(
    store: TopicStore,
    site: str,
    *,
    generated_root: str | Path | None = None,
) -> dict[str, Any]:
    """Idempotently seed the registry from committed seeds and local artifacts."""

    profile = get_site_profile(site)
    store.ensure_site(site, default_categories(site))
    before_topics = {topic.topic_id: topic.to_dict() for topic in store.list_topics(site)}
    before_publications = sum(
        len(topic.publications) for topic in store.list_topics(site)
    )
    report: dict[str, Any] = {
        "site": site,
        "seed_count": 0,
        "metadata_count": 0,
        "created_topics": 0,
        "updated_topics": 0,
        "publication_links_added": 0,
        "legacy_signals_skipped": 0,
        "duplicate_publication_resolutions": [],
        "primary_publication_resolutions": [],
        "conflicts": [],
    }

    seeds = _read_json(profile.seed_file)
    if not isinstance(seeds, list):
        raise ValueError(f"Seed file must contain a list: {profile.seed_file}")
    report["seed_count"] = len(seeds)
    for raw_seed in seeds:
        seed = str(raw_seed).strip()
        if not seed:
            continue
        existing = store.find_topic_by_text(site, seed)
        if existing is None:
            store.create_topic(
                site,
                seed,
                _category_for_text(store, site, seed),
                identity_key=f"seed:{normalize_text(seed)}",
                aliases=[seed],
                canonical_intent="legacy-seed",
                status=TopicStatus.DISCOVERED,
            )

    selected_generated_root = (
        Path(generated_root)
        if generated_root is not None
        else profile.output_dir.parent
    )
    artifacts: list[dict[str, Any]] = []
    for metadata_path in _site_metadata_paths(site, selected_generated_root):
        metadata = _read_json(metadata_path)
        if not isinstance(metadata, dict):
            continue
        report["metadata_count"] += 1
        identity, title, category_name = _metadata_identity(
            metadata,
            metadata_path.parent.name.replace("-", " "),
        )
        signals = (
            metadata.get("candidate", {}).get("signals", [])
            if isinstance(metadata.get("candidate"), dict)
            else []
        )
        if isinstance(signals, list):
            report["legacy_signals_skipped"] += len(signals)

        artifacts.append(
            {
                "path": metadata_path.parent,
                "identity": identity,
                "title": title,
                "category_name": category_name,
                "publication": _publication_from_directory(
                    metadata_path.parent,
                    title,
                ),
            }
        )

    topic_by_path: dict[Path, TopicRecord] = {}
    for artifact in artifacts:
        metadata_directory = artifact["path"]
        identity = artifact["identity"]
        title = artifact["title"]
        category_name = artifact["category_name"]
        topic = store.find_topic_by_text(site, identity)
        if topic is None:
            topic = store.find_topic_by_text(site, title)
        category = store.find_category(site, category_name) if category_name else None
        category_id = (
            category.category_id
            if category is not None
            else _category_for_text(store, site, identity)
        )
        if topic is None:
            topic = store.create_topic(
                site,
                title,
                category_id,
                identity_key=f"legacy:{normalize_text(identity)}",
                aliases=list(
                    dict.fromkeys(
                        [identity, title, metadata_directory.name]
                    )
                ),
                canonical_intent="legacy-generated",
                status=TopicStatus.DISCOVERED,
            )
        else:
            updated = TopicRecord.from_dict(topic.to_dict())
            if title and normalize_text(title) != normalize_text(updated.canonical_title):
                updated.aliases = list(
                    dict.fromkeys([*updated.aliases, title, identity])
                )
            topic = store.upsert_topic(site, updated, expected_revision=topic.revision)
        topic_by_path[metadata_directory] = topic

    duplicate_owners = _duplicate_publication_owners(artifacts)
    for artifact in artifacts:
        metadata_directory = artifact["path"]
        topic = topic_by_path[metadata_directory]
        publication = artifact["publication"]
        if publication is not None:
            topic = store.get_topic(site, topic.topic_id) or topic
            owner_path = duplicate_owners.get(metadata_directory)
            if owner_path is not None:
                owner_topic = topic_by_path[owner_path]
                same_topic = owner_topic.topic_id == topic.topic_id
                reason = (
                    "Initial migration ignored duplicate local Blogger receipt "
                    f"post:{publication.blogger_post_id}; authoritative owner is "
                    f"{owner_topic.topic_id}"
                )
                if not same_topic:
                    updated = TopicRecord.from_dict(topic.to_dict())
                    note = (
                        f"{reason}. Review this topic independently; no runtime "
                        "topic merge was performed."
                    )
                    if not updated.publications:
                        updated.status = TopicStatus.REVIEW
                        updated.status_reason = reason
                    updated.editor_notes = list(
                        dict.fromkeys([*updated.editor_notes, note])
                    )
                    topic = store.upsert_topic(
                        site,
                        updated,
                        expected_revision=topic.revision,
                    )
                    topic_by_path[metadata_directory] = topic
                report["duplicate_publication_resolutions"].append(
                    {
                        "post_id": publication.blogger_post_id,
                        "owner_path": str(owner_path),
                        "owner_topic_id": owner_topic.topic_id,
                        "secondary_path": str(metadata_directory),
                        "secondary_topic_id": topic.topic_id,
                        "resolution": (
                            "SAME_TOPIC_COLLAPSED"
                            if same_topic
                            else "SECONDARY_REVIEW"
                        ),
                    }
                )
                continue
            try:
                store.record_publication(site, topic.topic_id, publication)
            except ValueError as exc:
                if "already owns a different primary publication" in str(exc):
                    updated = TopicRecord.from_dict(topic.to_dict())
                    publication.primary = False
                    updated.publications.append(publication)
                    try:
                        topic = store.upsert_topic(
                            site,
                            updated,
                            expected_revision=topic.revision,
                        )
                        topic_by_path[metadata_directory] = topic
                        continue
                    except ValueError as secondary_exc:
                        exc = secondary_exc
                report["conflicts"].append(
                    {
                        "path": str(metadata_directory),
                        "topic_id": topic.topic_id,
                        "error": str(exc),
                    }
                )

    report["primary_publication_resolutions"] = (
        _normalize_migration_primary_publications(store, site)
    )
    after_topics = {topic.topic_id: topic.to_dict() for topic in store.list_topics(site)}
    after_publications = sum(
        len(topic.publications) for topic in store.list_topics(site)
    )
    report["created_topics"] = len(set(after_topics) - set(before_topics))
    report["updated_topics"] = sum(
        1
        for topic_id in set(after_topics) & set(before_topics)
        if after_topics[topic_id] != before_topics[topic_id]
    )
    report["publication_links_added"] = max(
        0,
        after_publications - before_publications,
    )
    report["topic_count"] = len(after_topics)
    report["publication_count"] = after_publications
    return report


def _question_from_bundle(
    site: str,
    raw: dict[str, Any],
    default_collected_at: str,
) -> QuestionRecord:
    safe = {
        key: raw[key]
        for key in (
            "question_id",
            "source",
            "source_item_id",
            "source_id",
            "reddit_id",
            "external_id",
            "url",
            "permalink",
            "title",
            "question",
            "summary",
            "created_at",
            "posted_at",
            "created_utc",
            "collected_at",
            "engagement",
            "score",
            "comments",
            "upvotes",
            "views",
            "content_hash",
            "evidence_type",
            "evidence",
            "verification_method",
            "verified_at",
            "verified_by",
            "property_id",
            "site_property",
            "verified_by_codex",
            "topic_id",
            "aliases",
        )
        if key in raw
    }
    safe["site"] = site
    safe.setdefault("collected_at", default_collected_at)
    if raw.get("verified_by_codex") is True:
        source_id = str(
            raw.get("source_item_id")
            or raw.get("source_id")
            or raw.get("reddit_id")
            or raw.get("external_id")
            or ""
        ).strip()
        source_url = canonical_url(str(raw.get("url") or raw.get("permalink") or ""))
        if source_id and source_url:
            safe["source_item_id"] = source_id
            safe["url"] = source_url
            safe["verification_method"] = "verified_by_codex"
            safe["verified_by"] = "codex"
            safe["verified_at"] = str(
                raw.get("verified_at")
                or raw.get("collected_at")
                or default_collected_at
            )
    # body/selftext are intentionally not copied into the durable inbox.
    return QuestionRecord.from_dict(safe)


def _resolve_bundle_category(
    store: TopicStore,
    site: str,
    raw: dict[str, Any],
    title: str,
) -> str:
    category_id = str(raw.get("category_id") or "")
    if category_id and store.get_category(site, category_id):
        return category_id
    category_name = str(raw.get("category") or "")
    category = store.find_category(site, category_name) if category_name else None
    if category is not None:
        return category.category_id
    return _category_for_text(store, site, title)


def _import_weekly_bundle_mutating(
    store: TopicStore,
    site: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Import one collector/clustering snapshot using fail-closed evidence rules."""

    store.ensure_site(site, default_categories(site))
    run_id = str(bundle.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("Weekly bundle requires run_id")
    run_at = str(
        bundle.get("ended_at")
        or bundle.get("run_at")
        or bundle.get("collected_at")
        or utc_now()
    )
    requested_status = str(
        bundle.get("collector_status")
        or bundle.get("run_status")
        or bundle.get("status")
        or "SUCCESS"
    ).upper()
    if requested_status not in {"SUCCESS", "DEGRADED", "FAILED"}:
        raise ValueError("collector status must be SUCCESS, DEGRADED, or FAILED")

    report: dict[str, Any] = {
        "site": site,
        "run_id": run_id,
        "run_at": run_at,
        "questions_received": 0,
        "questions_upserted": 0,
        "clusters_received": 0,
        "clusters_created": 0,
        "clusters_updated": 0,
        "topics_received": 0,
        "topics_created": 0,
        "topics_updated": 0,
        "topics_ready": 0,
        "ready_rejected": [],
        "untrusted_evidence_exceptions": [],
        "invalid_evidence": [],
        "assignment_errors": [],
    }
    question_id_map: dict[str, str] = {}
    for index, raw_question in enumerate(bundle.get("questions") or []):
        if not isinstance(raw_question, dict):
            report["assignment_errors"].append(f"questions[{index}] is not an object")
            continue
        report["questions_received"] += 1
        question = _question_from_bundle(site, raw_question, run_at)
        if question.evidence_type in {
            EvidenceType.OBSERVED_QUESTION,
            EvidenceType.FIRST_PARTY_QUERY,
        } and not question.eligible_evidence:
            report["invalid_evidence"].append(
                {
                    "question_id": question.question_id,
                    "reason": (
                        "eligible evidence requires an immutable source id or canonical URL, "
                        "approved verification_method, verified_at, and verified_by"
                    ),
                }
            )
        saved = store.upsert_question(site, question)
        raw_id = str(raw_question.get("question_id") or question.question_id)
        question_id_map[raw_id] = saved.question_id
        question_id_map[question.question_id] = saved.question_id
        report["questions_upserted"] += 1

    cluster_id_map: dict[str, str] = {}
    for index, raw_cluster in enumerate(bundle.get("clusters") or []):
        if not isinstance(raw_cluster, dict):
            report["assignment_errors"].append(f"clusters[{index}] is not an object")
            continue
        report["clusters_received"] += 1
        signature = str(
            raw_cluster.get("problem_signature")
            or raw_cluster.get("canonical_label")
            or raw_cluster.get("label")
            or ""
        ).strip()
        if not signature:
            report["assignment_errors"].append(
                f"clusters[{index}] has no problem_signature"
            )
            continue
        raw_cluster_id = str(raw_cluster.get("cluster_id") or "")
        cluster_id = raw_cluster_id or stable_id("cluster", site, signature)
        existing_cluster = store.get_cluster(
            site,
            cluster_id,
            resolve_aliases=False,
        )
        cluster = ClusterRecord.from_dict(
            {
                **raw_cluster,
                "cluster_id": cluster_id,
                "site": site,
                "problem_signature": signature,
                "question_ids": [
                    question_id_map[str(item)]
                    for item in raw_cluster.get("question_ids", [])
                    if str(item) in question_id_map
                ],
                "observation_run_ids": list(
                    dict.fromkeys(
                        [
                            *list(raw_cluster.get("observation_run_ids") or []),
                            run_id,
                        ]
                    )
                ),
            }
        )
        saved_cluster = store.upsert_cluster(site, cluster)
        if existing_cluster is None:
            report["clusters_created"] += 1
        else:
            report["clusters_updated"] += 1
        cluster_id_map[raw_cluster_id or cluster_id] = saved_cluster.cluster_id
        cluster_id_map[saved_cluster.cluster_id] = saved_cluster.cluster_id

    topic_id_map: dict[str, str] = {}
    for index, raw_topic in enumerate(bundle.get("topics") or []):
        if not isinstance(raw_topic, dict):
            report["assignment_errors"].append(f"topics[{index}] is not an object")
            continue
        report["topics_received"] += 1
        title = str(
            raw_topic.get("canonical_title")
            or raw_topic.get("canonical_topic")
            or raw_topic.get("title")
            or raw_topic.get("seed")
            or ""
        ).strip()
        if not title:
            report["assignment_errors"].append(f"topics[{index}] has no title")
            continue
        raw_cluster_id = str(raw_topic.get("cluster_id") or "")
        cluster_id = cluster_id_map.get(raw_cluster_id, raw_cluster_id)
        problem_signature = str(raw_topic.get("problem_signature") or "")
        incoming_topic_id = str(raw_topic.get("topic_id") or "")
        existing = (
            store.get_topic(site, incoming_topic_id)
            if incoming_topic_id
            else None
        )
        if existing is None:
            existing = store.find_topic_by_text(
                site,
                title,
                cluster_id=cluster_id,
                problem_signature=problem_signature,
            )
        category_id = _resolve_bundle_category(store, site, raw_topic, title)
        requested_topic_status = TopicStatus(
            str(raw_topic.get("status") or TopicStatus.REVIEW.value).upper()
        )
        requested_action = TopicAction(
            str(raw_topic.get("action") or TopicAction.NEW_POST.value).upper()
        )
        if existing is None:
            topic = store.create_topic(
                site,
                title,
                category_id,
                identity_key=cluster_id or problem_signature or title,
                cluster_id=cluster_id,
                canonical_intent=str(raw_topic.get("canonical_intent") or raw_topic.get("intent") or ""),
                problem_signature=problem_signature,
                aliases=list(raw_topic.get("aliases") or []),
                action=requested_action,
                status=TopicStatus.REVIEW,
                priority_score=float(raw_topic.get("priority_score") or 0.0),
                editor_brief=str(raw_topic.get("editor_brief") or ""),
                reader_questions=list(raw_topic.get("reader_questions") or []),
                difference_from_existing=str(raw_topic.get("difference_from_existing") or ""),
                severity_score=float(raw_topic.get("severity_score") or 0.0),
                severity_reason=str(raw_topic.get("severity_reason") or ""),
                official_source_urls=list(raw_topic.get("official_source_urls") or []),
                official_source_refs=list(raw_topic.get("official_source_refs") or []),
                official_answerable=bool(raw_topic.get("official_answerable", False)),
                auditor_decision=str(raw_topic.get("auditor_decision") or ""),
                auditor_reasons=list(raw_topic.get("auditor_reasons") or []),
                audited_at=str(raw_topic.get("audited_at") or ""),
                # Evidence exceptions are approved through a separate
                # revision-checked user decision. Never trust self-approval
                # embedded in a research bundle.
                evidence_exception={},
                topic_id=incoming_topic_id,
            )
            report["topics_created"] += 1
        else:
            topic = TopicRecord.from_dict(existing.to_dict())
            topic.aliases = list(
                dict.fromkeys(
                    [*topic.aliases, *list(raw_topic.get("aliases") or [])]
                )
            )
            topic.cluster_id = cluster_id or topic.cluster_id
            topic.problem_signature = problem_signature or topic.problem_signature
            topic.canonical_intent = str(
                raw_topic.get("canonical_intent")
                or raw_topic.get("intent")
                or topic.canonical_intent
            )
            topic.category_id = category_id
            if topic.status not in {
                TopicStatus.PUBLISHED,
                TopicStatus.LIVE_UNVERIFIED,
                TopicStatus.MERGED,
            }:
                topic.action = requested_action
            topic.editor_brief = str(raw_topic.get("editor_brief") or topic.editor_brief)
            topic.reader_questions = list(
                dict.fromkeys(
                    [
                        *topic.reader_questions,
                        *list(raw_topic.get("reader_questions") or []),
                    ]
                )
            )
            topic.difference_from_existing = str(
                raw_topic.get("difference_from_existing")
                or topic.difference_from_existing
            )
            if "severity_score" in raw_topic:
                topic.severity_score = float(raw_topic.get("severity_score") or 0.0)
                topic.severity_reason = str(
                    raw_topic.get("severity_reason") or ""
                )
            topic.official_source_urls = list(
                dict.fromkeys(
                    [
                        *topic.official_source_urls,
                        *list(raw_topic.get("official_source_urls") or []),
                    ]
                )
            )
            existing_refs = {
                (item.get("url", ""), item.get("authority_type", "")): item
                for item in topic.official_source_refs
            }
            for item in raw_topic.get("official_source_refs") or []:
                if isinstance(item, dict):
                    existing_refs[
                        (
                            str(item.get("url") or ""),
                            str(item.get("authority_type") or "").upper(),
                        )
                    ] = dict(item)
            topic.official_source_refs = list(existing_refs.values())
            topic.official_answerable = bool(
                raw_topic.get("official_answerable", topic.official_answerable)
            )
            topic.auditor_decision = str(
                raw_topic.get("auditor_decision") or topic.auditor_decision
            ).upper()
            topic.auditor_reasons = list(
                dict.fromkeys(
                    [
                        *topic.auditor_reasons,
                        *list(raw_topic.get("auditor_reasons") or []),
                    ]
                )
            )
            topic.audited_at = str(raw_topic.get("audited_at") or topic.audited_at)
            topic = store.upsert_topic(
                site,
                topic,
                expected_revision=existing.revision,
            )
            report["topics_updated"] += 1
        raw_id = incoming_topic_id or topic.topic_id
        topic_id_map[raw_id] = topic.topic_id
        topic_id_map[topic.topic_id] = topic.topic_id

        for question_id in raw_topic.get("question_ids") or []:
            mapped_question_id = question_id_map.get(str(question_id), str(question_id))
            try:
                topic = store.link_question(site, mapped_question_id, topic.topic_id)
            except ValueError as exc:
                report["assignment_errors"].append(str(exc))
        topic = store.recalculate_priority(site, topic.topic_id)
        topic = store.refresh_duplicate_candidates(site, topic.topic_id)
        submitted_exception = dict(raw_topic.get("evidence_exception") or {})
        if submitted_exception and submitted_exception != topic.evidence_exception:
            report["untrusted_evidence_exceptions"].append(
                {
                    "topic_id": topic.topic_id,
                    "reason": (
                        "research bundles cannot approve single-signal "
                        "evidence exceptions"
                    ),
                }
            )
        if requested_topic_status is TopicStatus.READY:
            try:
                if topic.status is TopicStatus.DISCOVERED:
                    topic = store.mark_topic_status(
                        site,
                        topic.topic_id,
                        TopicStatus.REVIEW,
                    )
                topic = store.mark_topic_status(
                    site,
                    topic.topic_id,
                    TopicStatus.READY,
                )
                report["topics_ready"] += 1
            except ValueError as exc:
                report["ready_rejected"].append(
                    {"topic_id": topic.topic_id, "reason": str(exc)}
                )
        elif requested_topic_status in {
            TopicStatus.HOLD,
            TopicStatus.STALE,
            TopicStatus.REJECTED,
        }:
            try:
                topic = store.mark_topic_status(
                    site,
                    topic.topic_id,
                    requested_topic_status,
                    reason=f"Imported {requested_action.value} decision from {run_id}",
                )
            except ValueError as exc:
                report["assignment_errors"].append(str(exc))
        elif requested_action is TopicAction.WATCH:
            try:
                topic = store.mark_topic_status(
                    site,
                    topic.topic_id,
                    TopicStatus.HOLD,
                    reason=f"Imported WATCH decision from {run_id}",
                )
            except ValueError as exc:
                report["assignment_errors"].append(str(exc))
        elif requested_action is TopicAction.REJECT:
            try:
                topic = store.mark_topic_status(
                    site,
                    topic.topic_id,
                    TopicStatus.REJECTED,
                    reason=f"Imported REJECT decision from {run_id}",
                )
            except ValueError as exc:
                report["assignment_errors"].append(str(exc))
        cluster = store.get_cluster(site, topic.cluster_id)
        if cluster is not None and run_id not in cluster.observation_run_ids:
            cluster.observation_run_ids.append(run_id)
            store.upsert_cluster(
                site,
                cluster,
                expected_revision=cluster.revision,
            )

    for assignment in bundle.get("assignments") or []:
        if not isinstance(assignment, dict):
            continue
        question_id = question_id_map.get(
            str(assignment.get("question_id") or ""),
            str(assignment.get("question_id") or ""),
        )
        topic_id = topic_id_map.get(
            str(assignment.get("topic_id") or ""),
            str(assignment.get("topic_id") or ""),
        )
        try:
            store.link_question(site, question_id, topic_id)
        except ValueError as exc:
            report["assignment_errors"].append(str(exc))

    effective_status = requested_status
    if bundle.get("degraded") is True:
        effective_status = "DEGRADED"
    if (
        report["invalid_evidence"]
        or report["assignment_errors"]
        or report["ready_rejected"]
        or report["untrusted_evidence_exceptions"]
    ):
        effective_status = "DEGRADED"
    ready_topics = [
        topic
        for topic in store.list_topics(site, include_merged=False)
        if topic.status is TopicStatus.READY
    ]
    question_map = {
        question.question_id: question for question in store.list_questions(site)
    }
    ready_evidence = []
    synthetic_influence_count = 0
    for topic in ready_topics:
        gate = evidence_gate(
            topic,
            [
                question_map[question_id]
                for question_id in topic.question_ids
                if question_id in question_map
            ],
        )
        ready_evidence.extend(
            question_map[question_id]
            for question_id in gate.eligible_question_ids
            if question_id in question_map
        )
        synthetic_influence_count += sum(
            1
            for question_id in topic.question_ids
            if question_id in question_map
            and not question_map[question_id].eligible_evidence
        )
    unique_ready_evidence = {
        question.question_id: question for question in ready_evidence
    }
    locator_coverage = (
        sum(1 for item in unique_ready_evidence.values() if item.evidence_locator)
        / len(unique_ready_evidence)
        if unique_ready_evidence
        else 1.0
    )
    validation_issues = store.validate_site(site)
    structural_blogger_duplicate_count = sum(
        1 for issue in validation_issues if issue.code == "PUBLICATION_DUPLICATE"
    )
    semantic_blogger_duplicate_ids = store.semantic_publication_duplicates(
        site,
        set(topic_id_map.values()),
    )
    semantic_blogger_duplicate_count = sum(
        len(duplicate_ids)
        for duplicate_ids in semantic_blogger_duplicate_ids.values()
    )
    blogger_duplicate_count = (
        structural_blogger_duplicate_count
        + semantic_blogger_duplicate_count
    )
    auditor = bundle.get("auditor") if isinstance(bundle.get("auditor"), dict) else {}
    auditor_passed = (
        bool(auditor.get("passed"))
        and str(auditor.get("decision") or "").upper() == "PASS"
        and (
            auditor.get("evidence_locator_coverage_verified") is True
            or auditor.get("evidence_url_coverage_verified") is True
        )
        and auditor.get("synthetic_influence_verified") is True
        and auditor.get("blogger_duplicates_verified") is True
        and blogger_duplicate_count == 0
    )
    bundle_question_ids = set(question_id_map.values())
    verified_bundle_questions = [
        question
        for question_id, question in question_map.items()
        if question_id in bundle_question_ids and question.eligible_evidence
    ]
    source_count = len(
        {
            normalize_text(question.source)
            for question in verified_bundle_questions
        }
    )
    stop_condition = str(bundle.get("stop_condition") or "").upper()
    unexplored_scope = [
        str(item)
        for item in bundle.get("unexplored_scope") or []
        if str(item).strip()
    ]
    run_type = str(bundle.get("run_type") or "")
    coverage_manifest = [
        item
        for item in bundle.get("coverage_manifest") or []
        if isinstance(item, dict)
    ]
    required_coverage_incomplete = [
        item
        for item in coverage_manifest
        if item.get("required") is True
        and str(item.get("state") or "").upper() not in {"DONE", "SATURATED"}
    ]
    backfill_coverage_complete = (
        run_type != "BACKFILL_RESEARCH"
        or (
            bool(str(bundle.get("coverage_hash") or "").strip())
            and bool(coverage_manifest)
            and not required_coverage_incomplete
        )
    )
    complete = (
        bundle.get("complete") is True
        and bundle.get("degraded") is not True
        and stop_condition in {"EXHAUSTED", "SATURATED", "SOURCE_LIMIT"}
        and not unexplored_scope
        and bool(bundle.get("started_at"))
        and bool(bundle.get("ended_at"))
        and not report["invalid_evidence"]
        and not report["assignment_errors"]
        and not report["ready_rejected"]
        and backfill_coverage_complete
    )
    if not complete:
        effective_status = "DEGRADED"
    rollout_details = {
        "run_type": run_type,
        "started_at": str(bundle.get("started_at") or ""),
        "ended_at": str(bundle.get("ended_at") or run_at),
        "stop_condition": stop_condition,
        "complete": complete,
        "schema_valid": True,
        "ready_evidence_locator_coverage": round(locator_coverage, 6),
        # Retained for backwards-compatible reporting; this now represents
        # immutable evidence locator coverage, including Search Console
        # property/query receipts that do not have a public URL.
        "ready_evidence_url_coverage": round(locator_coverage, 6),
        "synthetic_influence_count": synthetic_influence_count,
        "blogger_duplicate_count": blogger_duplicate_count,
        "structural_blogger_duplicate_count": structural_blogger_duplicate_count,
        "semantic_blogger_duplicate_count": semantic_blogger_duplicate_count,
        "semantic_blogger_duplicate_ids": semantic_blogger_duplicate_ids,
        "auditor_passed": auditor_passed,
        "source_count": source_count,
        "verified_questions": len(verified_bundle_questions),
        "new_clusters": report["clusters_created"],
        "ready_topics": len(ready_topics),
        "unexplored_scope": unexplored_scope,
        "coverage_hash": str(bundle.get("coverage_hash") or ""),
        "logic_version": str(bundle.get("logic_version") or ""),
        "campaign_id": str(bundle.get("campaign_id") or ""),
        "sheet_sync_status": str(bundle.get("sheet_sync_status") or "PENDING"),
    }
    rollout = store.record_rollout_run(
        site,
        run_id,
        effective_status,
        run_at=str(bundle.get("started_at") or run_at),
        details=rollout_details,
    )
    report["effective_status"] = effective_status
    report["rollout"] = rollout
    return report


def import_weekly_bundle(
    store: TopicStore,
    site: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Stage, validate, then atomically commit a weekly bundle.

    No persistent file changes when schema, provenance, references, or
    post-apply registry validation fails.  A valid topic that misses a READY
    gate is committed in REVIEW with a DEGRADED run record, never published.
    """

    validate_weekly_bundle(bundle)
    run_id = str(bundle.get("run_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("run_id may only contain letters, numbers, dot, underscore, or hyphen")
    archive_path = store.site_dir(site) / "runs" / f"{run_id}.json"
    if archive_path.exists():
        archived = _read_json(archive_path)
        if archived != bundle:
            raise ValueError(f"run_id content mismatch for archived run {run_id}")
        return {
            "site": site,
            "run_id": run_id,
            "idempotent": True,
            "effective_status": str(
                next(
                    (
                        item.get("status")
                        for item in store.get_rollout_state(site).get("recent_runs") or []
                        if item.get("run_id") == run_id
                    ),
                    "ARCHIVED",
                )
            ),
            "rollout": store.get_rollout_state(site),
            "questions_received": len(bundle.get("questions") or []),
            "questions_upserted": 0,
            "clusters_received": len(bundle.get("clusters") or []),
            "clusters_created": 0,
            "clusters_updated": 0,
            "topics_received": len(bundle.get("topics") or []),
            "topics_created": 0,
            "topics_updated": 0,
            "topics_ready": 0,
            "ready_rejected": [],
            "invalid_evidence": [],
            "assignment_errors": [],
        }
    existing_state = store.get_rollout_state(site)
    if any(
        item.get("run_id") == bundle.get("run_id")
        for item in existing_state.get("recent_runs") or []
    ):
        return {
            "site": site,
            "run_id": str(bundle.get("run_id")),
            "idempotent": True,
            "effective_status": str(
                next(
                    item.get("status")
                    for item in existing_state.get("recent_runs") or []
                    if item.get("run_id") == bundle.get("run_id")
                )
            ),
            "rollout": existing_state,
            "questions_received": len(bundle.get("questions") or []),
            "questions_upserted": 0,
            "clusters_received": len(bundle.get("clusters") or []),
            "clusters_created": 0,
            "clusters_updated": 0,
            "topics_received": len(bundle.get("topics") or []),
            "topics_created": 0,
            "topics_updated": 0,
            "topics_ready": 0,
            "ready_rejected": [],
            "invalid_evidence": [],
            "assignment_errors": [],
        }
    run_at = str(
        bundle.get("ended_at")
        or bundle.get("run_at")
        or bundle.get("collected_at")
        or utc_now()
    )
    raw_question_ids = {
        str(item.get("question_id") or "")
        for item in bundle.get("questions") or []
        if isinstance(item, dict)
    }
    for raw in bundle.get("questions") or []:
        question = _question_from_bundle(site, raw, run_at)
        if question.evidence_type in {
            EvidenceType.OBSERVED_QUESTION,
            EvidenceType.FIRST_PARTY_QUERY,
        } and not question.eligible_evidence:
            raise ValueError(
                f"Invalid verified evidence provenance for {question.question_id}"
            )
    for raw in bundle.get("topics") or []:
        for question_id in raw.get("question_ids") or []:
            if str(question_id) not in raw_question_ids:
                raise ValueError(
                    f"Topic references question not present in bundle: {question_id}"
                )
    for raw in bundle.get("clusters") or []:
        for question_id in raw.get("question_ids") or []:
            if str(question_id) not in raw_question_ids:
                raise ValueError(
                    f"Cluster references question not present in bundle: {question_id}"
                )

    base_registry = store._load_registry(site)
    base_revision = int(base_registry.get("revision") or 0)
    with tempfile.TemporaryDirectory(prefix="topic-import-stage-") as directory:
        staging_root = Path(directory) / "topics"
        source_site = store.site_dir(site)
        if source_site.exists():
            shutil.copytree(source_site, staging_root / site)
        staged = TopicStore(staging_root)
        report = _import_weekly_bundle_mutating(staged, site, deepcopy(bundle))
        staged_archive_path = staged.site_dir(site) / "runs" / f"{run_id}.json"
        staged._atomic_write(staged_archive_path, deepcopy(bundle))
        hard_errors = [
            *report.get("invalid_evidence", []),
            *report.get("assignment_errors", []),
        ]
        validation_errors = [
            issue.to_dict()
            for issue in staged.validate_site(site)
            if issue.severity == "ERROR"
        ]
        if hard_errors or validation_errors:
            raise ValueError(
                "Weekly bundle failed staged validation: "
                + json.dumps(
                    {
                        "import_errors": hard_errors,
                        "validation_errors": validation_errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        with store._lock(site):
            current_revision = int(store._load_registry(site).get("revision") or 0)
            if current_revision != base_revision:
                raise ValueError(
                    "Registry changed during staged import; retry with a fresh bundle"
                )
            documents = [
                (staged.registry_path(site), store.registry_path(site)),
                (staged.inbox_path(site), store.inbox_path(site)),
                (staged.categories_path(site), store.categories_path(site)),
                (staged.proposals_path(site), store.proposals_path(site)),
                (staged_archive_path, archive_path),
            ]
            store._commit_documents_locked(
                site,
                [
                    (target, _read_json(source))
                    for source, target in documents
                ],
            )
        return report


def _posts_from_snapshot(
    snapshot: Any,
) -> tuple[list[dict[str, Any]], str, bool]:
    if isinstance(snapshot, list):
        return [item for item in snapshot if isinstance(item, dict)], "", False
    if not isinstance(snapshot, dict):
        raise ValueError("Blogger snapshot must be an object or list")
    posts = snapshot.get("posts")
    if posts is None:
        posts = snapshot.get("items")
    if posts is None and isinstance(snapshot.get("blogger"), dict):
        posts = [snapshot["blogger"]]
    if not isinstance(posts, list):
        raise ValueError("Blogger snapshot requires posts/items list")
    fetched_at = str(snapshot.get("fetched_at") or snapshot.get("verified_at") or "")
    authoritative_live = (
        snapshot.get("authoritative_live") is True
        and str(snapshot.get("source") or "").upper() == "BLOGGER_API"
    )
    return (
        [item for item in posts if isinstance(item, dict)],
        fetched_at,
        authoritative_live,
    )


def _topic_id_marker(post: dict[str, Any]) -> str:
    content = str(post.get("content") or post.get("body") or "")
    for pattern in TOPIC_MARKER_PATTERNS:
        match = pattern.search(content)
        if match:
            return match.group(1)
    return ""


def sync_blogger_snapshot(
    store: TopicStore,
    site: str,
    snapshot: Any,
    *,
    create_missing: bool = False,
) -> dict[str, Any]:
    """Reconcile an adapter-produced Blogger snapshot; never calls Blogger."""

    store.ensure_site(site, default_categories(site))
    posts, fetched_at, authoritative_live = _posts_from_snapshot(snapshot)
    complete_snapshot = bool(
        isinstance(snapshot, dict) and snapshot.get("complete_snapshot") is True
    )
    seen_publication_keys: set[str] = set()
    report: dict[str, Any] = {
        "site": site,
        "posts_received": len(posts),
        "matched": 0,
        "created": 0,
        "authoritative_live": authoritative_live,
        "unresolved": [],
        "conflicts": [],
    }
    catalog_entries: list[dict[str, Any]] = []
    registry_topics = store.list_topics(site)
    for raw in posts:
        publication = PublicationRef.from_dict(raw)
        seen_publication_keys.add(
            f"post:{publication.blogger_post_id}"
            if publication.blogger_post_id
            else f"url:{canonical_url(publication.url)}"
        )
        if (
            authoritative_live
            and fetched_at
            and publication.status.upper() in {"LIVE", "PUBLISHED"}
        ):
            publication.last_verified_at = fetched_at
        marker_topic_id = _topic_id_marker(raw)
        explicit_topic_id = str(raw.get("topic_id") or marker_topic_id or "")
        catalog_entry = {
            **publication.to_dict(),
            "last_seen_at": fetched_at,
            "topic_id": "",
            "has_topic_marker": bool(explicit_topic_id),
        }
        catalog_entries.append(catalog_entry)
        topic = store.get_topic(site, explicit_topic_id) if explicit_topic_id else None
        if topic is None:
            post_key_id = publication.blogger_post_id
            post_url = canonical_url(publication.url)
            matches = [
                candidate
                for candidate in registry_topics
                if any(
                    (
                        post_key_id
                        and item.blogger_post_id
                        and post_key_id == item.blogger_post_id
                    )
                    or (
                        post_url
                        and item.url
                        and post_url == canonical_url(item.url)
                    )
                    for item in candidate.publications
                )
            ]
            if len(matches) == 1:
                topic = matches[0]
        if topic is None and publication.title:
            matches = [
                candidate
                for candidate in registry_topics
                if normalize_text(publication.title)
                in {
                    normalize_text(candidate.canonical_title),
                    *(normalize_text(alias) for alias in candidate.aliases),
                }
            ]
            if len(matches) == 1:
                topic = matches[0]
            elif len(matches) > 1:
                report["conflicts"].append(
                    {
                        "post_id": publication.blogger_post_id,
                        "title": publication.title,
                        "topic_ids": [item.topic_id for item in matches],
                    }
                )
                continue
        if topic is None and create_missing and publication.title:
            topic = store.create_topic(
                site,
                publication.title,
                _category_for_text(store, site, publication.title),
                identity_key=f"blogger:{publication.blogger_post_id or publication.url}",
                aliases=[publication.title],
                status=TopicStatus.DISCOVERED,
            )
            registry_topics.append(topic)
            report["created"] += 1
        if topic is None:
            report["unresolved"].append(
                {
                    "post_id": publication.blogger_post_id,
                    "url": publication.url,
                    "title": publication.title,
                }
            )
            continue
        catalog_entry["topic_id"] = topic.topic_id
        try:
            store.reconcile_publication(site, topic.topic_id, publication)
            report["matched"] += 1
        except ValueError as exc:
            report["conflicts"].append(
                {
                    "post_id": publication.blogger_post_id,
                    "topic_id": topic.topic_id,
                    "error": str(exc),
                }
            )
    report["blogger_catalog_count"] = store.record_blogger_catalog_snapshot(
        site,
        catalog_entries,
        complete=complete_snapshot,
    )
    held_duplicate_ids: list[str] = []
    duplicate_map = store.semantic_publication_duplicates(site)
    for topic_id, duplicate_ids in duplicate_map.items():
        topic = store.get_topic(site, topic_id)
        if topic is None or topic.status is not TopicStatus.READY:
            continue
        refreshed = store.refresh_duplicate_candidates(site, topic_id)
        if not refreshed.duplicate_candidate_ids:
            continue
        store.mark_topic_status(
            site,
            topic_id,
            TopicStatus.HOLD,
            reason=(
                "Blogger reconciliation found semantic duplicate candidates: "
                + ", ".join(duplicate_ids)
            ),
            expected_revision=refreshed.revision,
        )
        held_duplicate_ids.append(topic_id)
    report["held_semantic_duplicate_topic_ids"] = held_duplicate_ids
    if complete_snapshot:
        stale_topic_ids = []
        for topic in store.list_topics(site, include_merged=False):
            if topic.status not in {
                TopicStatus.PUBLISHED,
                TopicStatus.LIVE_UNVERIFIED,
            }:
                continue
            topic_keys = {
                f"post:{item.blogger_post_id}"
                if item.blogger_post_id
                else f"url:{canonical_url(item.url)}"
                for item in topic.publications
            }
            if topic_keys and not (topic_keys & seen_publication_keys):
                store.mark_topic_status(
                    site,
                    topic.topic_id,
                    TopicStatus.STALE,
                    "missing from complete Blogger LIVE snapshot; never auto-republish",
                    expected_revision=topic.revision,
                )
                stale_topic_ids.append(topic.topic_id)
        report["stale_missing_topic_ids"] = stale_topic_ids
    else:
        report["stale_missing_topic_ids"] = []
    return report


def load_bundle(path: str | Path) -> Any:
    return _read_json(Path(path))
