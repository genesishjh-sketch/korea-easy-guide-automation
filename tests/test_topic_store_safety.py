from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.topics.defaults import default_categories
from src.topics.models import ProposalKind
from src.topics.models import ProposalStatus
from src.topics.models import TopicStatus
from src.topics.store import TopicStore


SITE = "korea_easy_guide"
QUALIFYING_RUN_IDS = (
    "weekly-2026-07-05",
    "weekly-2026-07-12",
    "weekly-2026-07-19",
)


class TopicStoreSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.categories = default_categories(SITE)
        self.store.ensure_site(SITE, self.categories)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_multi_document_commit_rolls_back_after_partial_write(self) -> None:
        first = self.store.site_dir(SITE) / "transaction-a.json"
        second = self.store.site_dir(SITE) / "transaction-b.json"
        self.store._atomic_write(first, {"value": "old-a"})
        self.store._atomic_write(second, {"value": "old-b"})
        original_write = self.store._atomic_write

        def flaky_write(path, document):
            if path == second and document == {"value": "new-b"}:
                raise OSError("injected second write failure")
            return original_write(path, document)

        with self.assertRaisesRegex(OSError, "injected"):
            with self.store._lock(SITE):
                with patch.object(
                    self.store,
                    "_atomic_write",
                    side_effect=flaky_write,
                ):
                    self.store._commit_documents_locked(
                        SITE,
                        [
                            (first, {"value": "new-a"}),
                            (second, {"value": "new-b"}),
                        ],
                    )

        self.assertEqual(
            self.store._read_json(first, {}),
            {"value": "old-a"},
        )
        self.assertEqual(
            self.store._read_json(second, {}),
            {"value": "old-b"},
        )
        self.assertFalse(
            self.store._transaction_journal_path(SITE).exists()
        )

    def _record_qualifying_runs(self) -> None:
        self.store.record_rollout_run(
            SITE,
            "completed-backfill",
            "SUCCESS",
            run_at="2026-07-04T10:00:00+09:00",
            details={
                "run_type": "BACKFILL_RESEARCH",
                "complete": True,
                "schema_valid": True,
                "coverage_hash": "coverage-v1",
                "logic_version": "test-v1",
                "unexplored_scope": [],
            },
        )
        details = {
            "run_type": "WEEKLY_RESEARCH",
            "complete": True,
            "schema_valid": True,
            "ready_evidence_url_coverage": 1.0,
            "synthetic_influence_count": 0,
            "blogger_duplicate_count": 0,
            "auditor_passed": True,
            "source_count": 1,
        }
        for run_id, run_at in zip(
            QUALIFYING_RUN_IDS,
            (
                "2026-07-05T20:00:00+09:00",
                "2026-07-12T20:00:00+09:00",
                "2026-07-19T20:00:00+09:00",
            ),
            strict=True,
        ):
            self.store.record_rollout_run(
                SITE,
                run_id,
                "SUCCESS",
                run_at=run_at,
                details=details,
            )

    def _create_observed_topic(
        self,
        suffix: str,
        status: TopicStatus,
    ):
        topic = self.store.create_topic(
            SITE,
            f"Topic {suffix}",
            self.categories[0].category_id,
            cluster_id=f"cluster-{suffix}",
            canonical_intent=f"intent-{suffix}",
            problem_signature=f"problem-{suffix}",
            status=status,
        )
        cluster = self.store.get_cluster(SITE, topic.cluster_id)
        self.assertIsNotNone(cluster)
        cluster.observation_run_ids = list(QUALIFYING_RUN_IDS)
        self.store.upsert_cluster(
            SITE,
            cluster,
            expected_revision=cluster.revision,
        )
        return topic

    def test_published_identity_fields_cannot_change_through_generic_upsert(self) -> None:
        replacements = {
            "canonical_title": "A rewritten canonical title",
            "category_id": self.categories[1].category_id,
            "cluster_id": "cluster-replacement",
            "canonical_intent": "a different reader intent",
            "problem_signature": "a different problem signature",
        }
        for status in (TopicStatus.PUBLISHED, TopicStatus.LIVE_UNVERIFIED):
            for field, replacement in replacements.items():
                with self.subTest(status=status.value, field=field):
                    topic = self.store.create_topic(
                        SITE,
                        f"{status.value} {field}",
                        self.categories[0].category_id,
                        identity_key=f"{status.value}-{field}",
                        canonical_intent=f"intent-{field}",
                        problem_signature=f"problem-{field}",
                        status=status,
                    )
                    candidate = topic.to_dict()
                    candidate[field] = replacement
                    with self.assertRaisesRegex(
                        ValueError,
                        "identity is immutable through upsert_topic",
                    ):
                        self.store.upsert_topic(
                            SITE,
                            candidate,
                            expected_revision=topic.revision,
                        )
                    persisted = self.store.get_topic(SITE, topic.topic_id)
                    self.assertEqual(
                        getattr(persisted, field),
                        getattr(topic, field),
                    )

    def test_published_non_identity_edits_and_approved_reassignment_still_work(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Published topic with editable brief",
            self.categories[0].category_id,
            canonical_intent="retain this intent",
            problem_signature="retain this problem",
            status=TopicStatus.PUBLISHED,
        )
        candidate = topic.to_dict()
        candidate["editor_brief"] = "A safer, more detailed editorial brief."
        updated = self.store.upsert_topic(
            SITE,
            candidate,
            expected_revision=topic.revision,
        )
        self.assertEqual(
            updated.editor_brief,
            "A safer, more detailed editorial brief.",
        )

        proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.REASSIGN_CATEGORY,
            {
                "topic_id": topic.topic_id,
                "category_id": self.categories[1].category_id,
            },
            reason="Approved category correction",
        )
        self.store.approve_monthly_proposal(
            SITE,
            proposal.proposal_id,
            "editor@example.com",
        )
        self.store.apply_monthly_proposal(SITE, proposal.proposal_id)
        reassigned = self.store.get_topic(SITE, topic.topic_id)
        self.assertEqual(reassigned.category_id, self.categories[1].category_id)

    def test_published_cluster_labels_cannot_change_through_generic_upsert(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Published cluster identity",
            self.categories[0].category_id,
            status=TopicStatus.PUBLISHED,
        )
        cluster = self.store.get_cluster(SITE, topic.cluster_id)
        self.assertIsNotNone(cluster)
        cluster.problem_signature = "A different public problem identity"

        with self.assertRaisesRegex(
            ValueError,
            "Published cluster identity is immutable through upsert_cluster",
        ):
            self.store.upsert_cluster(
                SITE,
                cluster,
                expected_revision=cluster.revision,
            )

    def test_create_category_rejects_duplicate_cluster_ids(self) -> None:
        self._record_qualifying_runs()
        topics = [
            self._create_observed_topic(str(index), TopicStatus.READY)
            for index in range(3)
        ]
        proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.CREATE_CATEGORY,
            {
                "category": {"name": "Duplicate-inflated category"},
                "cluster_ids": [
                    topics[0].cluster_id,
                    topics[1].cluster_id,
                    topics[2].cluster_id,
                    topics[0].cluster_id,
                    topics[1].cluster_id,
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "duplicate cluster IDs"):
            self.store.approve_monthly_proposal(
                SITE,
                proposal.proposal_id,
                "editor@example.com",
            )

    def test_split_category_rejects_duplicate_cluster_ids(self) -> None:
        topics = [
            self._create_observed_topic(f"split-{index}", TopicStatus.READY)
            for index in range(3)
        ]
        proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.SPLIT_CATEGORY,
            {
                "groups": [
                    {
                        "cluster_ids": [
                            topics[0].cluster_id,
                            topics[1].cluster_id,
                            topics[2].cluster_id,
                            topics[0].cluster_id,
                        ]
                    }
                ]
            },
        )
        with self.assertRaisesRegex(ValueError, "duplicate cluster IDs"):
            self.store.approve_monthly_proposal(
                SITE,
                proposal.proposal_id,
                "editor@example.com",
            )

    def test_category_threshold_does_not_count_live_unverified_as_published(self) -> None:
        self._record_qualifying_runs()
        statuses = (
            TopicStatus.READY,
            TopicStatus.READY,
            TopicStatus.LIVE_UNVERIFIED,
            TopicStatus.REVIEW,
            TopicStatus.REVIEW,
        )
        topics = [
            self._create_observed_topic(f"status-{index}", status)
            for index, status in enumerate(statuses)
        ]
        proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.CREATE_CATEGORY,
            {
                "category": {"name": "Premature category"},
                "cluster_ids": [topic.cluster_id for topic in topics],
            },
        )
        with self.assertRaisesRegex(ValueError, "3 READY/PUBLISHED topics"):
            self.store.approve_monthly_proposal(
                SITE,
                proposal.proposal_id,
                "editor@example.com",
            )

    def test_category_threshold_counts_ready_and_published_topics(self) -> None:
        self._record_qualifying_runs()
        statuses = (
            TopicStatus.READY,
            TopicStatus.PUBLISHED,
            TopicStatus.PUBLISHED,
            TopicStatus.REVIEW,
            TopicStatus.REVIEW,
        )
        topics = [
            self._create_observed_topic(f"eligible-{index}", status)
            for index, status in enumerate(statuses)
        ]
        proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.CREATE_CATEGORY,
            {
                "category": {"name": "Eligible category"},
                "cluster_ids": [topic.cluster_id for topic in topics],
            },
        )
        approved = self.store.approve_monthly_proposal(
            SITE,
            proposal.proposal_id,
            "editor@example.com",
        )
        self.assertEqual(approved.status, ProposalStatus.APPROVED)

    def test_explicit_proposal_ids_are_safe_and_collisions_are_strict(self) -> None:
        for unsafe_id in ("../escape", "/tmp/escape", r"..\escape", "proposal.bad"):
            with self.subTest(unsafe_id=unsafe_id):
                with self.assertRaisesRegex(ValueError, "proposal_id must match"):
                    self.store.create_monthly_proposal(
                        SITE,
                        ProposalKind.LABEL_CHANGE,
                        {"category_id": self.categories[0].category_id},
                        proposal_id=unsafe_id,
                    )

        original = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.LABEL_CHANGE,
            {
                "category_id": self.categories[0].category_id,
                "blogger_label": "Travel Basics",
            },
            reason="Clearer public label",
            proposal_id="proposal-safe_01",
        )
        repeated = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.LABEL_CHANGE,
            {
                "category_id": self.categories[0].category_id,
                "blogger_label": "Travel Basics",
            },
            reason="Clearer public label",
            proposal_id="proposal-safe_01",
        )
        self.assertEqual(repeated.to_dict(), original.to_dict())

        collisions = (
            (
                ProposalKind.RENAME_CATEGORY,
                original.payload,
                original.reason,
            ),
            (
                original.kind,
                {**original.payload, "blogger_label": "Different label"},
                original.reason,
            ),
            (
                original.kind,
                original.payload,
                "A different reason",
            ),
        )
        for kind, payload, reason in collisions:
            with self.subTest(kind=kind.value, payload=payload, reason=reason):
                with self.assertRaisesRegex(ValueError, "Proposal id collision"):
                    self.store.create_monthly_proposal(
                        SITE,
                        kind,
                        payload,
                        reason=reason,
                        proposal_id=original.proposal_id,
                    )

    def test_registry_and_proposal_map_keys_must_match_internal_ids(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Map identity topic",
            self.categories[0].category_id,
        )
        registry_path = self.store.registry_path(SITE)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["topics"]["wrong-topic-key"] = registry["topics"].pop(topic.topic_id)
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "topics map key"):
            self.store.list_topics(SITE)

        second_store = TopicStore(Path(self.temp.name) / "other-topics")
        second_store.ensure_site(SITE, self.categories)
        proposal = second_store.create_monthly_proposal(
            SITE,
            ProposalKind.LABEL_CHANGE,
            {"category_id": self.categories[0].category_id},
            proposal_id="proposal-safe-map",
        )
        proposals_path = second_store.proposals_path(SITE)
        proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
        proposals["proposals"]["wrong-proposal-key"] = proposals["proposals"].pop(
            proposal.proposal_id
        )
        proposals_path.write_text(
            json.dumps(proposals, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "proposals map key"):
            second_store.validate_site(SITE)


if __name__ == "__main__":
    unittest.main()
