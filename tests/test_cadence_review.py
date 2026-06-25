from __future__ import annotations

from datetime import date
import unittest

from src.reporting.cadence import build_cadence_alert_message
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
            reddit_health={
                "status": "oauth_connected",
                "health_score": 100,
                "blocks_cadence_increase": False,
            },
        )

        self.assertEqual(review.current_recommendation, "review_2_posts")
        self.assertEqual(review.action, "하루 2개 전환 검토 가능")
        self.assertEqual(review.reddit_health_score, 100)
        self.assertFalse(review.reddit_health_blocks_cadence_increase)

    def test_reddit_health_blocks_cadence_increase_even_when_counts_are_ready(self) -> None:
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
            reddit_health={
                "status": "missing_credentials",
                "status_label": "Reddit OAuth 키 없음",
                "health_score": 0,
                "blocks_cadence_increase": True,
                "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertTrue(review.reddit_health_blocks_cadence_increase)
        self.assertIn("Reddit OAuth Health", " ".join(review.reasons))
        self.assertIn("0/100", " ".join(review.reasons))

    def test_initial_period_still_mentions_reddit_health_blocker(self) -> None:
        review = review_cadence(
            today=date(2026, 6, 25),
            published_posts=1,
            indexed_pages_estimate=0,
            recent_impressions=0,
            quality_issue_count=0,
            signal_quality={
                "status": "fallback_only",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "fallback_reddit_signal_count": 15,
            },
            reddit_health={
                "status": "missing_credentials",
                "status_label": "Reddit OAuth 키 없음",
                "health_score": 0,
                "blocks_cadence_increase": True,
                "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
            },
        )

        joined_reasons = " ".join(review.reasons)
        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("초기 신뢰도 구축 기간", joined_reasons)
        self.assertIn("Reddit OAuth Health도 발행량 증량을 차단", joined_reasons)
        self.assertIn("0/100", joined_reasons)

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

    def test_cadence_alert_includes_reddit_setup_links_when_oauth_is_missing(self) -> None:
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

        message = build_cadence_alert_message(
            "Easy PC Fix Guide",
            "https://easypcfixguide.blogspot.com",
            review,
        )

        self.assertIn("필요 조치", message)
        self.assertIn("https://www.reddit.com/prefs/apps", message)
        self.assertIn("REDDIT_CLIENT_ID", message)
        self.assertIn("Reddit Health 점수: 0/100", message)
        self.assertIn("Easy PC Fix Reddit OAuth Health", message)
        self.assertIn("Reddit 앱 입력값:", message)
        self.assertIn("앱 타입: script", message)
        self.assertIn("redirect uri: http://localhost:8080", message)
        self.assertIn("GitHub에 넣을 값:", message)
        self.assertIn("REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret", message)

    def test_cadence_alert_omits_reddit_setup_links_when_oauth_is_stable(self) -> None:
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

        message = build_cadence_alert_message(
            "Easy PC Fix Guide",
            "https://easypcfixguide.blogspot.com",
            review,
        )

        self.assertNotIn("필요 조치", message)
        self.assertNotIn("https://www.reddit.com/prefs/apps", message)


if __name__ == "__main__":
    unittest.main()
