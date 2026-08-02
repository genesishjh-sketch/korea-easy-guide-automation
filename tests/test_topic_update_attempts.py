from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.topics.models import CategoryRecord
from src.topics.models import PublicationRef
from src.topics.models import TopicAction
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.store import TopicStore


SITE = "easy_pc_fix_guide"
CATEGORY_ID = "cat-update-attempts"
RUN_ID = "maintenance-run"
TOPIC_ID = "topic-update-attempt"
POST_ID = "blogger-post-1"
POST_URL = "https://example.com/existing-post.html"


def make_store(
    root: Path,
    *,
    topic_id: str = TOPIC_ID,
    action: TopicAction = TopicAction.UPDATE_EXISTING,
    status: TopicStatus = TopicStatus.CLAIMED,
    claim_run_id: str = RUN_ID,
    publication: PublicationRef | None = None,
) -> tuple[TopicStore, TopicRecord]:
    store = TopicStore(root)
    store.upsert_category(
        SITE,
        CategoryRecord(
            category_id=CATEGORY_ID,
            site=SITE,
            name="Maintenance",
            blogger_label="Maintenance",
        ),
    )
    topic = store.upsert_topic(
        SITE,
        TopicRecord(
            topic_id=topic_id,
            site=SITE,
            canonical_title=f"Repair guidance for {topic_id}",
            category_id=CATEGORY_ID,
            cluster_id=f"cluster-{topic_id}",
            action=action,
            status=status,
            claim_run_id=claim_run_id,
            publications=(
                [
                    publication
                    or PublicationRef(
                        blogger_post_id=POST_ID,
                        url=POST_URL,
                        title="Existing post",
                        status="LIVE",
                        primary=True,
                    )
                ]
                if action in {TopicAction.UPDATE_EXISTING, TopicAction.FAQ_ADD}
                else []
            ),
        ),
    )
    return store, topic


