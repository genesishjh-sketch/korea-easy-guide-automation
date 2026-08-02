from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.topics.blogger_labels import rollback_proposal_blogger_labels
from src.topics.blogger_labels import sync_proposal_blogger_labels
from src.topics.defaults import default_categories
from src.topics.models import ProposalKind
from src.topics.models import ProposalStatus
from src.topics.models import PublicationRef
from src.topics.store import TopicStore


SITE = "korea_easy_guide"


class FakeBloggerLabelClient:
    def __init__(self, posts: dict[str, dict]) -> None:
        self.posts = deepcopy(posts)
        self.get_calls: list[str] = []
        self.update_calls: list[str] = []
        self.fail_second_update_once = False
        self._failed = False

    def get_post(self, post_id: str) -> dict:
        self.get_calls.append(post_id)
        return deepcopy(self.posts[post_id])

    def update_post_labels(
        self,
        post_id: str,
        labels: list[str],
        *,
        post: dict | None = None,
    ) -> dict:
        self.update_calls.append(post_id)
        if (
            self.fail_second_update_once
            and not self._failed
            and len(self.update_calls) == 2
        ):
            self._failed = True
            raise RuntimeError("simulated Blogger failure")
        self.posts[post_id]["labels"] = list(labels)
        return deepcopy(self.posts[post_id])


class TopicBloggerLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = TopicStore(Path(self.temp.name) / "topics")
        self.categories = default_categories(SITE)
        self.store.ensure_site(SITE, self.categories)
        self.old_label = self.categories[0].blogger_label
        self.post_ids = ["post-label-a", "post-label-b"]
        for index, post_id in enumerate(self.post_ids):
            topic = self.store.create_topic(
                SITE,
                f"Published topic {index}",
                self.categories[0].category_id,
            )
            self.store.record_publication(
                SITE,
                topic.topic_id,
                PublicationRef(
                    blogger_post_id=post_id,
                    url=f"https://example.blogspot.com/{post_id}.html",
                    title=f"Published topic {index}",
                    status="LIVE",
                    last_verified_at="2026-07-26T20:00:00+09:00",
                ),
            )
        self.proposal = self.store.create_monthly_proposal(
            SITE,
            ProposalKind.LABEL_CHANGE,
            {
                "category_id": self.categories[0].category_id,
                "blogger_label": "Korea Transportation",
            },
            reason="Clearer public label",
        )
        self.client = FakeBloggerLabelClient(
            {
                post_id: {
                    "id": post_id,
                    "url": f"https://example.blogspot.com/{post_id}.html",
                    "title": post_id,
                    "content": "<article>Keep this content.</article>",
                    "labels": ["Keep Me", self.old_label, "Also Keep"],
                }
                for post_id in self.post_ids
            }
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unapproved_proposal_never_calls_blogger(self) -> None:
        with self.assertRaisesRegex(ValueError, "before explicit approval"):
            sync_proposal_blogger_labels(
                self.store,
                SITE,
                self.proposal.proposal_id,
                self.client,
                apply=True,
            )
        self.assertEqual(self.client.get_calls, [])
        self.assertEqual(self.client.update_calls, [])

    def test_partial_failure_retries_idempotently_and_preserves_other_labels(self) -> None:
        self.store.approve_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
            "editor@example.com",
            "Approved",
        )
        pending = self.store.apply_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        self.assertEqual(pending.status, ProposalStatus.APPROVED)
        self.assertTrue(Path(pending.snapshot_path).exists())
        self.assertTrue(Path(pending.rollback_path).exists())

        preview = sync_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
        )
        self.assertTrue(preview["dry_run"])
        self.assertEqual(self.client.update_calls, [])

        self.client.fail_second_update_once = True
        failed = sync_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )
        self.assertFalse(failed["success"])
        self.assertEqual(failed["status"], "PENDING_RETRY")
        still_pending = self.store.get_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        self.assertIsNotNone(still_pending)
        assert still_pending is not None
        self.assertTrue(still_pending.publication_sync_pending)
        self.assertTrue(Path(still_pending.label_sync_snapshot_path).exists())

        completed = sync_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )
        self.assertTrue(completed["success"])
        self.assertEqual(completed["status"], "APPLIED")
        self.assertEqual(sorted(self.client.update_calls.count(post_id) for post_id in self.post_ids), [1, 2])
        for post in self.client.posts.values():
            self.assertEqual(
                post["labels"],
                ["Keep Me", "Korea Transportation", "Also Keep"],
            )
        for operation in completed["operations"]:
            self.assertEqual(
                operation["canonical_url"],
                f"https://example.blogspot.com/{operation['blogger_post_id']}.html",
            )

    def test_url_mismatch_aborts_prefetch_with_zero_writes(self) -> None:
        self.store.approve_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
            "editor@example.com",
            "Approved",
        )
        self.store.apply_monthly_proposal(SITE, self.proposal.proposal_id)
        self.client.posts[self.post_ids[0]]["url"] = (
            "https://example.blogspot.com/a-different-post.html"
        )

        with self.assertRaisesRegex(ValueError, "URL mismatch"):
            sync_proposal_blogger_labels(
                self.store,
                SITE,
                self.proposal.proposal_id,
                self.client,
                apply=True,
            )
        self.assertEqual(self.client.update_calls, [])

    def _apply_forward_label_change(self) -> None:
        self.store.approve_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
            "editor@example.com",
            "Approved",
        )
        self.store.apply_monthly_proposal(SITE, self.proposal.proposal_id)
        completed = sync_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )
        self.assertTrue(completed["success"])
        self.assertEqual(completed["status"], "APPLIED")

    def test_rollback_preview_is_read_only_and_apply_aligns_blogger_and_registry(
        self,
    ) -> None:
        self._apply_forward_label_change()
        updates_after_forward = list(self.client.update_calls)

        preview = rollback_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
        )

        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["status"], "READY")
        self.assertEqual(self.client.update_calls, updates_after_forward)
        self.assertEqual(
            {operation["state"] for operation in preview["operations"]},
            {"RESTORE"},
        )
        for operation in preview["operations"]:
            self.assertEqual(
                operation["canonical_url"],
                f"https://example.blogspot.com/{operation['blogger_post_id']}.html",
            )
            self.assertEqual(
                operation["labels_after"],
                ["Keep Me", self.old_label, "Also Keep"],
            )
        still_applied = self.store.get_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        assert still_applied is not None
        self.assertEqual(still_applied.status, ProposalStatus.APPLIED)

        completed = rollback_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )

        self.assertTrue(completed["success"])
        self.assertEqual(completed["status"], "ROLLED_BACK")
        for post in self.client.posts.values():
            self.assertEqual(
                post["labels"],
                ["Keep Me", self.old_label, "Also Keep"],
            )
        rolled_back = self.store.get_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        assert rolled_back is not None
        self.assertEqual(rolled_back.status, ProposalStatus.ROLLED_BACK)
        self.assertEqual(
            self.store.get_category(
                SITE,
                self.categories[0].category_id,
            ).blogger_label,
            self.old_label,
        )

    def test_rollback_url_mismatch_has_zero_writes_and_keeps_registry_applied(
        self,
    ) -> None:
        self._apply_forward_label_change()
        self.client.update_calls.clear()
        self.client.posts[self.post_ids[0]]["url"] = (
            "https://example.blogspot.com/a-different-post.html"
        )

        with self.assertRaisesRegex(ValueError, "URL mismatch"):
            rollback_proposal_blogger_labels(
                self.store,
                SITE,
                self.proposal.proposal_id,
                self.client,
                apply=True,
            )

        self.assertEqual(self.client.update_calls, [])
        still_applied = self.store.get_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        assert still_applied is not None
        self.assertEqual(still_applied.status, ProposalStatus.APPLIED)
        self.assertEqual(
            self.store.get_category(
                SITE,
                self.categories[0].category_id,
            ).blogger_label,
            "Korea Transportation",
        )

    def test_partial_rollback_failure_retries_without_rewriting_restored_post(
        self,
    ) -> None:
        self._apply_forward_label_change()
        self.client.update_calls.clear()
        self.client._failed = False
        self.client.fail_second_update_once = True

        failed = rollback_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )

        self.assertFalse(failed["success"])
        self.assertEqual(failed["status"], "PENDING_RETRY")
        still_applied = self.store.get_monthly_proposal(
            SITE,
            self.proposal.proposal_id,
        )
        assert still_applied is not None
        self.assertEqual(still_applied.status, ProposalStatus.APPLIED)
        restored_post_id = self.client.update_calls[0]
        pending_post_id = self.client.update_calls[1]
        self.assertEqual(
            self.client.posts[restored_post_id]["labels"],
            ["Keep Me", self.old_label, "Also Keep"],
        )
        self.assertEqual(
            self.client.posts[pending_post_id]["labels"],
            ["Keep Me", "Korea Transportation", "Also Keep"],
        )

        completed = rollback_proposal_blogger_labels(
            self.store,
            SITE,
            self.proposal.proposal_id,
            self.client,
            apply=True,
        )

        self.assertTrue(completed["success"])
        self.assertEqual(completed["status"], "ROLLED_BACK")
        self.assertEqual(
            sorted(
                self.client.update_calls.count(post_id)
                for post_id in self.post_ids
            ),
            [1, 2],
        )
        for post in self.client.posts.values():
            self.assertEqual(
                post["labels"],
                ["Keep Me", self.old_label, "Also Keep"],
            )


if __name__ == "__main__":
    unittest.main()
