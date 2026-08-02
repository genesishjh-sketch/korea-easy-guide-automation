from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.monthly import build_monthly_review
from src.topics.monthly import execute_monthly_reorganization
from src.topics.monthly import import_proposal_bundle
from src.topics.models import ProposalKind
from src.topics.models import ProposalStatus
from src.topics.models import PublicationRef
from src.topics.models import QuestionRecord
from src.topics.store import TopicStore


class TopicMonthlyTests(unittest.TestCase):
    @staticmethod
    def _observed_question(
        site: str,
        suffix: str,
        timestamp: str,
    ) -> QuestionRecord:
        return QuestionRecord.from_dict(
            {
                "question_id": f"question-{suffix}",
                "site": site,
                "source": "reddit",
                "source_item_id": f"reddit-{suffix}",
                "url": (
                    "https://www.reddit.com/r/koreatravel/comments/"
                    f"{suffix}/question"
                ),
                "title": f"Observed question {suffix}",
                "created_at": timestamp,
                "collected_at": timestamp,
                "evidence_type": "OBSERVED_QUESTION",
                "verification_method": "verified_by_codex",
                "verified_at": timestamp,
                "verified_by": "codex",
            }
        )

    def test_label_change_waits_for_external_sync_and_has_rollback_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "korea_easy_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(
                site,
                "Published transport topic",
                categories[0].category_id,
            )
            store.record_publication(
                site,
                topic.topic_id,
                PublicationRef(
                    blogger_post_id="post-1",
                    url="https://example.blogspot.com/post.html",
                    status="LIVE",
                    last_verified_at="2026-07-26T20:00:00+09:00",
                ),
            )
            proposal = store.create_monthly_proposal(
                site,
                ProposalKind.LABEL_CHANGE,
                {
                    "category_id": categories[0].category_id,
                    "blogger_label": "Korea Transportation",
                },
                reason="Clearer label",
            )
            with self.assertRaisesRegex(ValueError, "APPROVED"):
                store.apply_monthly_proposal(site, proposal.proposal_id)
            store.approve_monthly_proposal(
                site,
                proposal.proposal_id,
                "editor@example.com",
                "Approved after review",
            )
            pending = store.apply_monthly_proposal(site, proposal.proposal_id)

            self.assertEqual(pending.status, ProposalStatus.APPROVED)
            self.assertTrue(pending.publication_sync_pending)
            self.assertTrue(Path(pending.snapshot_path).exists())
            self.assertTrue(Path(pending.rollback_path).exists())
            applied = store.mark_proposal_publication_sync(
                site,
                proposal.proposal_id,
                success=True,
            )
            self.assertEqual(applied.status, ProposalStatus.APPLIED)
            rolled_back = store.rollback_monthly_proposal(
                site,
                proposal.proposal_id,
            )
            self.assertEqual(rolled_back.status, ProposalStatus.ROLLED_BACK)
            self.assertTrue(Path(rolled_back.rollback_path).exists())
            self.assertTrue(Path(rolled_back.rollback_audit_path).exists())
            self.assertEqual(
                store.get_category(site, categories[0].category_id).blogger_label,
                categories[0].blogger_label,
            )

    def test_published_cluster_merge_is_proposal_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            first = store.create_topic(site, "Wi-Fi fails A", categories[0].category_id)
            second = store.create_topic(site, "Wi-Fi fails B", categories[0].category_id)
            store.record_publication(
                site,
                first.topic_id,
                PublicationRef(
                    blogger_post_id="post-a",
                    url="https://example.blogspot.com/a.html",
                    status="LIVE",
                    last_verified_at="2026-07-26T20:00:00+09:00",
                ),
            )
            with self.assertRaisesRegex(ValueError, "approved monthly proposal"):
                store.merge_clusters(site, first.cluster_id, second.cluster_id)

            proposal = store.create_monthly_proposal(
                site,
                ProposalKind.MERGE_CLUSTER,
                {
                    "source_cluster_id": first.cluster_id,
                    "target_cluster_id": second.cluster_id,
                },
                "Same durable problem",
            )
            store.approve_monthly_proposal(
                site,
                proposal.proposal_id,
                "editor@example.com",
            )
            applied = store.apply_monthly_proposal(site, proposal.proposal_id)
            self.assertEqual(applied.status, ProposalStatus.APPLIED)
            self.assertEqual(
                store.get_cluster(site, first.cluster_id).cluster_id,
                second.cluster_id,
            )

    def test_generated_published_merge_proposal_is_human_reviewable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            first = store.create_topic(
                site,
                "Network Adapter Missing in Windows 11: Device Manager and BIOS Boundaries",
                categories[0].category_id,
            )
            second = store.create_topic(
                site,
                "Network Adapter Missing in Windows 11? Check Device Manager and Updates",
                categories[0].category_id,
            )
            store.record_publication(
                site,
                first.topic_id,
                PublicationRef(
                    blogger_post_id="post-network",
                    url="https://example.blogspot.com/network.html",
                    status="LIVE",
                    last_verified_at="2026-07-26T20:00:00+09:00",
                ),
            )
            recent_question = self._observed_question(
                site,
                "network-adapter",
                "2026-07-01T00:00:00+00:00",
            )
            store.upsert_question(site, recent_question)
            store.link_question(
                site,
                recent_question.question_id,
                second.topic_id,
            )

            result = execute_monthly_reorganization(
                store,
                site,
                as_of="2026-07-29T00:00:00+00:00",
            )
            proposal = store.get_monthly_proposal(
                site,
                result["generated_proposal_ids"][0],
            )

            self.assertEqual(result["auto_merges"], [])
            self.assertIn(first.canonical_title, proposal.payload["current_value"])
            self.assertIn(second.canonical_title, proposal.payload["current_value"])
            self.assertIn(
                proposal.payload["source_cluster_id"],
                proposal.payload["proposed_value"],
            )
            self.assertIn("Semantic similarity", proposal.payload["evidence_summary"])
            self.assertIn("publication URLs", proposal.payload["impact"])

    def test_monthly_scope_is_recent_twelve_months_plus_all_publications(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "korea_easy_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            old = store.create_topic(
                site,
                "Old unpublished question",
                categories[0].category_id,
            )
            old_question = self._observed_question(
                site,
                "old",
                "2020-01-01T00:00:00+00:00",
            )
            store.upsert_question(site, old_question)
            store.link_question(site, old_question.question_id, old.topic_id)

            recent = store.create_topic(
                site,
                "Recent unpublished question",
                categories[0].category_id,
            )
            recent_question = self._observed_question(
                site,
                "recent",
                "2026-07-01T00:00:00+00:00",
            )
            store.upsert_question(site, recent_question)
            store.link_question(
                site,
                recent_question.question_id,
                recent.topic_id,
            )

            published = store.create_topic(
                site,
                "Historical published guide",
                categories[0].category_id,
            )
            store.record_publication(
                site,
                published.topic_id,
                PublicationRef(
                    blogger_post_id="historical-post",
                    url="https://example.blogspot.com/historical.html",
                    status="LIVE",
                    last_verified_at="2020-01-01T00:00:00+00:00",
                ),
            )

            review = build_monthly_review(
                store,
                site,
                as_of="2026-07-29T00:00:00+00:00",
            )

            self.assertEqual(review["total_topic_count"], 3)
            self.assertEqual(review["topic_count"], 2)
            self.assertEqual(
                review["excluded_stale_unpublished_topic_count"],
                1,
            )
            self.assertEqual(review["question_count"], 1)
            self.assertEqual(review["publication_count"], 1)

    def test_identity_critical_tokens_prevent_false_duplicate_merges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            pairs = (
                (
                    "Windows Update error 0x80070103",
                    "Windows Update error 0x80070002",
                ),
                (
                    "Seollal travel tips",
                    "Chuseok travel tips",
                ),
                (
                    "High CPU Usage Windows 11: A Low-Risk Windows Diagnostic Path",
                    "High Disk Usage Windows 11: A Low-Risk Windows Diagnostic Path",
                ),
                (
                    "Photos App Not Opening Windows 11: Trace the Failure Before You Reset Anything",
                    "Microsoft Store Not Opening Windows 11: Trace the Failure Before You Reset Anything",
                ),
            )
            for pair_index, pair in enumerate(pairs):
                for topic_index, title in enumerate(pair):
                    topic = store.create_topic(
                        site,
                        title,
                        categories[0].category_id,
                        problem_signature=title,
                    )
                    question = self._observed_question(
                        site,
                        f"identity-{pair_index}-{topic_index}",
                        "2026-07-01T00:00:00+00:00",
                    )
                    store.upsert_question(site, question)
                    store.link_question(site, question.question_id, topic.topic_id)

            review = build_monthly_review(
                store,
                site,
                as_of="2026-07-29T00:00:00+00:00",
            )

            self.assertEqual(review["duplicate_pairs"], [])
            self.assertGreaterEqual(
                len(review["identity_conflicts_excluded"]),
                3,
            )
            identity_token_pairs = [
                {
                    *item["left_identity_tokens"],
                    *item["right_identity_tokens"],
                }
                for item in review["identity_conflicts_excluded"]
            ]
            self.assertTrue(
                any(
                    {
                        "entity:resource:cpu",
                        "entity:resource:disk",
                    }
                    <= tokens
                    for tokens in identity_token_pairs
                )
            )
            self.assertTrue(
                any(
                    {
                        "entity:component:photos-app",
                        "entity:component:microsoft-store",
                    }
                    <= tokens
                    for tokens in identity_token_pairs
                )
            )
            self.assertEqual(
                len(
                    [
                        topic
                        for topic in store.list_topics(site)
                        if topic.status.value == "MERGED"
                    ]
                ),
                0,
            )

    def test_exact_unpublished_duplicate_is_merged_with_aliases_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topics = []
            for index, title in enumerate(
                ("Printer offline on desktop", "Printer appears offline")
            ):
                topic = store.create_topic(
                    site,
                    title,
                    categories[0].category_id,
                    problem_signature=f"printer-state-{index}",
                    aliases=["printer offline recovery"],
                )
                question = self._observed_question(
                    site,
                    f"printer-{index}",
                    "2026-07-01T00:00:00+00:00",
                )
                store.upsert_question(site, question)
                store.link_question(site, question.question_id, topic.topic_id)
                topics.append(topic)

            result = execute_monthly_reorganization(
                store,
                site,
                as_of="2026-07-29T00:00:00+00:00",
            )

            self.assertEqual(len(result["auto_merges"]), 1)
            source_id = result["auto_merges"][0]["source_topic_id"]
            target_id = result["auto_merges"][0]["target_topic_id"]
            source = store.get_topic(site, source_id, resolve_aliases=False)
            target = store.get_topic(site, target_id)
            self.assertEqual(source.status.value, "MERGED")
            self.assertEqual(source.merged_into_topic_id, target_id)
            self.assertIn(source_id, target.aliases)
            self.assertEqual(len(target.question_ids), 2)

    def test_monthly_proposal_bundle_is_schema_validated_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "korea_easy_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            bundle = {
                "schema_version": 1,
                "site": site,
                "reviewed_at": "2026-07-29T00:00:00+00:00",
                "window_start": "2025-07-29T00:00:00+00:00",
                "auditor": {
                    "decision": "PASS",
                    "auditor_id": "codex-auditor",
                    "reviewed_at": "2026-07-29T00:00:00+00:00",
                },
                "proposals": [
                    {
                        "proposal_id": "valid_first",
                        "kind": "LABEL_CHANGE",
                        "payload": {
                            "category_id": categories[0].category_id,
                            "blogger_label": "Korea Transportation",
                        },
                        "reason": "Clearer label",
                    },
                    {
                        "proposal_id": "invalid_second",
                        "kind": "LABEL_CHANGE",
                        "payload": {
                            "category_id": categories[1].category_id,
                        },
                        "reason": "Missing public label",
                    },
                ],
            }

            with self.assertRaisesRegex(ValueError, "schema validation failed"):
                import_proposal_bundle(store, site, bundle)

            self.assertEqual(store.list_monthly_proposals(site), [])


if __name__ == "__main__":
    unittest.main()
