from __future__ import annotations

import unittest
from collections import Counter

from src.pipeline.stage5_repair_indexing_links import add_related_link
from src.pipeline.stage5_repair_indexing_links import build_repairs
from src.pipeline.stage5_repair_indexing_links import choose_orphan_source
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

    def test_known_windows_update_broken_link_uses_explicit_live_replacement(self) -> None:
        broken_url = (
            "https://easypcfixguide.blogspot.com/2026/07/"
            "windows-update-stuck-at-100-easy.html"
        )
        replacement_url = (
            "https://easypcfixguide.blogspot.com/2026/06/"
            "windows-update-download-stuck-at-0-easy.html"
        )
        posts = [
            {
                "id": "source",
                "title": "Windows 11 Slow After Update",
                "url": (
                    "https://easypcfixguide.blogspot.com/2026/07/"
                    "windows-11-slow-after-update-measure.html"
                ),
                "content": f"<a href='{broken_url}'>Windows Update Stuck at 100</a>",
            },
            {
                "id": "replacement",
                "title": "Windows Update Stuck at 0%: Check Activity Before You Interrupt It",
                "url": replacement_url,
                "content": "<h1>Windows Update Stuck at 0%</h1>",
            },
        ]

        html, changed, unresolved = replace_broken_links(
            posts[0],
            posts,
            {post["url"]: post for post in posts},
            "https://easypcfixguide.blogspot.com",
        )

        self.assertIn(replacement_url, html)
        self.assertIn(posts[1]["title"], html)
        self.assertEqual(changed[0]["old_url"], broken_url)
        self.assertEqual(unresolved, [])

    def test_known_orphans_use_explicit_contextual_sources(self) -> None:
        mappings = [
            (
                "https://koreaeasyguide.blogspot.com/2026/07/"
                "korea-mobile-payment-options-for.html",
                "https://koreaeasyguide.blogspot.com/2026/07/"
                "korea-cash-vs-card-guide-for-tourists.html",
            ),
            (
                "https://easypcfixguide.blogspot.com/2026/07/"
                "microsoft-store-not-opening-windows-11_01240372287.html",
                "https://easypcfixguide.blogspot.com/2026/07/"
                "microsoft-store-apps-not-updating-easy.html",
            ),
            (
                "https://easypcfixguide.blogspot.com/2026/07/"
                "network-adapter-missing-in-windows-11.html",
                "https://easypcfixguide.blogspot.com/2026/06/"
                "wi-fi-button-missing-on-windows-11.html",
            ),
            (
                "https://easypcfixguide.blogspot.com/2026/07/"
                "windows-11-slow-after-update-measure.html",
                "https://easypcfixguide.blogspot.com/2026/06/"
                "windows-update-pending-restart-stuck.html",
            ),
        ]
        for index, (orphan_url, source_url) in enumerate(mappings):
            with self.subTest(orphan_url=orphan_url):
                orphan = {
                    "id": f"orphan-{index}",
                    "title": "Deliberately unrelated orphan title",
                    "url": orphan_url,
                    "labels": [],
                }
                expected_source = {
                    "id": f"source-{index}",
                    "title": "Deliberately unrelated source title",
                    "url": source_url,
                    "labels": [],
                }
                higher_scoring_source = {
                    "id": f"other-{index}",
                    "title": "Deliberately unrelated orphan title",
                    "url": f"https://example.com/other-{index}.html",
                    "labels": [],
                }

                selected = choose_orphan_source(
                    orphan,
                    [orphan, higher_scoring_source, expected_source],
                    Counter(),
                )

                self.assertIs(selected, expected_source)

    def test_indexed_source_is_added_even_when_target_already_has_a_weak_incoming_link(self) -> None:
        target_url = (
            "https://easypcfixguide.blogspot.com/2026/07/"
            "camera-not-working-in-windows-11-fix.html"
        )
        posts = [
            {
                "id": "target",
                "title": "Camera Not Working in Windows 11",
                "url": target_url,
                "content": "<article><h1>Camera</h1></article>",
                "labels": ["Hardware"],
                "published": "2026-07-21T00:00:00Z",
            },
            {
                "id": "weak",
                "title": "Keyboard Not Typing",
                "url": "https://easypcfixguide.blogspot.com/2026/07/keyboard-not-typing-windows-11-easy.html",
                "content": f"<article><a href='{target_url}'>Camera guide</a></article>",
                "labels": ["Hardware"],
                "published": "2026-07-20T00:00:00Z",
            },
            {
                "id": "strong",
                "title": "Scanner Not Detected",
                "url": "https://easypcfixguide.blogspot.com/2026/07/scanner-not-detected-windows-11-easy.html",
                "content": "<article><h2>Related Guides</h2><ul></ul></article>",
                "labels": ["Hardware"],
                "published": "2026-07-19T00:00:00Z",
            },
        ]

        transformed, report = build_repairs(posts, "https://easypcfixguide.blogspot.com")

        self.assertIn(target_url, transformed["strong"])
        self.assertEqual(len(report["discovery_link_additions"]), 1)
        self.assertEqual(report["discovery_link_additions"][0]["source_id"], "strong")