class TopicUpdateAttemptTests(unittest.TestCase):
    def test_update_attempt_requires_primary_live_target(self) -> None:
        cases = (
            (
                PublicationRef(
                    blogger_post_id=POST_ID,
                    url=POST_URL,
                    status="LIVE",
                    primary=False,
                ),
                "primary publication",
            ),
            (
                PublicationRef(
                    blogger_post_id=POST_ID,
                    url=POST_URL,
                    status="DRAFT",
                    primary=True,
                ),
                "LIVE or PUBLISHED",
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, (publication, expected_error) in enumerate(cases):
                with self.subTest(expected_error=expected_error):
                    store, topic = make_store(
                        Path(tmpdir) / str(index),
                        publication=publication,
                    )
                    with self.assertRaisesRegex(ValueError, expected_error):
                        store.begin_update_attempt(
                            SITE,
                            TOPIC_ID,
                            action=TopicAction.UPDATE_EXISTING,
                            blogger_post_id=POST_ID,
                            url=POST_URL,
                            run_id=RUN_ID,
                            expected_revision=topic.revision,
                        )

    def test_update_attempt_is_single_owner_and_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "topics"
            _, topic = make_store(root)

            def acquire() -> dict:
                return TopicStore(root).begin_update_attempt(
                    SITE,
                    TOPIC_ID,
                    action=TopicAction.UPDATE_EXISTING,
                    blogger_post_id=POST_ID,
                    url=POST_URL,
                    run_id=RUN_ID,
                    expected_revision=topic.revision,
                    lease_seconds=60,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                attempts = list(executor.map(lambda _: acquire(), range(2)))

            self.assertEqual(
                sum(bool(attempt["acquired"]) for attempt in attempts),
                1,
            )
            attempt_id = attempts[0]["attempt_id"]
            first_start = TopicStore(root).mark_update_started(
                SITE,
                TOPIC_ID,
                attempt_id=attempt_id,
                run_id=RUN_ID,
            )
            restarted_start = TopicStore(root).mark_update_started(
                SITE,
                TOPIC_ID,
                attempt_id=attempt_id,
                run_id=RUN_ID,
            )

        self.assertTrue(first_start["started"])
        self.assertFalse(restarted_start["started"])
        self.assertEqual(restarted_start["status"], "UPDATE_STARTED")

    def test_update_expiry_distinguishes_pre_update_from_unknown_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pre_store, pre_topic = make_store(Path(tmpdir) / "pre")
            pre_attempt = pre_store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id=RUN_ID,
                expected_revision=pre_topic.revision,
                lease_seconds=60,
                now="2099-01-01T00:00:00+00:00",
            )
            pre_sweep = pre_store.sweep_expired_reservations(
                SITE,
                now="2099-01-01T00:02:00+00:00",
            )

            started_store, started_topic = make_store(Path(tmpdir) / "started")
            started_attempt = started_store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id=RUN_ID,
                expected_revision=started_topic.revision,
                lease_seconds=60,
                now="2099-01-01T00:00:00+00:00",
            )
            started_store.mark_update_started(
                SITE,
                TOPIC_ID,
                attempt_id=started_attempt["attempt_id"],
                run_id=RUN_ID,
                now="2099-01-01T00:00:01+00:00",
            )
            started_sweep = started_store.sweep_expired_reservations(
                SITE,
                now="2099-01-01T00:02:00+00:00",
            )
            pre_registry = pre_store._load_registry(SITE)
            started_registry = started_store._load_registry(SITE)
            pre_topic_status = pre_store.get_topic(SITE, TOPIC_ID).status
            started_topic_status = started_store.get_topic(SITE, TOPIC_ID).status

        self.assertEqual(pre_sweep[0]["outcome"], "READY")
        self.assertEqual(
            pre_registry["publish_attempts"][TOPIC_ID]["status"],
            "ABORTED_PRE_UPDATE",
        )
        self.assertEqual(pre_topic_status, TopicStatus.READY)
        self.assertEqual(started_sweep[0]["outcome"], "HOLD_RECONCILE")
        self.assertEqual(
            started_registry["publish_attempts"][TOPIC_ID]["status"],
            "UNKNOWN",
        )
        self.assertEqual(started_topic_status, TopicStatus.HOLD)
        self.assertEqual(
            pre_attempt["attempt_id"],
            started_attempt["attempt_id"],
        )

    def test_new_run_can_replace_only_a_pre_update_terminal_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, topic = make_store(Path(tmpdir) / "topics")
            first = store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id=RUN_ID,
                expected_revision=topic.revision,
                lease_seconds=60,
                now="2099-01-01T00:00:00+00:00",
            )
            store.sweep_expired_reservations(
                SITE,
                now="2099-01-01T00:02:00+00:00",
            )
            reclaimed = store.get_topic(SITE, TOPIC_ID)
            reclaimed.status = TopicStatus.CLAIMED
            reclaimed.claim_run_id = "next-maintenance-run"
            reclaimed = store.upsert_topic(
                SITE,
                reclaimed,
                expected_revision=reclaimed.revision,
            )
            second = store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id="next-maintenance-run",
                expected_revision=reclaimed.revision,
            )

        self.assertTrue(second["acquired"])
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(second["prior_attempts"][-1]["status"], "ABORTED_PRE_UPDATE")
        self.assertEqual(second["prior_attempts"][-1]["prior_attempts"], [])

    def test_durable_update_outbox_reconciles_unknown_receipt_idempotently(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "topics"
            store, topic = make_store(root)
            attempt = store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id=RUN_ID,
                expected_revision=topic.revision,
            )
            store.mark_update_started(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                run_id=RUN_ID,
            )
            receipt = PublicationRef(
                blogger_post_id=POST_ID,
                url=f"{POST_URL}?utm_source=maintenance",
                title="Updated post",
                status="LIVE",
                updated_at="2099-01-01T00:00:30+00:00",
            )
            outbox_entry = store.enqueue_update_receipt(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                publication=receipt,
                run_id=RUN_ID,
                error="Registry write failed after Blogger success",
                now="2099-01-01T00:00:31+00:00",
            )
            unknown_topic = store.get_topic(SITE, TOPIC_ID)
            unknown_registry = store._load_registry(SITE)

            reconciled = TopicStore(root).record_update_receipt(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                publication=receipt,
                expected_revision=topic.revision,
                run_id=RUN_ID,
                now="2099-01-01T00:01:00+00:00",
            )
            reconciled_revision = reconciled.revision
            repeated = TopicStore(root).record_update_receipt(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                publication=receipt,
                expected_revision=topic.revision,
                run_id=RUN_ID,
                now="2099-01-01T00:02:00+00:00",
            )
            with self.assertRaisesRegex(ValueError, "reserved target ID/URL"):
                TopicStore(root).record_update_receipt(
                    SITE,
                    TOPIC_ID,
                    attempt_id=attempt["attempt_id"],
                    publication=PublicationRef(
                        blogger_post_id=POST_ID,
                        url="https://example.com/different-url.html",
                    ),
                    expected_revision=topic.revision,
                    run_id=RUN_ID,
                )
            final_registry = store._load_registry(SITE)
            final_entry = next(
                item
                for item in final_registry["publication_outbox"]
                if item["outbox_id"] == outbox_entry["outbox_id"]
            )

        self.assertEqual(outbox_entry["update_attempt_id"], attempt["attempt_id"])
        self.assertEqual(
            outbox_entry["stages"],
            {
                "blogger": "SUCCESS",
                "registry": "PENDING",
                "sheet": "PENDING",
            },
        )
        self.assertEqual(unknown_topic.status, TopicStatus.HOLD)
        self.assertEqual(
            unknown_registry["publish_attempts"][TOPIC_ID]["status"],
            "UNKNOWN",
        )
        self.assertEqual(reconciled.status, TopicStatus.LIVE_UNVERIFIED)
        self.assertEqual(repeated.revision, reconciled_revision)
        self.assertEqual(
            final_registry["publish_attempts"][TOPIC_ID]["status"],
            "RECEIPT_RECORDED",
        )
        self.assertEqual(
            final_registry["publication_receipts"][attempt["attempt_id"]]["status"],
            "RECORDED",
        )
        self.assertEqual(final_entry["stages"]["blogger"], "SUCCESS")
        self.assertEqual(final_entry["stages"]["registry"], "SUCCESS")
        self.assertEqual(final_entry["stages"]["sheet"], "PENDING")

    def test_update_receipt_must_match_reserved_id_and_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, topic = make_store(Path(tmpdir) / "topics")
            attempt = store.begin_update_attempt(
                SITE,
                TOPIC_ID,
                action=TopicAction.UPDATE_EXISTING,
                blogger_post_id=POST_ID,
                url=POST_URL,
                run_id=RUN_ID,
                expected_revision=topic.revision,
            )
            store.mark_update_started(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                run_id=RUN_ID,
            )

            with self.assertRaisesRegex(ValueError, "reserved target ID/URL"):
                store.record_update_receipt(
                    SITE,
                    TOPIC_ID,
                    attempt_id=attempt["attempt_id"],
                    publication=PublicationRef(
                        blogger_post_id="different-post",
                        url=POST_URL,
                        status="LIVE",
                    ),
                    expected_revision=topic.revision,
                    run_id=RUN_ID,
                )
            attempt_status = store._load_registry(SITE)["publish_attempts"][
                TOPIC_ID
            ]["status"]

        self.assertEqual(attempt_status, "UPDATE_STARTED")

    def test_publication_merge_enriches_url_only_reference_without_duplicate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, topic = make_store(
                Path(tmpdir) / "topics",
                publication=PublicationRef(
                    url=POST_URL,
                    title="URL-only catalog entry",
                    status="LIVE",
                    primary=True,
                ),
            )
            merged = store.record_publication(
                SITE,
                TOPIC_ID,
                PublicationRef(
                    blogger_post_id=POST_ID,
                    url=f"{POST_URL}?utm_source=catalog",
                    title="ID-enriched catalog entry",
                    status="LIVE",
                    primary=True,
                ),
                expected_revision=topic.revision,
                run_id=RUN_ID,
            )

        self.assertEqual(len(merged.publications), 1)
        self.assertEqual(merged.publications[0].blogger_post_id, POST_ID)
        self.assertEqual(
            len([item for item in merged.publications if item.primary]),
            1,
        )
        transitive = store._merge_publication_lists(
            [
                PublicationRef(
                    url="https://example.com/old-url.html",
                    primary=True,
                )
            ],
            [
                PublicationRef(
                    blogger_post_id="same-post",
                    url="https://example.com/old-url.html",
                    primary=True,
                ),
                PublicationRef(
                    blogger_post_id="same-post",
                    url="https://example.com/new-url.html",
                    primary=True,
                ),
                PublicationRef(
                    url="https://example.com/new-url.html?utm_source=catalog",
                    primary=True,
                ),
            ],
        )
        self.assertEqual(len(transitive), 1)

    def test_new_post_validator_rejects_multiple_primary_publications(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, _ = make_store(
                Path(tmpdir) / "topics",
                action=TopicAction.NEW_POST,
                status=TopicStatus.DISCOVERED,
                claim_run_id="",
            )
            topic = store.get_topic(SITE, TOPIC_ID)
            topic.publications = [
                PublicationRef(
                    blogger_post_id="post-a",
                    url="https://example.com/a.html",
                    primary=True,
                ),
                PublicationRef(
                    blogger_post_id="post-b",
                    url="https://example.com/b.html",
                    primary=True,
                ),
            ]
            store.upsert_topic(
                SITE,
                topic,
                expected_revision=topic.revision,
            )

            issue_codes = {
                issue.code
                for issue in store.validate_site(SITE)
            }

        self.assertIn("NEW_POST_MULTIPLE_PRIMARY_PUBLICATIONS", issue_codes)

    def test_active_or_unknown_external_attempt_blocks_identity_and_merge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "topics"
            store, source = make_store(
                root,
                topic_id="source-topic",
                action=TopicAction.NEW_POST,
                status=TopicStatus.GENERATED,
                claim_run_id=RUN_ID,
            )
            _, target = make_store(
                root,
                topic_id="target-topic",
                action=TopicAction.NEW_POST,
                status=TopicStatus.DISCOVERED,
                claim_run_id="",
            )
            attempt = store.begin_publish_attempt(
                SITE,
                source.topic_id,
                run_id=RUN_ID,
                expected_revision=source.revision,
            )
            store.mark_publish_insert_started(
                SITE,
                source.topic_id,
                attempt_id=attempt["attempt_id"],
                run_id=RUN_ID,
            )
            changed = deepcopy(store.get_topic(SITE, source.topic_id))
            changed.canonical_title = "Changed while Blogger call is in flight"

            with self.assertRaisesRegex(ValueError, "external attempt"):
                store.upsert_topic(
                    SITE,
                    changed,
                    expected_revision=changed.revision,
                )
            with self.assertRaisesRegex(ValueError, "external attempt"):
                store.merge_topics(SITE, source.topic_id, target.topic_id)

            store.mark_publish_attempt_unknown(
                SITE,
                source.topic_id,
                attempt_id=attempt["attempt_id"],
                run_id=RUN_ID,
                error="timeout",
            )
            with self.assertRaisesRegex(ValueError, "external attempt"):
                store.merge_topics(SITE, source.topic_id, target.topic_id)


if __name__ == "__main__":
    unittest.main()
