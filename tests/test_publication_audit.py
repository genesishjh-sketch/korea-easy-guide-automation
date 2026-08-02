from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from bs4 import BeautifulSoup

from src.pipeline import stage2_publish
from src.topics.models import CategoryRecord
from src.topics.models import PublicationRef
from src.topics.models import TopicAction
from src.topics.models import TopicRecord
from src.topics.models import TopicStatus
from src.topics.store import TopicStore


SITE = "easy_pc_fix_guide"
TOPIC_ID = "topic-publication-audit"
RUN_ID = "daily-run-publication-audit"


def generated_store(root: Path, *, revision: int = 7) -> tuple[TopicStore, TopicRecord]:
    store = TopicStore(root)
    store.upsert_category(
        SITE,
        CategoryRecord(
            category_id="cat-apps",
            site=SITE,
            name="Apps & Settings",
            blogger_label="Apps & Settings",
        ),
    )
    topic = store.upsert_topic(
        SITE,
        TopicRecord(
            topic_id=TOPIC_ID,
            site=SITE,
            canonical_title="windows settings app will not open",
            category_id="cat-apps",
            cluster_id="cluster-publication-audit",
            action=TopicAction.NEW_POST,
            status=TopicStatus.GENERATED,
            revision=revision,
            claim_run_id=RUN_ID,
        ),
    )
    return store, topic


def write_article(article_dir: Path, revision: int) -> None:
    article_dir.mkdir(parents=True)
    (article_dir / "metadata.json").write_text(
        json.dumps(
            {
                "article": {
                    "title": "Settings app repair",
                    "slug": "settings-app-repair",
                    "tags": ["Apps"],
                },
                "candidate": {
                    "topic_id": TOPIC_ID,
                    "cluster_id": "cluster-publication-audit",
                    "category_id": "cat-apps",
                    "action": "NEW_POST",
                    "topic_action": "NEW_POST",
                    "revision": revision,
                    "topic_revision": revision,
                    "claim_run_id": RUN_ID,
                },
            }
        ),
        encoding="utf-8",
    )


