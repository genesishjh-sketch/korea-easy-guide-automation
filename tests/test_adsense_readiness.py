from __future__ import annotations

import unittest
from unittest.mock import Mock
from unittest.mock import patch

from src.reporting import adsense_readiness


def feed(entries: list[dict]) -> dict:
    return {"feed": {"entry": entries}}


def page_entry(title: str) -> dict:
    return {"title": {"$t": title}}


def post_entry(title: str, url: str, html: str) -> dict:
    return {
        "title": {"$t": title},
        "published": {"$t": "2026-07-07T00:00:00Z"},
        "content": {"$t": html},
        "link": [{"rel": "alternate", "href": url}],
    }


def rich_html(image: str = "https://example.com/image.jpg") -> str:
    body = " ".join(["useful beginner guidance"] * 1500)
    links = "".join(
        [
            '<a href="https://support.microsoft.com/en-us/windows/test">Microsoft</a>',
            '<a href="https://learn.microsoft.com/windows/test">Learn</a>',
            '<a href="https://www.microsoft.com/windows">Windows</a>',
            '<a href="https://support.microsoft.com/en-us/windows/another">Support</a>',
            '<a href="https://easypcfixguide.blogspot.com/search/label/Windows">Related</a>',
            '<a href="https://easypcfixguide.blogspot.com/2026/07/related.html">Related 2</a>',
        ]
    )
    return f"<p>{body}</p>{links}<img src='{image}'><img src='{image}-2'>"


class AdsenseReadinessTests(unittest.TestCase):
    def test_similarity_thresholds_flag_repetitive_template_content_early(self) -> None:
        self.assertLessEqual(adsense_readiness.REWRITE_BODY_SIMILARITY, 0.25)
        self.assertLessEqual(adsense_readiness.MAX_BODY_SIMILARITY, 0.32)

    def test_similarity_warning_requires_duplicate_risk_rewrite(self) -> None:
        self.assertEqual(
            adsense_readiness.classify_post_issues(["content_similarity_warning"]),
            "duplicate_risk",
        )

    def test_missing_required_pages_keeps_site_not_ready(self) -> None:
        responses = [
            Mock(ok=True, json=lambda: feed([page_entry("About")])),
            Mock(ok=True, json=lambda: feed([post_entry("Post", "https://easypcfixguide.blogspot.com/p.html", rich_html())])),
        ]
        for response in responses:
            response.raise_for_status = Mock()
        with patch("src.reporting.adsense_readiness.requests.get", side_effect=responses):
            result = adsense_readiness.build_readiness_report("easy_pc_fix_guide")

        self.assertEqual(result["status"], "not_ready")
        self.assertIn("Contact", result["required_pages"]["missing"])

    def test_reused_image_and_thin_content_are_classified(self) -> None:
        pages = [page_entry(title) for title in adsense_readiness.REQUIRED_PAGES]
        thin = "<p>short text</p><a href='https://easypcfixguide.blogspot.com/a'>A</a><img src='https://cdn.example.com/same.jpg'>"
        posts = [
            post_entry("Wi-Fi Keeps Disconnecting on Windows 11", "https://easypcfixguide.blogspot.com/a.html", thin),
            post_entry("Printer Offline on Windows 11", "https://easypcfixguide.blogspot.com/b.html", thin),
        ]
        responses = [
            Mock(ok=True, json=lambda: feed(pages)),
            Mock(ok=True, json=lambda: feed(posts)),
        ]
        for response in responses:
            response.raise_for_status = Mock()
        with patch("src.reporting.adsense_readiness.requests.get", side_effect=responses):
            result = adsense_readiness.build_readiness_report("easy_pc_fix_guide")

        self.assertEqual(result["status"], "not_ready")
        classifications = {item["classification"] for item in result["post_audits"]}
        self.assertIn("internal_links", classifications)
        issues = {issue for item in result["post_audits"] for issue in item["issues"]}
        self.assertIn("reused_image_url", issues)
        self.assertIn("thin_content", issues)


if __name__ == "__main__":
    unittest.main()
