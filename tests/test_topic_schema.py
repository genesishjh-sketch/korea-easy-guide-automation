from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.store import TopicStore


class TopicSchemaTests(unittest.TestCase):
    def test_corrupt_attempt_receipt_and_reservation_fail_closed(self) -> None:
        corruptions = {
            "publish_attempts": {
                "topic-corrupt": {
                    "attempt_id": "attempt-corrupt",
                    "status": "INSERTING",
                }
            },
            "publication_receipts": {
                "attempt-corrupt": {
                    "attempt_id": "attempt-corrupt",
                    "status": "RECORDED",
                }
            },
            "topic_reservations": {
                "topic-corrupt": {
                    "kind": "CLAIM",
                    "topic_id": "topic-corrupt",
                    "run_id": "run-corrupt",
                    "started_at": "2026-07-01T00:00:00Z",
                    "expires_at": "2026-07-01T01:00:00Z",
                    "status": "INVALID",
                }
            },
        }
        for field, corrupt_value in corruptions.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "topics"
                store = TopicStore(root)
                site = "korea_easy_guide"
                store.ensure_site(site, default_categories(site))
                registry = json.loads(
                    store.registry_path(site).read_text(encoding="utf-8")
                )
                registry[field] = corrupt_value
                store.registry_path(site).write_text(
                    json.dumps(registry),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "registry schema validation failed",
                ):
                    store.list_topics(site)

    def test_corrupt_persistent_registry_fails_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "topics"
            store = TopicStore(root)
            site = "korea_easy_guide"
            store.ensure_site(site, default_categories(site))
            registry = json.loads(store.registry_path(site).read_text(encoding="utf-8"))
            registry["topics"]["bad"] = {"topic_id": "bad"}
            store.registry_path(site).write_text(
                json.dumps(registry),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "registry schema validation failed"):
                store.list_topics(site)


if __name__ == "__main__":
    unittest.main()
