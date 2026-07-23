from __future__ import annotations

import unittest

from src.pipeline.stage5_repair_indexing_links import add_related_link
from src.pipeline.stage5_repair_indexing_links import replace_broken_links


class RepairIndexingLinksTests(unittest.TestCase):
    def test_broken_link_is_replaced_by_matching_live_title(self) -> None:
        posts = [
            {
                "id": "1",
                "title": "Printer Queue Help",
                "url": "https://example.com/source.html",
                "content": (
                    "<h2>Related Guides</h2><ul><li>"
                    "<a href='https://example.com/missing.html'>Keyboard Not Typing in Windows 11</a>"
                    "</li></ul>"
                ),
            },
            {
                "id": "2",
                "title": "Keyboard Not Typing in Windows 11: Hardware and Layout Checks",
                "url": "https://example.com/keyboard-checks.html",
                "content": "<h1>Keyboard</h1>",
            },
        ]
        live_urls = {post["url"]: post for post in posts}
        html, changed, unresolved = replace_broken_links(
            posts[0], posts, live_urls, "https://example.com"
        )

        self.assertIn("https://example.com/keyboard-checks.html", html)
        self.assertEqual(len(changed), 1)
        self.assertEqual(unresolved, [])

    def test_related_link_is_added_only_once(self) -> None:
        html = "<article><h2>Related Guides</h2><ul></ul><h2>Sources</h2></article>"
        updated = add_related_link(html, "Useful Guide", "https://example.com/useful.html")
        repeated = add_related_link(updated, "Useful Guide", "https://example.com/useful.html")

        self.assertIn("Useful Guide", updated)
        self.assertEqual(repeated, updated)
