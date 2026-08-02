from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.defaults import default_category_id
from src.topics.migration import backfill_local_history
from src.topics.migration import import_weekly_bundle
from src.topics.migration import sync_blogger_snapshot
from src.topics.models import PublicationRef
from src.topics.models import TopicStatus
from src.topics.sheet_export import build_sheet_export
from src.topics.store import ROLLOUT_READY_FIRST
from src.topics.store import ROLLOUT_SHADOW
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


def weekly_bundle(run_id: str, ended_at: str) -> dict:
    category_id = default_category_id(SITE, "Transportation")
    questions = []
    for suffix in ("one", "two"):
        questions.append(
            {
                "question_id": f"q-{suffix}",
                "source": "reddit",
                "source_id": f"source-{suffix}",
                "url": f"https://www.reddit.com/r/koreatravel/comments/{suffix}/question",
                "title": f"Observed question {suffix}",
                "summary": "Short retained summary.",
                "posted_at": "2026-07-20T10:00:00+09:00",
                "collected_at": ended_at,
                "engagement": {"comments": 4},
                "evidence_type": "OBSERVED_QUESTION",
                "verified_by_codex": True
            }
        )
    return {
        "schema_version": 1,
        "site": SITE,
        "run_id": run_id,
        "run_type": "WEEKLY_RESEARCH",
        "started_at": ended_at.replace("20:15", "20:00"),
        "ended_at": ended_at,
        "complete": True,
        "degraded": False,
        "stop_condition": "EXHAUSTED",
        "checkpoint": {"cursor": "done", "searched_scope": ["reddit"]},
        "source_coverage": {"reddit": 2},
        "unexplored_scope": [],
        "synthetic_influence_count": 0,
        "blogger_duplicate_count": 0,
        "auditor": {
            "passed": True,
            "decision": "PASS",
            "auditor_id": "codex-auditor",
            "evidence_url_coverage_verified": True,
            "synthetic_influence_verified": True,
            "blogger_duplicates_verified": True
        },
        "questions": questions,
        "clusters": [
            {
                "cluster_id": "cluster-airport-transfer",
                "problem_signature": "airport transfer fails after late arrival",
                "canonical_label": "Late airport transfer recovery",
                "question_ids": ["q-one", "q-two"],
                "topic_ids": ["topic-airport-transfer"],
                "aliases": [],
                "observation_run_ids": []
            }
        ],
        "topics": [
            {
                "topic_id": "topic-airport-transfer",
                "cluster_id": "cluster-airport-transfer",
                "canonical_title": "What to do when an airport transfer fails",
                "category_id": category_id,
                "action": "NEW_POST",
                "status": "READY",
                "question_ids": ["q-one", "q-two"],
                "aliases": [],
                "priority_score": 50
                ,
                "editor_brief": "Explain recovery choices and official escalation paths.",
                "reader_questions": ["What should I do when the transfer does not arrive?"],
                "difference_from_existing": "No existing post covers failed late arrivals.",
                "official_source_urls": ["https://english.visitkorea.or.kr/"],
                "official_source_refs": [
                    {
                        "url": "https://english.visitkorea.or.kr/",
                        "authority_type": "GOVERNMENT"
                    }
                ],
                "official_answerable": True,
                "auditor_decision": "PASS",
                "auditor_reasons": ["Official guidance can answer the question."],
                "audited_at": ended_at
            }
        ],
        "assignments": []
    }


class WeeklyImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.store.record_rollout_run(
            SITE,
            "completed-backfill",
            "SUCCESS",
            run_at="2026-07-18T10:00:00+09:00",
            details={
                "run_type": "BACKFILL_RESEARCH",
                "complete": True,
                "schema_valid": True,
                "coverage_hash": "coverage-v1",
                "logic_version": "test-v1",
                "unexplored_scope": [],
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_two_distinct_complete_sunday_runs_promote_and_rerun_is_idempotent(self) -> None:
        first = weekly_bundle("weekly-1", "2026-07-19T20:15:00+09:00")
        second = weekly_bundle("weekly-2", "2026-07-26T20:15:00+09:00")

        report_one = import_weekly_bundle(self.store, SITE, first)
        self.assertEqual(report_one["rollout"]["mode"], ROLLOUT_SHADOW)
        first_details = report_one["rollout"]["recent_runs"][-1]["details"]
        self.assertEqual(first_details["verified_questions"], 2)
        self.assertEqual(first_details["source_count"], 1)
        self.assertEqual(first_details["new_clusters"], 1)
        self.assertEqual(first_details["ready_evidence_url_coverage"], 1.0)
        report_two = import_weekly_bundle(self.store, SITE, second)
        self.assertEqual(report_two["rollout"]["mode"], ROLLOUT_READY_FIRST)
        revision = self.store._load_registry(SITE)["revision"]

        repeated = import_weekly_bundle(self.store, SITE, second)
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(self.store._load_registry(SITE)["revision"], revision)

    def test_sheet_export_reports_created_not_received_clusters(self) -> None:
        first = weekly_bundle("weekly-created", "2026-07-19T20:15:00+09:00")
        repeated_cluster = weekly_bundle(
            "weekly-existing-cluster",
            "2026-07-26T20:15:00+09:00",
        )

        import_weekly_bundle(self.store, SITE, first)
        report = import_weekly_bundle(self.store, SITE, repeated_cluster)
        payload = build_sheet_export(self.store, [SITE])
        run = next(
            item
            for item in payload["runs"]
            if item["run_id"] == "weekly-existing-cluster"
        )

        self.assertEqual(report["clusters_received"], 1)
        self.assertEqual(report["clusters_created"], 0)
        self.assertEqual(run["new_clusters"], 0)

    def test_monday_run_cannot_promote(self) -> None:
        monday = weekly_bundle("monday-1", "2026-07-20T20:15:00+09:00")
        import_weekly_bundle(self.store, SITE, monday)
        monday["run_id"] = "monday-2"
        import_weekly_bundle(self.store, SITE, monday)
        self.assertEqual(self.store.get_rollout_mode(SITE), ROLLOUT_SHADOW)

    def test_complete_run_without_ready_topics_uses_vacuous_ready_url_coverage(self) -> None:
        bundle = weekly_bundle(
            "no-ready-yet",
            "2026-07-19T20:15:00+09:00",
        )
        bundle["topics"][0]["status"] = "REVIEW"

        report = import_weekly_bundle(self.store, SITE, bundle)
        details = report["rollout"]["recent_runs"][-1]["details"]

        self.assertEqual(report["effective_status"], "SUCCESS")
        self.assertTrue(report["rollout"]["recent_runs"][-1]["qualifying"])
        self.assertEqual(details["ready_topics"], 0)
        self.assertEqual(details["ready_evidence_url_coverage"], 1.0)
        self.assertEqual(details["verified_questions"], 2)
        self.assertEqual(details["new_clusters"], 1)

    def test_incomplete_stop_condition_cannot_claim_complete_or_promote(self) -> None:
        invalid = weekly_bundle(
            "time-budget-1",
            "2026-07-19T20:15:00+09:00",
        )
        invalid["stop_condition"] = "TIME_BUDGET"
        invalid["unexplored_scope"] = ["reddit:next-page"]

        with self.assertRaisesRegex(ValueError, "weekly schema validation failed"):
            import_weekly_bundle(self.store, SITE, invalid)

        self.assertEqual(self.store.list_topics(SITE), [])
        self.assertEqual(
            self.store.get_rollout_state(SITE)["consecutive_qualifying_runs"],
            0,
        )

    def test_declared_incomplete_success_is_recorded_degraded(self) -> None:
        incomplete = weekly_bundle(
            "manual-stop-1",
            "2026-07-19T20:15:00+09:00",
        )
        incomplete["complete"] = False
        incomplete["stop_condition"] = "MANUAL_STOP"
        incomplete["unexplored_scope"] = ["search-console"]

        report = import_weekly_bundle(self.store, SITE, incomplete)

        self.assertEqual(report["effective_status"], "DEGRADED")
        self.assertEqual(report["rollout"]["mode"], "DEGRADED")
        self.assertEqual(
            report["rollout"]["consecutive_qualifying_runs"],
            0,
        )

    def test_invalid_public_json_provenance_fails_without_partial_mutation(self) -> None:
        bundle = weekly_bundle("invalid", "2026-07-19T20:15:00+09:00")
        bundle["questions"][0].pop("verified_by_codex")
        bundle["questions"][0]["verification_method"] = "reddit_public_json"
        bundle["questions"][0]["verified_at"] = bundle["ended_at"]
        bundle["questions"][0]["verified_by"] = "collector"

        with self.assertRaisesRegex(ValueError, "Invalid verified evidence provenance"):
            import_weekly_bundle(self.store, SITE, bundle)

        self.assertEqual(self.store.list_topics(SITE), [])
        self.assertEqual(self.store.list_questions(SITE), [])

    def test_spoofed_first_party_query_fails_before_mutation(self) -> None:
        bundle = weekly_bundle("spoof", "2026-07-19T20:15:00+09:00")
        question = bundle["questions"][0]
        question.pop("verified_by_codex")
        question.update(
            {
                "source": "reddit_search",
                "evidence_type": "FIRST_PARTY_QUERY",
                "verification_method": "site_search_export",
                "verified_at": bundle["ended_at"],
                "verified_by": "codex",
                "property_id": SITE
            }
        )
        with self.assertRaisesRegex(ValueError, "Invalid verified evidence provenance"):
            import_weekly_bundle(self.store, SITE, bundle)
        self.assertEqual(self.store.list_topics(SITE), [])

    def test_verified_search_console_queries_need_no_public_url(self) -> None:
        bundle = weekly_bundle(
            "search-console-evidence",
            "2026-07-19T20:15:00+09:00",
        )
        for index, question in enumerate(bundle["questions"], start=1):
            question.pop("verified_by_codex")
            question.pop("url")
            question.update(
                {
                    "source": "search_console",
                    "source_item_id": f"query-receipt-{index}",
                    "evidence_type": "FIRST_PARTY_QUERY",
                    "verification_method": "search_console_api",
                    "verified_at": bundle["ended_at"],
                    "verified_by": "search-console-import",
                    "property_id": "https://koreaeasyguide.blogspot.com/",
                }
            )
        bundle["auditor"]["evidence_locator_coverage_verified"] = True
        bundle["auditor"].pop("evidence_url_coverage_verified")

        report = import_weekly_bundle(self.store, SITE, bundle)

        self.assertEqual(report["topics_ready"], 1)
        details = report["rollout"]["recent_runs"][-1]["details"]
        self.assertEqual(details["ready_evidence_locator_coverage"], 1.0)
        self.assertEqual(details["verified_questions"], 2)

    def test_single_question_requires_a_structured_high_confidence_exception(self) -> None:
        bundle = weekly_bundle("single-review", "2026-07-19T20:15:00+09:00")
        bundle["questions"] = bundle["questions"][:1]
        bundle["clusters"][0]["question_ids"] = ["q-one"]
        bundle["topics"][0]["question_ids"] = ["q-one"]
        bundle["topics"][0]["status"] = "REVIEW"
        bundle["topics"][0]["severity_score"] = 12
        bundle["topics"][0]["severity_reason"] = (
            "A failed late-night transfer can strand a traveler."
        )

        import_weekly_bundle(self.store, SITE, bundle)
        review = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(review)
        assert review is not None
        approved = self.store.approve_evidence_exception(
            SITE,
            review.topic_id,
            approved_by="owner@example.com",
            approved_at="2026-07-19T20:30:00+09:00",
            reason=(
                "The official outage notice and concentrated engagement make "
                "this urgent."
            ),
            basis="OFFICIAL_ISSUE",
            decision_id="decision-single-1",
            expected_revision=review.revision,
        )
        ready_bundle = weekly_bundle(
            "single-exception",
            "2026-07-26T20:15:00+09:00",
        )
        ready_bundle["questions"] = ready_bundle["questions"][:1]
        ready_bundle["clusters"][0]["question_ids"] = ["q-one"]
        ready_bundle["topics"][0]["question_ids"] = ["q-one"]
        ready_bundle["topics"][0]["severity_score"] = 12
        ready_bundle["topics"][0]["severity_reason"] = (
            "A failed late-night transfer can strand a traveler."
        )
        report = import_weekly_bundle(self.store, SITE, ready_bundle)

        self.assertEqual(report["topics_ready"], 1)
        topic = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(topic)
        assert topic is not None
        self.assertEqual(topic.status, TopicStatus.READY)
        self.assertEqual(topic.evidence_exception["basis"], "OFFICIAL_ISSUE")
        self.assertEqual(
            topic.evidence_exception["approval_source"],
            "USER_DECISION",
        )
        self.assertGreater(topic.revision, approved.revision)
        self.assertEqual(topic.priority_components["severity"], 12)

    def test_research_bundle_cannot_self_approve_single_question_exception(self) -> None:
        bundle = weekly_bundle("self-approved", "2026-07-19T20:15:00+09:00")
        bundle["questions"] = bundle["questions"][:1]
        bundle["clusters"][0]["question_ids"] = ["q-one"]
        bundle["topics"][0]["question_ids"] = ["q-one"]
        bundle["topics"][0]["evidence_exception"] = {
            "approved_by": "codex",
            "approved_at": "2026-07-19T20:10:00+09:00",
            "reason": "The automation attempted to approve itself.",
            "basis": "OFFICIAL_ISSUE",
            "approval_source": "USER_DECISION",
            "decision_id": "invented-by-automation",
        }

        report = import_weekly_bundle(self.store, SITE, bundle)

        self.assertEqual(report["topics_ready"], 0)
        self.assertTrue(report["untrusted_evidence_exceptions"])
        topic = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(topic)
        assert topic is not None
        self.assertEqual(topic.status, TopicStatus.REVIEW)
        self.assertEqual(topic.evidence_exception, {})

    def test_severity_input_is_bounded_and_requires_a_reason(self) -> None:
        too_high = weekly_bundle("severity-high", "2026-07-19T20:15:00+09:00")
        too_high["topics"][0]["severity_score"] = 16
        too_high["topics"][0]["severity_reason"] = "Out of range."
        with self.assertRaisesRegex(ValueError, "weekly schema validation failed"):
            import_weekly_bundle(self.store, SITE, too_high)

        missing_reason = weekly_bundle(
            "severity-no-reason",
            "2026-07-19T20:15:00+09:00",
        )
        missing_reason["topics"][0]["severity_score"] = 10
        with self.assertRaisesRegex(ValueError, "weekly schema validation failed"):
            import_weekly_bundle(self.store, SITE, missing_reason)
        self.assertEqual(self.store.list_topics(SITE), [])

    def test_watch_and_reject_imports_preserve_lifecycle_status(self) -> None:
        watch = weekly_bundle(
            "watch-status",
            "2026-07-19T20:15:00+09:00",
        )
        watch["topics"][0]["action"] = "WATCH"
        watch["topics"][0]["status"] = "HOLD"
        import_weekly_bundle(self.store, SITE, watch)
        held = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(held)
        assert held is not None
        self.assertEqual(held.status, TopicStatus.HOLD)

        reject = weekly_bundle(
            "reject-status",
            "2026-07-26T20:15:00+09:00",
        )
        reject["topics"][0]["action"] = "REJECT"
        reject["topics"][0]["status"] = "REJECTED"
        import_weekly_bundle(self.store, SITE, reject)
        rejected = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(rejected)
        assert rejected is not None
        self.assertEqual(rejected.status, TopicStatus.REJECTED)

    def test_markerless_blogger_title_blocks_semantic_duplicate_server_side(self) -> None:
        sync_blogger_snapshot(
            self.store,
            SITE,
            {
                "fetched_at": "2026-07-19T19:00:00+09:00",
                "complete_snapshot": False,
                "posts": [
                    {
                        "id": "external-duplicate-1",
                        "url": "https://example.blogspot.com/existing-guide.html",
                        "title": "What to Do When an Airport Transfer Fails",
                        "status": "LIVE",
                        "content": "<article><p>No topic marker.</p></article>",
                    }
                ],
            },
        )
        bundle = weekly_bundle(
            "semantic-duplicate",
            "2026-07-19T20:15:00+09:00",
        )
        # The submitted counters/auditor claim no duplicate; the Registry must
        # still derive the conflict from the synced Blogger title.
        bundle["blogger_duplicate_count"] = 0
        bundle["auditor"]["blogger_duplicates_verified"] = True

        report = import_weekly_bundle(self.store, SITE, bundle)

        self.assertEqual(report["effective_status"], "DEGRADED")
        self.assertEqual(report["topics_ready"], 0)
        self.assertTrue(report["ready_rejected"])
        details = report["rollout"]["recent_runs"][-1]["details"]
        self.assertGreater(details["semantic_blogger_duplicate_count"], 0)
        self.assertIn(
            "blogger:post:external-duplicate-1",
            details["semantic_blogger_duplicate_ids"]["topic-airport-transfer"],
        )
        catalog = self.store._load_registry(SITE)["blogger_catalog"]
        self.assertNotIn("content", catalog["post:external-duplicate-1"])

    def test_later_blogger_sync_holds_previously_ready_semantic_duplicate(self) -> None:
        bundle = weekly_bundle(
            "ready-before-sync",
            "2026-07-19T20:15:00+09:00",
        )
        import_weekly_bundle(self.store, SITE, bundle)
        before = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(before)
        assert before is not None
        self.assertEqual(before.status, TopicStatus.READY)

        report = sync_blogger_snapshot(
            self.store,
            SITE,
            {
                "fetched_at": "2026-07-19T21:00:00+09:00",
                "complete_snapshot": False,
                "posts": [
                    {
                        "id": "late-duplicate",
                        "url": "https://example.blogspot.com/late-duplicate.html",
                        "title": "What to do when airport transfer fails",
                        "status": "LIVE",
                    }
                ],
            },
        )

        self.assertEqual(
            report["held_semantic_duplicate_topic_ids"],
            ["topic-airport-transfer"],
        )
        after = self.store.get_topic(SITE, "topic-airport-transfer")
        self.assertIsNotNone(after)
        assert after is not None
        self.assertEqual(after.status, TopicStatus.HOLD)

    def test_blogger_reconciliation_preserves_historical_posts_without_republish(self) -> None:
        self.store.ensure_site(SITE, default_categories(SITE))
        topic = self.store.create_topic(
            SITE,
            "How to Buy KTX Tickets in Korea as a Foreigner",
            default_category_id(SITE, "Transportation"),
        )
        fetched_at = "2026-07-29T05:56:12+00:00"
        primary = PublicationRef(
            blogger_post_id="newer-primary",
            url="https://example.blogspot.com/2026/07/ktx-tickets.html",
            title=topic.canonical_title,
            status="LIVE",
            published_at="2026-07-02T17:09:05-07:00",
            last_verified_at=fetched_at,
        )
        self.store.record_publication(SITE, topic.topic_id, primary)
        snapshot = {
            "fetched_at": fetched_at,
            "complete_snapshot": True,
            "posts": [
                {
                    "id": "older-historical",
                    "url": "https://example.blogspot.com/2026/06/ktx-tickets.html",
                    "title": topic.canonical_title,
                    "status": "LIVE",
                    "published": "2026-06-23T23:38:56-07:00",
                },
                primary.to_dict(),
            ],
        }

        report = sync_blogger_snapshot(self.store, SITE, snapshot)
        current = self.store.get_topic(SITE, topic.topic_id)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(report["matched"], 2)
        self.assertEqual(
            {
                publication.blogger_post_id
                for publication in current.publications
            },
            {"older-historical", "newer-primary"},
        )
        self.assertEqual(
            [
                publication.blogger_post_id
                for publication in current.publications
                if publication.primary
            ],
            ["newer-primary"],
        )
        self.assertEqual(
            self.store.publication_owner(
                SITE,
                blogger_post_id="older-historical",
            ),
            topic.topic_id,
        )

        registry_revision = self.store._load_registry(SITE)["revision"]
        topic_revision = current.revision
        repeated = sync_blogger_snapshot(self.store, SITE, snapshot)
        repeated_topic = self.store.get_topic(SITE, topic.topic_id)
        self.assertEqual(repeated["conflicts"], [])
        self.assertEqual(repeated_topic.revision, topic_revision)
        self.assertEqual(
            self.store._load_registry(SITE)["revision"],
            registry_revision,
        )

        with self.assertRaisesRegex(
            ValueError,
            "different primary publication",
        ):
            self.store.record_publication(
                SITE,
                topic.topic_id,
                PublicationRef(
                    blogger_post_id="new-insert",
                    url="https://example.blogspot.com/2026/08/ktx-tickets.html",
                    status="LIVE",
                ),
            )

    def test_blogger_reconciliation_keeps_cross_topic_ownership_conflicts(self) -> None:
        self.store.ensure_site(SITE, default_categories(SITE))
        category_id = default_category_id(SITE, "Transportation")
        owner = self.store.create_topic(
            SITE,
            "Existing KTX guide",
            category_id,
        )
        other = self.store.create_topic(
            SITE,
            "Different airport guide",
            category_id,
        )
        self.store.record_publication(
            SITE,
            owner.topic_id,
            PublicationRef(
                blogger_post_id="owned-post",
                url="https://example.blogspot.com/owned-post.html",
                status="LIVE",
            ),
        )

        report = sync_blogger_snapshot(
            self.store,
            SITE,
            {
                "complete_snapshot": False,
                "posts": [
                    {
                        "id": "owned-post",
                        "url": "https://example.blogspot.com/owned-post.html",
                        "title": other.canonical_title,
                        "topic_id": other.topic_id,
                        "status": "LIVE",
                    }
                ],
            },
        )

        self.assertEqual(len(report["conflicts"]), 1)
        self.assertIn("already belongs", report["conflicts"][0]["error"])
        self.assertEqual(
            self.store.publication_owner(
                SITE,
                blogger_post_id="owned-post",
            ),
            owner.topic_id,
        )
        self.assertEqual(
            self.store.get_topic(SITE, other.topic_id).publications,
            [],
        )

    def test_only_authoritative_blogger_live_catalog_promotes_published(self) -> None:
        self.store.ensure_site(SITE, default_categories(SITE))
        topic = self.store.create_topic(
            SITE,
            "Authoritative catalog verification",
            default_category_id(SITE, "Transportation"),
        )
        snapshot = {
            "site": SITE,
            "fetched_at": "2026-07-29T05:56:12+00:00",
            "complete_snapshot": False,
            "posts": [
                {
                    "id": "catalog-verification-post",
                    "url": "https://example.blogspot.com/catalog.html",
                    "title": topic.canonical_title,
                    "topic_id": topic.topic_id,
                    "status": "LIVE",
                }
            ],
        }

        untrusted = sync_blogger_snapshot(self.store, SITE, snapshot)
        unverified = self.store.get_topic(SITE, topic.topic_id)
        self.assertFalse(untrusted["authoritative_live"])
        self.assertEqual(unverified.status, TopicStatus.LIVE_UNVERIFIED)
        self.assertEqual(unverified.publications[0].last_verified_at, "")

        trusted = sync_blogger_snapshot(
            self.store,
            SITE,
            {
                **snapshot,
                "source": "BLOGGER_API",
                "authoritative_live": True,
            },
        )
        published = self.store.get_topic(SITE, topic.topic_id)
        self.assertTrue(trusted["authoritative_live"])
        self.assertEqual(published.status, TopicStatus.PUBLISHED)
        self.assertEqual(
            published.publications[0].last_verified_at,
            snapshot["fetched_at"],
        )

    def test_initial_backfill_resolves_duplicate_post_id_to_strong_receipt(self) -> None:
        generated = Path(self.temp.name) / "generated"
        winner = generated / SITE / "2026-07-01" / "verified-owner"
        newer_same_topic = generated / SITE / "2026-07-03" / "verified-owner-newer"
        secondary = generated / SITE / "2026-07-02" / "copied-receipt"
        winner.mkdir(parents=True)
        newer_same_topic.mkdir(parents=True)
        secondary.mkdir(parents=True)
        (winner / "metadata.json").write_text(
            json.dumps(
                {
                    "candidate": {
                        "keyword": "unique verified owner topic",
                        "category": "Transportation",
                        "signals": [],
                    },
                    "article": {
                        "title": "Unique Verified Owner Topic",
                        "category": "Transportation",
                    },
                }
            ),
            encoding="utf-8",
        )
        (secondary / "metadata.json").write_text(
            json.dumps(
                {
                    "candidate": {
                        "keyword": "unrelated copied receipt topic",
                        "category": "Transportation",
                        "signals": [],
                    },
                    "article": {
                        "title": "Unrelated Copied Receipt Topic",
                        "category": "Transportation",
                    },
                }
            ),
            encoding="utf-8",
        )
        (newer_same_topic / "metadata.json").write_text(
            (winner / "metadata.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (winner / "blogger_publish_result.json").write_text(
            json.dumps(
                {
                    "blogger": {
                        "id": "duplicate-post-1",
                        "url": "https://example.blogspot.com/2026/07/verified-owner.html",
                        "status": "LIVE",
                        "published": "2026-07-01T12:00:00Z",
                        "updated": "2026-07-01T12:05:00Z",
                    }
                }
            ),
            encoding="utf-8",
        )
        (secondary / "blogger_publish_result.json").write_text(
            json.dumps({"blogger": {"id": "duplicate-post-1"}}),
            encoding="utf-8",
        )
        (newer_same_topic / "blogger_publish_result.json").write_text(
            json.dumps(
                {
                    "blogger": {
                        "id": "newer-post-2",
                        "url": "https://example.blogspot.com/2026/07/verified-owner-newer.html",
                        "status": "LIVE",
                        "published": "2026-07-03T12:00:00Z",
                        "updated": "2026-07-03T12:05:00Z",
                    }
                }
            ),
            encoding="utf-8",
        )

        first = backfill_local_history(
            self.store,
            SITE,
            generated_root=generated,
        )
        self.assertEqual(first["conflicts"], [])
        self.assertEqual(
            first["duplicate_publication_resolutions"][0]["resolution"],
            "SECONDARY_REVIEW",
        )
        owner = self.store.find_topic_by_text(SITE, "unique verified owner topic")
        loser = self.store.find_topic_by_text(SITE, "unrelated copied receipt topic")
        self.assertIsNotNone(owner)
        self.assertIsNotNone(loser)
        assert owner is not None
        assert loser is not None
        self.assertEqual(
            self.store.publication_owner(
                SITE,
                blogger_post_id="duplicate-post-1",
            ),
            owner.topic_id,
        )
        self.assertEqual(loser.status, TopicStatus.REVIEW)
        self.assertEqual(loser.publications, [])
        self.assertIn(owner.topic_id, loser.status_reason)
        refreshed_owner = self.store.get_topic(SITE, owner.topic_id)
        self.assertIsNotNone(refreshed_owner)
        assert refreshed_owner is not None
        self.assertEqual(len(refreshed_owner.publications), 2)
        primary = [
            publication
            for publication in refreshed_owner.publications
            if publication.primary
        ]
        self.assertEqual(
            [publication.blogger_post_id for publication in primary],
            ["newer-post-2"],
        )

        repeated = backfill_local_history(
            self.store,
            SITE,
            generated_root=generated,
        )
        self.assertEqual(repeated["conflicts"], [])
        self.assertEqual(repeated["updated_topics"], 0)


if __name__ == "__main__":
    unittest.main()
