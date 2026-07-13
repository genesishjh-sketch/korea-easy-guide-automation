from __future__ import annotations

import unittest

from src.pipeline.stage3_search_console_audit import action_items
from src.pipeline.stage3_search_console_audit import has_live_fetch_failure
from src.pipeline.stage3_search_console_audit import is_indexed
from src.pipeline.stage3_search_console_audit import summarize_audit


class SearchConsoleAuditTests(unittest.TestCase):
    def test_pass_verdict_is_indexed(self) -> None:
        self.assertTrue(is_indexed({"verdict": "PASS", "coverage_state": "Submitted and indexed"}))

    def test_not_indexed_coverage_is_not_a_false_positive(self) -> None:
        self.assertFalse(is_indexed({"verdict": "NEUTRAL", "coverage_state": "Crawled - currently not indexed"}))

    def test_redirect_error_is_structural_fetch_failure(self) -> None:
        self.assertTrue(has_live_fetch_failure([{"page_fetch_state": "REDIRECT_ERROR"}]))

    def test_summary_separates_index_delay_from_structural_errors(self) -> None:
        result = {
            "sitemaps": {"status": "connected", "sitemaps": [{"errors": 0, "warnings": 0}]},
            "url_inspections": [
                {
                    "status": "connected",
                    "url": "https://example.com/post.html",
                    "verdict": "NEUTRAL",
                    "coverage_state": "Discovered - currently not indexed",
                    "page_fetch_state": "PAGE_FETCH_STATE_UNSPECIFIED",
                }
            ],
        }
        summary = summarize_audit(result)
        self.assertEqual(summary["not_indexed_count"], 1)
        self.assertFalse(summary["structural_error"])

    def test_crawled_not_indexed_recommends_content_work_not_request_spam(self) -> None:
        result = {
            "summary": {"sitemap_errors": 0, "sitemap_warnings": 0},
            "sitemaps": {"status": "connected"},
            "url_inspections": [
                {
                    "status": "connected",
                    "verdict": "NEUTRAL",
                    "coverage_state": "Crawled - currently not indexed",
                    "page_fetch_state": "SUCCESSFUL",
                    "last_crawl_time": "2026-07-10T00:00:00Z",
                }
            ],
        }
        actions = " ".join(action_items(result))
        self.assertIn("고유성", actions)
        self.assertIn("반복하지 말고", actions)

    def test_historical_redirect_is_not_current_structural_error_when_live_check_passes(self) -> None:
        result = {
            "sitemaps": {"status": "connected", "sitemaps": [{"errors": 0, "warnings": 0}]},
            "url_inspections": [
                {
                    "status": "connected",
                    "url": "https://example.com/post.html",
                    "verdict": "NEUTRAL",
                    "coverage_state": "Redirect error",
                    "page_fetch_state": "REDIRECT_ERROR",
                }
            ],
            "current_live_checks": [{"url": "https://example.com/post.html", "ok": True, "issues": []}],
        }
        summary = summarize_audit(result)
        self.assertEqual(summary["historical_redirect_error_count"], 1)
        self.assertEqual(summary["resolved_historical_redirect_count"], 1)
        self.assertFalse(summary["structural_error"])

    def test_current_live_failure_blocks_even_without_historical_redirect(self) -> None:
        result = {
            "sitemaps": {"status": "connected", "sitemaps": [{"errors": 0, "warnings": 0}]},
            "url_inspections": [
                {
                    "status": "connected",
                    "url": "https://example.com/new.html",
                    "verdict": "NEUTRAL",
                    "coverage_state": "URL is unknown to Google",
                    "page_fetch_state": "PAGE_FETCH_STATE_UNSPECIFIED",
                }
            ],
            "current_live_checks": [
                {"url": "https://example.com/new.html", "ok": False, "issues": ["canonical_mismatch"]}
            ],
        }
        summary = summarize_audit(result)
        self.assertEqual(summary["current_live_indexability_failure_count"], 1)
        self.assertTrue(summary["structural_error"])


if __name__ == "__main__":
    unittest.main()
