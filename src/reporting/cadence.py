from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


START_DATE = date(2026, 6, 24)
TWO_POST_REVIEW_DATE = date(2026, 7, 22)
THREE_POST_REVIEW_DATE = date(2026, 8, 19)


@dataclass(frozen=True)
class CadenceReview:
    current_recommendation: str
    action: str
    days_since_start: int
    published_posts: int
    indexed_pages_estimate: int
    recent_impressions: int
    quality_issue_count: int
    two_post_review_date: str
    three_post_review_date: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def review_cadence(
    today: date,
    published_posts: int,
    indexed_pages_estimate: int,
    recent_impressions: int,
    quality_issue_count: int,
) -> CadenceReview:
    days_since_start = max(0, (today - START_DATE).days + 1)
    reasons: list[str] = []

    if today < TWO_POST_REVIEW_DATE:
        reasons.append("아직 초기 신뢰도 구축 기간입니다. 하루 1개를 유지하세요.")
        action = "하루 1개 유지"
        recommendation = "not_ready"
    elif indexed_pages_estimate >= 50 and published_posts >= 50 and quality_issue_count == 0 and today >= THREE_POST_REVIEW_DATE:
        reasons.append("3개 전환 검토일 이후이고, 공개 글/색인 추정 수가 50개 이상입니다.")
        if recent_impressions > 0:
            reasons.append("Search Console 노출 데이터가 감지되었습니다.")
        action = "하루 3개 전환 검토 가능"
        recommendation = "review_3_posts"
    elif indexed_pages_estimate >= 20 and published_posts >= 20 and quality_issue_count == 0:
        reasons.append("2개 전환 검토일 이후이고, 공개 글/색인 추정 수가 20개 이상입니다.")
        action = "하루 2개 전환 검토 가능"
        recommendation = "review_2_posts"
    else:
        if published_posts < 20:
            reasons.append("공개 글 수가 아직 20개 미만입니다.")
        if indexed_pages_estimate < 20:
            reasons.append("Search Console에서 확인되는 색인/노출 페이지가 아직 20개 미만입니다.")
        if quality_issue_count > 0:
            reasons.append("품질 이슈가 있어 발행량 확대 전 보강이 필요합니다.")
        action = "하루 1개 유지"
        recommendation = "not_ready"

    return CadenceReview(
        current_recommendation=recommendation,
        action=action,
        days_since_start=days_since_start,
        published_posts=published_posts,
        indexed_pages_estimate=indexed_pages_estimate,
        recent_impressions=recent_impressions,
        quality_issue_count=quality_issue_count,
        two_post_review_date=TWO_POST_REVIEW_DATE.isoformat(),
        three_post_review_date=THREE_POST_REVIEW_DATE.isoformat(),
        reasons=reasons,
    )


def build_cadence_alert_message(site_name: str, site_url: str, review: CadenceReview) -> str:
    return "\n".join(
        [
            "[Posting Bot] 발행량 전환 검토일 알림",
            "",
            f"- 블로그: {site_name}",
            f"- 사이트: {site_url}",
            f"- 권장 조치: {review.action}",
            f"- 운영 일수: {review.days_since_start}일",
            f"- 공개 글 수: {review.published_posts}개",
            f"- Search Console 색인/노출 페이지 추정: {review.indexed_pages_estimate}개",
            f"- 최근 노출 수: {review.recent_impressions}",
            f"- 품질 이슈 수: {review.quality_issue_count}",
            "",
            "판단 근거:",
            *[f"- {reason}" for reason in review.reasons],
            "",
            "운영 원칙:",
            "- 자동으로 발행량을 늘리지는 않습니다.",
            "- 전환 가능 알림이 오면 승인 후 스케줄을 변경합니다.",
        ]
    )
