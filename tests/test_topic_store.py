from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.topics.defaults import default_categories
from src.topics.models import EvidenceType
from src.topics.models import PublicationRef
from src.topics.models import QuestionRecord
from src.topics.models import TopicAction
from src.topics.models import TopicStatus
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


class TopicStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.store.ensure_site(SITE, default_categories(SITE))
        self.category_id = default_categories(SITE)[0].category_id
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

    def question(
        self,
        suffix: str,
        *,
        method: str = "verified_by_codex",
        url: str | None = None,
    ) -> QuestionRecord:
        return QuestionRecord(
            question_id=f"q-{suffix}",
            site=SITE,
            source="reddit",
            source_item_id=f"source-{suffix}",
            url=url or f"https://www.reddit.com/r/koreatravel/comments/{suffix}/question",
            title=f"Question {suffix}",
            summary="A safely retained short summary.",
            evidence_type=EvidenceType.OBSERVED_QUESTION,
            verification_method=method,
            verified_at="2026-07-26T20:00:00+09:00",
            verified_by="codex",
        )

    def test_question_drops_raw_body_and_public_json_is_not_evidence(self) -> None:
        question = QuestionRecord.from_dict(
            {
                "site": SITE,
                "source": "reddit",
                "source_id": "abc",
                "url": "https://www.reddit.com/r/koreatravel/comments/abc/x",
                "title": "Question",
                "body": "must not persist",
                "selftext": "must not persist either",
                "summary": "safe summary",
                "evidence_type": "OBSERVED_QUESTION",
                "verification_method": "reddit_public_json",
                "verified_at": "2026-07-26T20:00:00+09:00",
                "verified_by": "codex",
            }
        )

        self.assertFalse(question.eligible_evidence)
        self.assertNotIn("body", question.to_dict())
        self.assertNotIn("selftext", question.to_dict())

    def test_observed_question_requires_an_explicit_source_host_adapter(self) -> None:
        common = {
            "site": SITE,
            "source_id": "observed-1",
            "title": "Observed question",
            "evidence_type": "OBSERVED_QUESTION",
            "verification_method": "browser_verified",
            "verified_at": "2026-07-26T20:00:00+09:00",
            "verified_by": "codex",
        }
        for source, url in (
            ("community", "https://random-community.example/questions/1"),
            ("forum", "https://superuser.com/questions/1/example"),
            ("reddit", "https://attacker.example/questions/1"),
            ("quora", "https://example.com/questions/1"),
        ):
            with self.subTest(source=source, url=url):
                question = QuestionRecord.from_dict(
                    {**common, "source": source, "url": url}
                )
                self.assertFalse(question.eligible_evidence)

        stack_exchange = QuestionRecord.from_dict(
            {
                **common,
                "source": "stack_exchange",
                "url": "https://superuser.com/questions/1/example",
            }
        )
        self.assertTrue(stack_exchange.eligible_evidence)

    def test_ready_needs_two_independent_records_and_a_verified_url(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "How to solve one specific travel problem",
            self.category_id,
            status=TopicStatus.REVIEW,
            official_source_urls=["https://english.visitkorea.or.kr/"],
            official_source_refs=[
                {
                    "url": "https://english.visitkorea.or.kr/",
                    "authority_type": "GOVERNMENT",
                }
            ],
            official_answerable=True,
            auditor_decision="PASS",
            audited_at="2026-07-26T20:00:00+09:00",
            editor_brief="Give a bounded official recovery guide.",
            reader_questions=["How can the reader recover safely?"],
            difference_from_existing="No current post covers this exact problem.",
        )
        first = self.store.upsert_question(SITE, self.question("one"))
        self.store.link_question(SITE, first.question_id, topic.topic_id)
        topic = self.store.recalculate_priority(SITE, topic.topic_id)
        with self.assertRaisesRegex(ValueError, "READY gate failed"):
            self.store.mark_topic_status(
                SITE,
                topic.topic_id,
                TopicStatus.READY,
            )

        second = self.store.upsert_question(SITE, self.question("two"))
        self.store.link_question(SITE, second.question_id, topic.topic_id)
        topic = self.store.recalculate_priority(SITE, topic.topic_id)
        ready = self.store.mark_topic_status(
            SITE,
            topic.topic_id,
            TopicStatus.READY,
        )
        self.assertEqual(ready.status, TopicStatus.READY)

    def test_priority_uses_six_bounded_axes_only_for_publish_candidates(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "A recurring high-confidence travel problem",
            self.category_id,
            status=TopicStatus.REVIEW,
            official_source_refs=[
                {
                    "url": "https://english.visitkorea.or.kr/",
                    "authority_type": "GOVERNMENT",
                }
            ],
            official_answerable=True,
            auditor_decision="PASS",
            audited_at="2026-07-26T20:00:00+09:00",
            editor_brief="Give a bounded official recovery guide.",
            reader_questions=["How can the reader recover safely?"],
            difference_from_existing="No current post covers this exact problem.",
            severity_score=12,
            severity_reason="Failure strands a traveler after the last train.",
        )
        for suffix in ("priority-one", "priority-two"):
            question = self.question(suffix)
            question.engagement = {"comments": 8}
            saved = self.store.upsert_question(SITE, question)
            self.store.link_question(SITE, saved.question_id, topic.topic_id)
        scored = self.store.recalculate_priority(SITE, topic.topic_id)
        expected_keys = {
            "evidence_strength",
            "recurrence",
            "content_gap",
            "severity",
            "answerability",
            "recency",
        }
        self.assertEqual(set(scored.priority_components), expected_keys)
        self.assertEqual(
            scored.priority_score,
            round(sum(scored.priority_components.values()), 2),
        )
        self.assertLessEqual(scored.priority_components["evidence_strength"], 25)
        self.assertLessEqual(scored.priority_components["recurrence"], 20)
        self.assertLessEqual(scored.priority_components["content_gap"], 20)
        self.assertLessEqual(scored.priority_components["severity"], 15)
        self.assertEqual(scored.priority_components["severity"], 12)
        self.assertLessEqual(scored.priority_components["answerability"], 10)
        self.assertLessEqual(scored.priority_components["recency"], 10)

        watch = self.store.create_topic(
            SITE,
            "A topic that is explicitly watch-only",
            self.category_id,
            status=TopicStatus.REVIEW,
            action=TopicAction.WATCH,
        )
        watch = self.store.recalculate_priority(SITE, watch.topic_id)
        self.assertEqual(watch.priority_score, 0)
        self.assertTrue(
            all(value == 0 for value in watch.priority_components.values())
        )

        old_topic = self.store.create_topic(
            SITE,
            "An old question collected again today",
            self.category_id,
            status=TopicStatus.REVIEW,
        )
        old_question = self.question("old-post")
        old_question.created_at = "2024-01-01T00:00:00+00:00"
        old_question.collected_at = "2026-07-29T12:00:00+09:00"
        old_question = self.store.upsert_question(SITE, old_question)
        self.store.link_question(SITE, old_question.question_id, old_topic.topic_id)
        old_topic = self.store.recalculate_priority(SITE, old_topic.topic_id)
        self.assertEqual(old_topic.priority_components["recency"], 0)

    def test_schedule_claim_release_and_publication_verification_lifecycle(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Airport transfer failure recovery",
            self.category_id,
            status=TopicStatus.REVIEW,
            official_source_urls=["https://english.visitkorea.or.kr/"],
            official_source_refs=[
                {
                    "url": "https://english.visitkorea.or.kr/",
                    "authority_type": "GOVERNMENT",
                }
            ],
            official_answerable=True,
            auditor_decision="PASS",
            audited_at="2026-07-26T20:00:00+09:00",
            editor_brief="Give a bounded official recovery guide.",
            reader_questions=["How can the reader recover safely?"],
            difference_from_existing="No current post covers this exact problem.",
        )
        for suffix in ("a", "b"):
            question = self.store.upsert_question(SITE, self.question(suffix))
            self.store.link_question(SITE, question.question_id, topic.topic_id)
        topic = self.store.recalculate_priority(SITE, topic.topic_id)
        topic = self.store.mark_topic_status(SITE, topic.topic_id, TopicStatus.READY)
        details = {
            "complete": True,
            "schema_valid": True,
            "ready_evidence_url_coverage": 1.0,
            "synthetic_influence_count": 0,
            "blogger_duplicate_count": 0,
            "auditor_passed": True,
            "source_count": 1,
            "run_type": "WEEKLY_RESEARCH",
        }
        self.store.record_rollout_run(
            SITE,
            "sunday-1",
            "SUCCESS",
            run_at="2026-07-19T20:00:00+09:00",
            details=details,
        )
        self.store.record_rollout_run(
            SITE,
            "sunday-2",
            "SUCCESS",
            run_at="2026-07-26T20:00:00+09:00",
            details=details,
        )
        scheduled = self.store.mark_topic_status(
            SITE,
            topic.topic_id,
            TopicStatus.SCHEDULED,
            expected_revision=topic.revision,
        )
        claimed = self.store.claim_topic(
            SITE,
            topic.topic_id,
            "publish-run",
            expected_revision=scheduled.revision,
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertGreater(claimed.revision, scheduled.revision)
        self.assertIsNone(
            self.store.claim_topic(SITE, topic.topic_id, "other-run")
        )
        generated = self.store.mark_topic_status(
            SITE,
            topic.topic_id,
            TopicStatus.GENERATED,
            run_id="publish-run",
        )
        released = self.store.release_claim(
            SITE,
            topic.topic_id,
            "publish-run",
            TopicStatus.READY,
        )
        self.assertEqual(generated.claim_run_id, "publish-run")
        self.assertEqual(released.status, TopicStatus.READY)

        claimed = self.store.claim_topic(SITE, topic.topic_id, "publish-run-2")
        assert claimed is not None
        generated = self.store.mark_topic_status(
            SITE,
            topic.topic_id,
            TopicStatus.GENERATED,
            run_id="publish-run-2",
        )
        unverified = self.store.record_publication(
            SITE,
            topic.topic_id,
            PublicationRef(
                blogger_post_id="123",
                url="https://example.blogspot.com/2026/07/post.html",
                status="LIVE",
            ),
            expected_revision=generated.revision,
            run_id="publish-run-2",
        )
        self.assertEqual(unverified.status, TopicStatus.LIVE_UNVERIFIED)
        verified = self.store.verify_publication(
            SITE,
            topic.topic_id,
            blogger_post_id="123",
        )
        self.assertEqual(verified.status, TopicStatus.PUBLISHED)

    def test_expire_stale_scheduled(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Old scheduled item",
            self.category_id,
            status=TopicStatus.SCHEDULED,
        )
        now = datetime.now(tz=timezone.utc) + timedelta(hours=72)
        expired = self.store.expire_stale_scheduled(
            SITE,
            48,
            now=now.isoformat(),
        )
        self.assertEqual([item.topic_id for item in expired], [topic.topic_id])
        self.assertEqual(
            self.store.get_topic(SITE, topic.topic_id).status,
            TopicStatus.STALE,
        )

    def test_rollout_streak_ignores_backfill_and_resets_on_weekly_miss(self) -> None:
        good = {
            "run_type": "WEEKLY_RESEARCH",
            "complete": True,
            "schema_valid": True,
            "ready_evidence_url_coverage": 1.0,
            "synthetic_influence_count": 0,
            "blogger_duplicate_count": 0,
            "auditor_passed": True,
            "source_count": 1,
        }
        first = self.store.record_rollout_run(
            SITE,
            "weekly-good-1",
            "SUCCESS",
            run_at="2026-07-19T20:00:00+09:00",
            details=good,
        )
        self.assertEqual(first["consecutive_qualifying_runs"], 1)
        backfill = self.store.record_rollout_run(
            SITE,
            "backfill-degraded",
            "DEGRADED",
            run_at="2026-07-20T12:00:00+09:00",
            details={**good, "run_type": "BACKFILL_RESEARCH"},
        )
        self.assertEqual(backfill["mode"], "SHADOW")
        self.assertEqual(backfill["consecutive_qualifying_runs"], 1)
        self.assertEqual(backfill["last_run_id"], "weekly-good-1")
        self.assertEqual(backfill["last_status"], "SUCCESS")

        missed = self.store.record_rollout_run(
            SITE,
            "weekly-missed",
            "SUCCESS",
            run_at="2026-07-26T20:00:00+09:00",
            details={**good, "auditor_passed": False},
        )
        self.assertEqual(missed["mode"], "SHADOW")
        self.assertEqual(missed["consecutive_qualifying_runs"], 0)

        self.store.record_rollout_run(
            SITE,
            "weekly-good-2",
            "SUCCESS",
            run_at="2026-08-02T20:00:00+09:00",
            details=good,
        )
        promoted = self.store.record_rollout_run(
            SITE,
            "weekly-good-3",
            "SUCCESS",
            run_at="2026-08-09T20:00:00+09:00",
            details=good,
        )
        self.assertEqual(promoted["mode"], "READY_FIRST")
        self.assertTrue(promoted["promoted"])
        after_promotion_miss = self.store.record_rollout_run(
            SITE,
            "weekly-missed-after-promotion",
            "SUCCESS",
            run_at="2026-08-16T20:00:00+09:00",
            details={**good, "blogger_duplicate_count": 1},
        )
        self.assertEqual(after_promotion_miss["mode"], "DEGRADED")
        recovered = self.store.record_rollout_run(
            SITE,
            "weekly-recovered",
            "SUCCESS",
            run_at="2026-08-23T20:00:00+09:00",
            details=good,
        )
        self.assertEqual(recovered["mode"], "READY_FIRST")

    def test_same_kst_iso_week_cannot_count_twice(self) -> None:
        details = {
            "run_type": "WEEKLY_RESEARCH",
            "complete": True,
            "schema_valid": True,
            "ready_evidence_locator_coverage": 1.0,
            "synthetic_influence_count": 0,
            "blogger_duplicate_count": 0,
            "auditor_passed": True,
            "source_count": 1,
        }
        self.store.record_rollout_run(
            SITE,
            "same-week-first",
            "SUCCESS",
            run_at="2026-07-19T20:00:00+09:00",
            details=details,
        )
        repeated = self.store.record_rollout_run(
            SITE,
            "same-week-second",
            "SUCCESS",
            run_at="2026-07-19T20:30:00+09:00",
            details=details,
        )

        self.assertEqual(repeated["consecutive_qualifying_runs"], 1)
        self.assertFalse(repeated["recent_runs"][-1]["qualifying"])
        self.assertIn(
            "same or older",
            repeated["recent_runs"][-1]["details"]["qualification_reason"],
        )

    def test_weekly_run_cannot_qualify_before_backfill_completion(self) -> None:
        fresh_store = TopicStore(Path(self.temp.name) / "fresh-topics")
        fresh_store.ensure_site(SITE, default_categories(SITE))
        state = fresh_store.record_rollout_run(
            SITE,
            "weekly-before-backfill",
            "SUCCESS",
            run_at="2026-07-19T20:00:00+09:00",
            details={
                "run_type": "WEEKLY_RESEARCH",
                "complete": True,
                "schema_valid": True,
                "ready_evidence_locator_coverage": 1.0,
                "synthetic_influence_count": 0,
                "blogger_duplicate_count": 0,
                "auditor_passed": True,
                "source_count": 1,
            },
        )

        self.assertEqual(state["mode"], "SHADOW")
        self.assertEqual(state["consecutive_qualifying_runs"], 0)
        self.assertFalse(state["recent_runs"][-1]["qualifying"])

    def test_automated_actor_cannot_approve_evidence_exception(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Single signal review topic",
            self.category_id,
            status=TopicStatus.REVIEW,
        )

        with self.assertRaisesRegex(ValueError, "automated actors"):
            self.store.approve_evidence_exception(
                SITE,
                topic.topic_id,
                approved_by="codex-auditor",
                reason="Automation must not approve itself.",
                basis="OFFICIAL_ISSUE",
                decision_id="invented",
                expected_revision=topic.revision,
            )

    def test_reddit_url_cannot_be_used_as_official_answerability_source(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "Community-only answer",
            self.category_id,
            status=TopicStatus.REVIEW,
            official_source_refs=[
                {
                    "url": "https://www.reddit.com/r/koreatravel/comments/x/y",
                    "authority_type": "PLATFORM",
                }
            ],
            official_answerable=True,
            auditor_decision="PASS",
            audited_at="2026-07-26T20:00:00+09:00",
        )
        for suffix in ("official-a", "official-b"):
            question = self.store.upsert_question(SITE, self.question(suffix))
            self.store.link_question(SITE, question.question_id, topic.topic_id)
        topic = self.store.recalculate_priority(SITE, topic.topic_id)
        with self.assertRaisesRegex(ValueError, "trusted host"):
            self.store.mark_topic_status(
                SITE,
                topic.topic_id,
                TopicStatus.READY,
            )

    def test_official_authority_requires_matching_configured_host(self) -> None:
        topic = self.store.create_topic(
            SITE,
            "An answer that cites a self-declared vendor",
            self.category_id,
            status=TopicStatus.REVIEW,
            official_source_refs=[
                {
                    "url": "https://attacker.example/official-looking-page",
                    "authority_type": "VENDOR",
                }
            ],
            official_answerable=True,
            auditor_decision="PASS",
            audited_at="2026-07-26T20:00:00+09:00",
            editor_brief="Give a bounded official recovery guide.",
            reader_questions=["How can the reader recover safely?"],
            difference_from_existing="No current post covers this exact problem.",
        )
        for suffix in ("authority-a", "authority-b"):
            question = self.store.upsert_question(SITE, self.question(suffix))
            self.store.link_question(SITE, question.question_id, topic.topic_id)
        topic = self.store.recalculate_priority(SITE, topic.topic_id)
        with self.assertRaisesRegex(ValueError, "trusted host"):
            self.store.mark_topic_status(
                SITE,
                topic.topic_id,
                TopicStatus.READY,
            )

        config_path = Path(self.temp.name) / "trusted-authorities.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "global": {},
                    "sites": {
                        SITE: {
                            "VENDOR": ["attacker.example"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            "os.environ",
            {"TOPIC_BOARD_AUTHORITY_CONFIG": str(config_path)},
        ):
            ready = self.store.mark_topic_status(
                SITE,
                topic.topic_id,
                TopicStatus.READY,
            )
        self.assertEqual(ready.status, TopicStatus.READY)


if __name__ == "__main__":
    unittest.main()