class PublicationAuditTests(unittest.TestCase):
    def test_expired_weekly_schedule_returns_to_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TopicStore(Path(tmpdir) / "topics")
            store.upsert_category(
                SITE,
                CategoryRecord(
                    category_id="cat-apps",
                    site=SITE,
                    name="Apps & Settings",
                    blogger_label="Apps & Settings",
                ),
            )
            topic = store.upsert_topic(
                SITE,
                TopicRecord(
                    topic_id="topic-expired-schedule",
                    site=SITE,
                    canonical_title="expired weekly schedule",
                    category_id="cat-apps",
                    cluster_id="cluster-expired-schedule",
                    status=TopicStatus.SCHEDULED,
                ),
            )
            store.record_schedule_reservation(
                SITE,
                topic.topic_id,
                expected_revision=topic.revision,
                scheduled_for="2099-01-01",
                expires_at="2099-01-02T00:00:00+00:00",
                now="2099-01-01T00:00:00+00:00",
            )
            swept = store.sweep_expired_reservations(
                SITE,
                now="2099-01-03T00:00:00+00:00",
            )
            current = store.get_topic(SITE, topic.topic_id)

        self.assertEqual(swept[0]["outcome"], "READY")
        self.assertEqual(current.status, TopicStatus.READY)

    def test_new_post_rejects_a_second_distinct_primary_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, _ = generated_store(Path(tmpdir) / "topics")
            first = PublicationRef(
                blogger_post_id="post-primary",
                url="https://example.com/post-primary.html",
                status="LIVE",
            )
            store.record_publication(SITE, TOPIC_ID, first, run_id=RUN_ID)

            with self.assertRaisesRegex(
                ValueError,
                "different primary publication",
            ):
                store.record_publication(
                    SITE,
                    TOPIC_ID,
                    PublicationRef(
                        blogger_post_id="post-duplicate",
                        url="https://example.com/post-duplicate.html",
                        status="LIVE",
                    ),
                )

            self.assertEqual(
                store.publication_owner(
                    SITE,
                    blogger_post_id="post-primary",
                    url="https://example.com/post-primary.html",
                ),
                TOPIC_ID,
            )
            self.assertNotIn(
                "PUBLICATION_INDEX_STALE",
                {issue.code for issue in store.validate_site(SITE)},
            )

    def test_publish_attempt_cas_allows_only_one_concurrent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "topics"
            _, topic = generated_store(root)

            def acquire() -> dict:
                return TopicStore(root).begin_publish_attempt(
                    SITE,
                    TOPIC_ID,
                    run_id=RUN_ID,
                    expected_revision=topic.revision,
                    lease_seconds=60,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: acquire(), range(2)))

        self.assertEqual(sum(bool(item["acquired"]) for item in results), 1)
        self.assertEqual(
            len({item["attempt_id"] for item in results}),
            1,
        )

    def test_restart_cannot_reacquire_an_insert_started_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "topics"
            first_store, topic = generated_store(root)
            attempt = first_store.begin_publish_attempt(
                SITE,
                TOPIC_ID,
                run_id=RUN_ID,
                expected_revision=topic.revision,
                lease_seconds=60,
            )
            first_store.mark_publish_insert_started(
                SITE,
                TOPIC_ID,
                attempt_id=attempt["attempt_id"],
                run_id=RUN_ID,
            )
            restarted = TopicStore(root).begin_publish_attempt(
                SITE,
                TOPIC_ID,
                run_id=RUN_ID,
                expected_revision=topic.revision,
                lease_seconds=60,
            )

        self.assertFalse(restarted["acquired"])
        self.assertEqual(restarted["status"], "INSERTING")

    def test_expiry_returns_pre_insert_to_ready_but_insert_trace_to_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first_store, first_topic = generated_store(Path(tmpdir) / "pre")
            pre = first_store.begin_publish_attempt(
                SITE,
                TOPIC_ID,
                run_id=RUN_ID,
                expected_revision=first_topic.revision,
                lease_seconds=60,
                now="2099-01-01T00:00:00+00:00",
            )
            pre_sweep = first_store.sweep_expired_reservations(
                SITE,
                now="2099-01-01T00:02:00+00:00",
                legacy_claim_hours=0.0001,
            )

            second_store, second_topic = generated_store(Path(tmpdir) / "started")
            started = second_store.begin_publish_attempt(
                SITE,
                TOPIC_ID,
                run_id=RUN_ID,
                expected_revision=second_topic.revision,
                lease_seconds=60,
                now="2099-01-01T00:00:00+00:00",
            )
            second_store.mark_publish_insert_started(
                SITE,
                TOPIC_ID,
                attempt_id=started["attempt_id"],
                run_id=RUN_ID,
                now="2099-01-01T00:00:01+00:00",
            )
            started_sweep = second_store.sweep_expired_reservations(
                SITE,
                now="2099-01-01T00:02:00+00:00",
                legacy_claim_hours=0.0001,
            )
            pre_topic_status = first_store.get_topic(SITE, TOPIC_ID).status
            pre_attempt_status = first_store._load_registry(SITE)[
                "publish_attempts"
            ][TOPIC_ID]["status"]
            started_topic_status = second_store.get_topic(
                SITE,
                TOPIC_ID,
            ).status
            started_attempt_status = second_store._load_registry(SITE)[
                "publish_attempts"
            ][TOPIC_ID]["status"]

        self.assertEqual(pre_sweep[0]["outcome"], "READY")
        self.assertEqual(pre_topic_status, TopicStatus.READY)
        self.assertEqual(pre_attempt_status, "ABORTED_PRE_INSERT")
        self.assertEqual(started_sweep[0]["outcome"], "HOLD_RECONCILE")
        self.assertEqual(started_topic_status, TopicStatus.HOLD)
        self.assertEqual(started_attempt_status, "UNKNOWN")

    def test_stage2_uses_generated_revision_and_writes_one_topic_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, topic = generated_store(root / "topics")
            article_dir = root / "generated" / "article"
            write_article(article_dir, topic.revision)
            settings = SimpleNamespace(
                site_key=SITE,
                generated_output_dir=str(root / "generated"),
                blogger_publish_mode="publish",
                blogger_blog_id="blog-id",
                site_url="https://example.com",
            )
            publisher = MagicMock()
            publisher.publish.return_value = {
                "id": "post-audit",
                "url": "https://example.com/post-audit.html",
                "status": "LIVE",
            }
            with patch.object(
                stage2_publish,
                "load_settings",
                return_value=settings,
            ), patch(
                "src.topics.store.TopicStore",
                return_value=store,
            ), patch.object(
                stage2_publish,
                "load_article",
                return_value=(
                    "Settings app repair",
                    '<article><p data-topic-id="wrong">Body</p></article>',
                    ["Apps"],
                ),
            ), patch.object(
                stage2_publish,
                "validate_live_originality",
            ), patch.object(
                stage2_publish,
                "BloggerPublisher",
                return_value=publisher,
            ):
                result_path = stage2_publish.run(article_dir, "publish", SITE)

            result = json.loads(result_path.read_text(encoding="utf-8"))
            sent_html = publisher.publish.call_args.kwargs["html"]
            soup = BeautifulSoup(sent_html, "html.parser")
            markers = soup.select("[data-topic-id]")
            current = store.get_topic(SITE, TOPIC_ID)
            attempt = store._load_registry(SITE)["publish_attempts"][TOPIC_ID]

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["data-topic-id"], TOPIC_ID)
        self.assertTrue(markers[0].has_attr("hidden"))
        self.assertEqual(result["publish_attempt_id"], attempt["attempt_id"])
        self.assertEqual(attempt["topic_revision"], topic.revision)
        self.assertEqual(attempt["status"], "RECEIPT_RECORDED")
        self.assertEqual(current.status, TopicStatus.LIVE_UNVERIFIED)

    def test_local_result_write_failure_keeps_receipt_and_never_reinserts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, topic = generated_store(root / "topics")
            article_dir = root / "generated" / "article"
            write_article(article_dir, topic.revision)
            settings = SimpleNamespace(
                site_key=SITE,
                generated_output_dir=str(root / "generated"),
                blogger_publish_mode="publish",
                blogger_blog_id="blog-id",
                site_url="https://example.com",
            )
            publisher = MagicMock()
            publisher.publish.return_value = {
                "id": "post-write-failure",
                "url": "https://example.com/post-write-failure.html",
                "status": "LIVE",
            }
            common = [
                patch.object(stage2_publish, "load_settings", return_value=settings),
                patch("src.topics.store.TopicStore", return_value=store),
                patch.object(
                    stage2_publish,
                    "load_article",
                    return_value=("Settings app repair", "<article>Body</article>", ["Apps"]),
                ),
                patch.object(stage2_publish, "validate_live_originality"),
                patch.object(
                    stage2_publish,
                    "BloggerPublisher",
                    return_value=publisher,
                ),
            ]
            for selected in common:
                selected.start()
            try:
                with patch.object(
                    stage2_publish,
                    "save_publish_result",
                    side_effect=OSError("disk full"),
                ):
                    with self.assertRaises(stage2_publish.PublishReceiptPersisted):
                        stage2_publish.run(article_dir, "publish", SITE)
                retry_path = stage2_publish.run(article_dir, "publish", SITE)
            finally:
                for selected in reversed(common):
                    selected.stop()

            retry = json.loads(retry_path.read_text(encoding="utf-8"))
            registry = store._load_registry(SITE)

        publisher.publish.assert_called_once()
        self.assertTrue(retry["skipped"])
        self.assertEqual(retry["reason"], "duplicate_topic_id")
        self.assertEqual(
            registry["publish_attempts"][TOPIC_ID]["status"],
            "RECEIPT_RECORDED",
        )
        self.assertIn(
            registry["publish_attempts"][TOPIC_ID]["attempt_id"],
            registry["publication_receipts"],
        )

    def test_timeout_marks_unknown_and_blocks_restart_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, topic = generated_store(root / "topics")
            article_dir = root / "generated" / "article"
            write_article(article_dir, topic.revision)
            settings = SimpleNamespace(
                site_key=SITE,
                generated_output_dir=str(root / "generated"),
                blogger_publish_mode="publish",
                blogger_blog_id="blog-id",
                site_url="https://example.com",
            )
            publisher = MagicMock()
            publisher.publish.side_effect = TimeoutError("response lost")
            with patch.object(
                stage2_publish,
                "load_settings",
                return_value=settings,
            ), patch(
                "src.topics.store.TopicStore",
                return_value=store,
            ), patch.object(
                stage2_publish,
                "load_article",
                return_value=("Settings app repair", "<article>Body</article>", ["Apps"]),
            ), patch.object(
                stage2_publish,
                "validate_live_originality",
            ), patch.object(
                stage2_publish,
                "BloggerPublisher",
                return_value=publisher,
            ):
                with self.assertRaises(stage2_publish.BloggerOutcomeUnknown):
                    stage2_publish.run(article_dir, "publish", SITE)
                with self.assertRaises(ValueError):
                    stage2_publish.run(article_dir, "publish", SITE)

            current = store.get_topic(SITE, TOPIC_ID)
            attempt = store._load_registry(SITE)["publish_attempts"][TOPIC_ID]

        publisher.publish.assert_called_once()
        self.assertEqual(current.status, TopicStatus.HOLD)
        self.assertEqual(attempt["status"], "UNKNOWN")

    def test_topic_revision_parser_fails_closed(self) -> None:
        for invalid in (None, 0, -1, True, 1.5, "1.5", ""):
            with self.subTest(revision=invalid):
                with self.assertRaises(ValueError):
                    stage2_publish.parse_topic_revision({"revision": invalid})
        self.assertEqual(
            stage2_publish.parse_topic_revision({"revision": "9"}),
            9,
        )


if __name__ == "__main__":
    unittest.main()
