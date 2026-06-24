from __future__ import annotations

from datetime import date
import unittest

from src.reporting.cadence import review_cadence


class CadenceReviewTests(unittest.TestCase):
    def test_two_post_review_is_allowed_when_quality_and_signals_are_stable(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 5,
                "reddit_public_json_signal_count": 0,
                "fallback_reddit_signal_count": 0,
            },
        )

        self.assertEqual(review.current_recommendation, "review_2_posts")
        self.assertEqual(review.action, "하루 2개 전환 검토 가능")

    def test_fallback_only_blocks_cadence_increase_even_when_counts_are_ready(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "fallback_only",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "fallback_reddit_signal_count": 6,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("fallback 질문", " ".join(review.reasons))
        self.assertEqual(review.fallback_reddit_signal_count, 6)

    def test_public_json_only_blocks_cadence_increase_until_oauth_is_seen(self) -> None:
        review = review_cadence(
            today=date(2026, 8, 19),
            published_posts=60,
            indexed_pages_estimate=60,
            recent_impressions=1000,
            quality_issue_count=0,
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 8,
                "fallback_reddit_signal_count": 0,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("public JSON", " ".join(review.reasons))
        self.assertEqual(review.reddit_public_json_signal_count, 8)


if __name__ == "__main__":
    unittest.main()
