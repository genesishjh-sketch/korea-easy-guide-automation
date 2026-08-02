from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.topics.defaults import default_categories
from src.topics.models import QuestionRecord
from src.topics.models import TopicStatus
from src.topics.sheet_export import build_sheet_export
from src.topics.store import TopicStore


class TopicSheetExportTests(unittest.TestCase):
    def test_export_has_fixed_sections_and_formula_safe_allowed_question_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(
                site,
                "=malicious title",
                categories[0].category_id,
                editor_brief="@unsafe brief",
            )
            question = store.upsert_question(
                site,
                QuestionRecord(
                    question_id="q1",
                    site=site,
                    source="query_plan",
                    source_item_id="plan-1",
                    title="+question",
                    summary="-summary",
                ),
            )
            store.link_question(site, question.question_id, topic.topic_id)

            payload = build_sheet_export(store, [site])

        self.assertEqual(
            set(payload),
            {
                "dashboard",
                "topics",
                "questions",
                "categories",
                "monthly_review",
                "publications",
                "runs",
            },
        )
        self.assertEqual(payload["topics"][0]["canonical_title"], "'=malicious title")
        self.assertEqual(payload["questions"][0]["title"], "'+question")
        self.assertEqual(payload["questions"][0]["topic_id"], topic.topic_id)
        self.assertEqual(payload["questions"][0]["cluster_id"], topic.cluster_id)
        self.assertNotIn("body", payload["questions"][0])
        self.assertNotIn("selftext", payload["questions"][0])

    def test_export_preserves_sheet_decision_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TopicStore(Path(directory) / "topics")
            site = "easy_pc_fix_guide"
            categories = default_categories(site)
            store.ensure_site(site, categories)
            topic = store.create_topic(
                site,
                "A held topic with an editorial decision",
                categories[0].category_id,
                status=TopicStatus.HOLD,
            )
            updated = topic.to_dict()
            updated["priority_override"] = 71
            updated["priority_score"] = 71
            updated["editor_notes"] = [
                "Keep the verified workaround.",
                "Recheck monthly.",
            ]
            store.upsert_topic(
                site,
                updated,
                expected_revision=topic.revision,
            )

            payload = build_sheet_export(store, [site])

        row = next(
            item
            for item in payload["topics"]
            if item["topic_id"] == topic.topic_id
        )
        self.assertEqual(row["user_decision"], "HOLD")
        self.assertEqual(row["priority_override"], 71)
        self.assertEqual(
            row["notes"],
            "Keep the verified workaround.\nRecheck monthly.",
        )


if __name__ == "__main__":
    unittest.main()
