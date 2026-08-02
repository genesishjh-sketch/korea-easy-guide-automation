from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from src.pipeline.stage2_publish import enqueue_local_publication_sync
from src.pipeline.stage2_publish import replay_local_publication_outbox
from src.pipeline.topic_board import _command_replay_outbox
from src.topics.defaults import default_categories
from src.topics.models import PublicationRef
from src.topics.store import TopicStore


class TopicOutboxTests(unittest.TestCase):
    def test_replay_accepts_explicit_sheet_ack_with_live_blogger_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = TopicStore(root / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(
                site,
                "Bluetooth disappeared",
                categories[0].category_id,
            )
            publication = PublicationRef(
                blogger_post_id="post-sheet-ack",
                url="https://example.blogspot.com/sheet-ack.html",
                title="Bluetooth disappeared",
                status="LIVE",
            )
            entry = store.enqueue_publication_sync(
                site,
                topic.topic_id,
                publication,
                "registry receipt pending",
            )
            publisher = MagicMock()
            publisher.list_live_posts.return_value = [
                {
                    **publication.to_dict(),
                    "id": publication.blogger_post_id,
                    "topic_id": topic.topic_id,
                }
            ]
            args = SimpleNamespace(
                root=root / "topics",
                dry_run=False,
                input=None,
                site=site,
                local_outbox=root / "does-not-exist.jsonl",
                sheet_acknowledged_outbox_id=[entry["outbox_id"]],
            )

            output = io.StringIO()
            with patch(
                "src.pipeline.topic_board.BloggerPublisher",
                return_value=publisher,
            ), patch(
                "src.pipeline.topic_board.load_settings",
                return_value=SimpleNamespace(),
            ), redirect_stdout(output):
                exit_code = _command_replay_outbox(args)

            remaining = TopicStore(root / "topics").list_publication_outbox(
                site
            )
            report = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["acknowledged"], [entry["outbox_id"]])
        self.assertEqual(report["remaining"], 0)
        self.assertEqual(remaining, [])
        publisher.list_live_posts.assert_called_once_with(fetch_bodies=True)

    def test_local_fallback_outbox_is_imported_once_and_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outbox_path = root / "publication_sync_pending.jsonl"
            store = TopicStore(root / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(
                site,
                "Scanner is not detected",
                categories[0].category_id,
            )
            publication = {
                "blogger_post_id": "post-local-fallback",
                "url": "https://example.blogspot.com/local-fallback.html",
                "status": "LIVE",
            }

            with patch.dict(
                "os.environ",
                {"TOPIC_PUBLICATION_OUTBOX": str(outbox_path)},
            ):
                first = enqueue_local_publication_sync(
                    site,
                    topic.topic_id,
                    publication,
                    error="registry temporarily unavailable",
                )
                second = enqueue_local_publication_sync(
                    site,
                    topic.topic_id,
                    publication,
                    error="same retry",
                )

            self.assertTrue(first["durable"])
            self.assertTrue(second["durable"])
            self.assertEqual(
                len(
                    [
                        json.loads(line)
                        for line in outbox_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                    ]
                ),
                1,
            )

            report = replay_local_publication_outbox(
                store,
                site,
                path=outbox_path,
            )
            replayed = replay_local_publication_outbox(
                store,
                site,
                path=outbox_path,
            )
            registry_entries = store.list_publication_outbox(site)

        self.assertEqual(report["imported"], 1)
        self.assertEqual(report["remaining"], 0)
        self.assertEqual(replayed["imported"], 0)
        self.assertEqual(len(registry_entries), 1)
        self.assertEqual(
            registry_entries[0]["stages"]["blogger"],
            "SUCCESS",
        )

    def test_outbox_ack_requires_all_three_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(site, "Printer issue", categories[0].category_id)
            publication = PublicationRef(
                blogger_post_id="post-1",
                url="https://example.blogspot.com/post.html",
                status="LIVE",
            )
            entry = store.enqueue_publication_sync(
                site,
                topic.topic_id,
                publication,
                "network timeout",
            )
            with self.assertRaisesRegex(ValueError, "Blogger, Registry, and Sheet"):
                store.acknowledge_publication_sync(site, entry["outbox_id"])
            for stage in ("blogger", "registry", "sheet"):
                store.mark_publication_outbox_stage(
                    site,
                    entry["outbox_id"],
                    stage,
                    success=True,
                )
            self.assertTrue(
                store.acknowledge_publication_sync(site, entry["outbox_id"])
            )
            self.assertEqual(store.list_publication_outbox(site), [])


if __name__ == "__main__":
    unittest.main()
