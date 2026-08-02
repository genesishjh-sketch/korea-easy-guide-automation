from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.decisions import apply_sheet_decisions
from src.topics.defaults import default_categories
from src.topics.models import PublicationRef
from src.topics.models import TopicStatus
from src.topics.store import TopicStore


class TopicDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.site = "korea_easy_guide"
        categories = default_categories(self.site)
        self.store.ensure_site(self.site, categories)
        self.topic = self.store.create_topic(
            self.site,
            "Reviewable topic",
            categories[0].category_id,
            status=TopicStatus.REVIEW,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def bundle(self, decision: dict) -> dict:
        return {
            "schema_version": 1,
            "site": self.site,
            "decisions": [decision],
        }

    def test_stale_or_formula_decision_has_zero_changes(self) -> None:
        revision = self.topic.revision
        with self.assertRaises(ValueError):
            apply_sheet_decisions(
                self.store,
                self.bundle(
                    {
                        "topic_id": self.topic.topic_id,
                        "expected_revision": revision + 1,
                        "decision": "HOLD",
                        "reason": "review",
                    }
                ),
            )
        self.assertEqual(self.store.get_topic(self.site, self.topic.topic_id).revision, revision)

        with self.assertRaisesRegex(ValueError, "Formula-like"):
            apply_sheet_decisions(
                self.store,
                self.bundle(
                    {
                        "topic_id": self.topic.topic_id,
                        "expected_revision": revision,
                        "decision": "NOTES",
                        "notes": "=IMPORTXML(...)",
                    }
                ),
            )
        self.assertEqual(self.store.get_topic(self.site, self.topic.topic_id).revision, revision)

    def test_published_topic_cannot_be_rejected_from_sheet(self) -> None:
        published = self.store.record_publication(
            self.site,
            self.topic.topic_id,
            PublicationRef(
                blogger_post_id="post-1",
                url="https://example.blogspot.com/post.html",
                status="LIVE",
                last_verified_at="2026-07-26T20:00:00+09:00",
            ),
        )
        with self.assertRaisesRegex(ValueError, "forbidden"):
            apply_sheet_decisions(
                self.store,
                self.bundle(
                    {
                        "topic_id": published.topic_id,
                        "expected_revision": published.revision,
                        "decision": "REJECT",
                        "reason": "unsafe",
                    }
                ),
            )
        self.assertEqual(
            self.store.get_topic(self.site, published.topic_id).status,
            TopicStatus.PUBLISHED,
        )

    def test_priority_override_is_separate_and_survives_recalculation(self) -> None:
        applied = apply_sheet_decisions(
            self.store,
            self.bundle(
                {
                    "topic_id": self.topic.topic_id,
                    "expected_revision": self.topic.revision,
                    "decision": "PRIORITY_OVERRIDE",
                    "priority_override": 77,
                }
            ),
        )
        self.assertEqual(applied["applied"][0]["topic_id"], self.topic.topic_id)
        overridden = self.store.get_topic(self.site, self.topic.topic_id)
        self.assertIsNotNone(overridden)
        assert overridden is not None
        self.assertEqual(overridden.priority_override, 77)
        self.assertNotIn("manual_override", overridden.priority_components)

        recalculated = self.store.recalculate_priority(
            self.site,
            self.topic.topic_id,
        )
        self.assertEqual(recalculated.priority_score, 77)
        self.assertEqual(recalculated.priority_override, 77)
        self.assertEqual(
            set(recalculated.priority_components),
            {
                "evidence_strength",
                "recurrence",
                "content_gap",
                "severity",
                "answerability",
                "recency",
            },
        )

    def test_reapplying_the_same_exported_decision_is_a_noop(self) -> None:
        first = apply_sheet_decisions(
            self.store,
            self.bundle(
                {
                    "topic_id": self.topic.topic_id,
                    "expected_revision": self.topic.revision,
                    "decision": "HOLD",
                    "reason": "held from Sheet review",
                }
            ),
        )
        revision = first["applied"][0]["revision"]
        second = apply_sheet_decisions(
            self.store,
            self.bundle(
                {
                    "topic_id": self.topic.topic_id,
                    "expected_revision": revision,
                    "decision": "HOLD",
                    "reason": "held from Sheet review",
                }
            ),
        )
        self.assertEqual(second["applied"][0]["revision"], revision)
        self.assertEqual(
            self.store.get_topic(self.site, self.topic.topic_id).revision,
            revision,
        )


if __name__ == "__main__":
    unittest.main()
