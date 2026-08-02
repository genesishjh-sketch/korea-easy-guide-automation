from __future__ import annotations

from datetime import date
import unittest

from src.reporting.cadence import build_cadence_alert_message
from src.reporting.cadence import review_cadence


def _verified_signal_quality(
    *,
    oauth: int = 0,
    observed: int | None = None,
    first_party: int = 0,
    **extra,
) -> dict:
    observed_count = oauth if observed is None else observed
    eligible_count = observed_count + first_party
    return {
        **extra,
        "reddit_oauth_signal_count": oauth,
        "observed_question_count": observed_count,
        "first_party_query_count": first_party,
        "demand_eligible_signal_count": eligible_count,
        "evidence_counts_verified": True,
        "derived_evidence_counts": {
            "live_reddit_signal_count": oauth,
            "reddit_oauth_signal_count": oauth,
            "observed_question_count": observed_count,
            "first_party_query_count": first_party,
            "demand_eligible_signal_count": eligible_count,
        },
    }


class CadenceReviewTests(unittest.TestCase):
    def test_two_post_review_is_allowed_when_quality_and_signals_are_stable(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality=_verified_signal_quality(
                status="connected",
                oauth=5,
                reddit_public_json_signal_count=0,
                reddit_google_site_search_signal_count=0,
                fallback_reddit_signal_count=0,
            ),
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

    def test_query_plan_does_not_bypass_reddit_health_block(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 6,
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
        self.assertEqual(review.observed_reddit_signal_count, 0)

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
                "reddit_google_site_search_signal_count": 0,
                "fallback_reddit_signal_count": 15,
            },
            reddit_health={
                "status": "missing_credentials",
                "status_label": "Reddit OAuth 키 없음",
                "health_score": 0,
                "blocks_cadence_increase": False,
                "action_required": "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET을 GitHub Secrets 또는 .env에 설정하세요.",
            },
        )

        joined_reasons = " ".join(review.reasons)
        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("초기 신뢰도 구축 기간", joined_reasons)
        self.assertIn("FALLBACK_TEMPLATE 질문", joined_reasons)

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
                "reddit_google_site_search_signal_count": 0,
                "fallback_reddit_signal_count": 6,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("FALLBACK_TEMPLATE 질문", " ".join(review.reasons))
        self.assertEqual(review.fallback_reddit_signal_count, 6)

    def test_query_plan_cannot_allow_three_post_review_without_observed_results(self) -> None:
        review = review_cadence(
            today=date(2026, 8, 19),
            published_posts=60,
            indexed_pages_estimate=60,
            recent_impressions=1000,
            quality_issue_count=0,
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 8,
                "fallback_reddit_signal_count": 0,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertIn("판단 점수가 0", " ".join(review.reasons))
        self.assertEqual(review.reddit_google_site_search_signal_count, 8)
        self.assertEqual(review.observed_reddit_signal_count, 0)

    def test_unverified_public_json_alone_cannot_increase_cadence(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "query_expansion_only",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 5,
                "query_plan_count": 5,
                "observed_question_count": 0,
                "first_party_query_count": 0,
                "demand_eligible_signal_count": 0,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.action, "하루 1개 유지")
        self.assertEqual(review.eligible_demand_evidence_count, 0)
        self.assertIn("검증 전 QUERY_PLAN", " ".join(review.reasons))

    def test_unverified_top_level_eligible_count_cannot_increase_cadence(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "observed",
                "observed_question_count": 3,
                "demand_eligible_signal_count": 3,
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.eligible_demand_evidence_count, 0)
        self.assertFalse(review.evidence_counts_verified)
        self.assertIn("파생된 수요 집계", " ".join(review.reasons))

    def test_mismatched_derived_counts_cannot_increase_cadence(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "observed",
                "evidence_counts_verified": True,
                "derived_evidence_counts": {
                    "live_reddit_signal_count": 1,
                    "reddit_oauth_signal_count": 1,
                    "observed_question_count": 1,
                    "first_party_query_count": 0,
                    "demand_eligible_signal_count": 9,
                },
            },
        )

        self.assertEqual(review.current_recommendation, "not_ready")
        self.assertEqual(review.eligible_demand_evidence_count, 0)
        self.assertFalse(review.evidence_counts_verified)

    def test_first_party_query_can_support_cadence_review(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality=_verified_signal_quality(
                status="observed",
                first_party=3,
                reddit_public_json_signal_count=0,
            ),
        )

        self.assertEqual(review.current_recommendation, "review_2_posts")
        self.assertEqual(review.first_party_query_count, 3)
        self.assertEqual(review.eligible_demand_evidence_count, 3)

    def test_cadence_alert_requests_observed_evidence_when_only_query_plan_exists(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality={
                "status": "connected",
                "reddit_oauth_signal_count": 0,
                "reddit_public_json_signal_count": 0,
                "reddit_google_site_search_signal_count": 6,
                "fallback_reddit_signal_count": 0,
            },
        )

        message = build_cadence_alert_message(
            "Easy PC Fix Guide",
            "https://easypcfixguide.blogspot.com",
            review,
        )

        self.assertIn("필요 조치", message)
        self.assertIn("https://www.reddit.com/prefs/apps", message)
        self.assertIn("Reddit QUERY_PLAN 수(판단 점수 0): 6", message)
        self.assertIn("OBSERVED_QUESTION 근거 수: 0", message)
        self.assertIn("FIRST_PARTY_QUERY 근거 수: 0", message)

    def test_cadence_alert_omits_reddit_setup_links_when_oauth_is_stable(self) -> None:
        review = review_cadence(
            today=date(2026, 7, 22),
            published_posts=25,
            indexed_pages_estimate=25,
            recent_impressions=100,
            quality_issue_count=0,
            signal_quality=_verified_signal_quality(
                status="connected",
                oauth=5,
                reddit_public_json_signal_count=0,
                fallback_reddit_signal_count=0,
            ),
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
