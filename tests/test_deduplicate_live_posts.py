from __future__ import annotations

import unittest

from src.pipeline.stage5_deduplicate_live_posts import limit_rewrites_to_post_ids


class DeduplicateLivePostsTests(unittest.TestCase):
    def test_post_id_filter_preserves_every_unselected_post(self) -> None:
        posts = [
            {"id": "selected", "content": "<p>selected original</p>"},
            {"id": "untouched", "content": "<p>untouched original</p>"},
        ]
        rewrites = {
            "selected": "<p>selected revised</p>",
            "untouched": "<p>untouched revised</p>",
        }

        result = limit_rewrites_to_post_ids(posts, rewrites, {"selected"})

        self.assertEqual(result["selected"], "<p>selected revised</p>")
        self.assertEqual(result["untouched"], "<p>untouched original</p>")

    def test_no_filter_keeps_all_rewrites(self) -> None:
        posts = [{"id": "one", "content": "<p>original</p>"}]
        rewrites = {"one": "<p>revised</p>"}

        self.assertIs(limit_rewrites_to_post_ids(posts, rewrites, None), rewrites)


if __name__ == "__main__":
    unittest.main()
