from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import github_secret_mapping
from src.utils.reddit_setup import reddit_app_field_guide
from src.utils.reddit_setup import reddit_oauth_secret_label


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
    signal_quality_status: str
    reddit_oauth_signal_count: int
    reddit_public_json_signal_count: int
    reddit_google_site_search_signal_count: int
    fallback_reddit_signal_count: int
    observed_reddit_signal_count: int
    observed_question_count: int
    first_party_query_count: int
    eligible_demand_evidence_count: int
    evidence_counts_verified: bool
    reddit_health_status: str
    reddit_health_score: int
    reddit_health_blocks_cadence_increase: bool
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
    signal_quality: dict | None = None,
    reddit_health: dict | None = None,
) -> CadenceReview:
    days_since_start = max(0, (today - START_DATE).days + 1)
    reasons: list[str] = []
    signal_quality = signal_quality or {}
    reddit_health = reddit_health or {}
    signal_quality_status = signal_quality.get("status", "not_uploaded")
    derived_counts, evidence_counts_verified = _verified_derived_evidence_counts(
        signal_quality
    )
    reddit_oauth_signal_count = derived_counts["reddit_oauth_signal_count"]
    reddit_public_json_signal_count = _count(signal_quality.get("reddit_public_json_signal_count", 0))
    reddit_google_site_search_signal_count = _count(signal_quality.get("reddit_google_site_search_signal_count", 0))
    fallback_reddit_signal_count = _count(signal_quality.get("fallback_reddit_signal_count", 0))
    observed_question_count = derived_counts["observed_question_count"]
    first_party_query_count = derived_counts["first_party_query_count"]
    eligible_demand_evidence_count = derived_counts[
        "demand_eligible_signal_count"
    ]
    observed_reddit_signal_count = derived_counts["live_reddit_signal_count"]
    reddit_health_status = reddit_health.get("status", "not_uploaded")
    reddit_health_score = _count(reddit_health.get("health_score", 0))
    reddit_health_blocks_cadence_increase = bool(
        reddit_health.get("blocks_cadence_increase", False)
    ) and eligible_demand_evidence_count <= 0
    has_unstable_reddit_collection = eligible_demand_evidence_count <= 0
    if not evidence_counts_verified:
        reasons.append(
            "검증된 signal_evidence 행에서 파생된 수요 집계가 없어 발행량 확대 근거로 사용하지 않습니다."
        )

    if today < TWO_POST_REVIEW_DATE:
        reasons.append("아직 초기 신뢰도 구축 기간입니다. 하루 1개를 유지하세요.")
        if reddit_health_blocks_cadence_increase:
            label = reddit_health.get("status_label") or reddit_health_status
            reasons.append(f"Reddit OAuth Health도 발행량 증량을 차단 중입니다: {label}.")
            reasons.append(f"Reddit Health 상태 점수는 {reddit_health_score}/100입니다.")
            if reddit_health.get("action_required"):
                reasons.append(f"필요 조치: {reddit_health.get('action_required')}")
        elif has_unstable_reddit_collection:
            reasons.append("최근 리서치에 OBSERVED_QUESTION 또는 FIRST_PARTY_QUERY 근거가 없습니다.")
            if fallback_reddit_signal_count:
                reasons.append("FALLBACK_TEMPLATE 질문은 실제 사용자 수요 근거가 아니므로 판단 점수에서 제외됩니다.")
            if reddit_public_json_signal_count:
                reasons.append("자동 public_json 결과는 실제 공개 페이지 검증 전 QUERY_PLAN으로 취급됩니다.")
            reasons.append("QUERY_PLAN, FALLBACK_TEMPLATE, SEARCH_SUGGESTION은 발행량 판단 점수가 0입니다.")
            reasons.append("발행량 확대 전 OAuth 질문, Codex가 원문 검증한 공개 질문, 또는 Search Console 쿼리를 확보하세요.")
        action = "하루 1개 유지"
        recommendation = "not_ready"
    elif reddit_health_blocks_cadence_increase:
        label = reddit_health.get("status_label") or reddit_health_status
        reasons.append(f"Reddit OAuth Health가 발행량 증량을 차단 중입니다: {label}.")
        reasons.append(f"Reddit Health 상태 점수는 {reddit_health_score}/100입니다.")
        if reddit_health.get("action_required"):
            reasons.append(f"필요 조치: {reddit_health.get('action_required')}")
        action = "하루 1개 유지"
        recommendation = "not_ready"
    elif has_unstable_reddit_collection:
        reasons.append("최근 리서치에 OBSERVED_QUESTION 또는 FIRST_PARTY_QUERY 근거가 없습니다.")
        if fallback_reddit_signal_count:
            reasons.append("FALLBACK_TEMPLATE 질문은 실제 사용자 수요 근거가 아니므로 판단 점수에서 제외됩니다.")
        if reddit_public_json_signal_count:
            reasons.append("자동 public_json 결과는 실제 공개 페이지 검증 전 QUERY_PLAN으로 취급됩니다.")
        reasons.append("QUERY_PLAN, FALLBACK_TEMPLATE, SEARCH_SUGGESTION은 발행량 판단 점수가 0입니다.")
        reasons.append("발행량 확대 전 OAuth 질문, Codex가 원문 검증한 공개 질문, 또는 Search Console 쿼리를 확보하세요.")
        action = "하루 1개 유지"
        recommendation = "not_ready"
    elif indexed_pages_estimate >= 50 and published_posts >= 50 and quality_issue_count == 0 and today >= THREE_POST_REVIEW_DATE:
        reasons.append("3개 전환 검토일 이후이고, 공개 글/색인 추정 수가 50개 이상입니다.")
        reasons.append(f"수요 판단 가능한 검증 근거가 {eligible_demand_evidence_count}개 있습니다.")
        if recent_impressions > 0:
            reasons.append("Search Console 노출 데이터가 감지되었습니다.")
        action = "하루 3개 전환 검토 가능"
        recommendation = "review_3_posts"
    elif indexed_pages_estimate >= 20 and published_posts >= 20 and quality_issue_count == 0:
        reasons.append("2개 전환 검토일 이후이고, 공개 글/색인 추정 수가 20개 이상입니다.")
        reasons.append(f"수요 판단 가능한 검증 근거가 {eligible_demand_evidence_count}개 있습니다.")
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
        signal_quality_status=signal_quality_status,
        reddit_oauth_signal_count=reddit_oauth_signal_count,
        reddit_public_json_signal_count=reddit_public_json_signal_count,
        reddit_google_site_search_signal_count=reddit_google_site_search_signal_count,
        fallback_reddit_signal_count=fallback_reddit_signal_count,
        observed_reddit_signal_count=observed_reddit_signal_count,
        observed_question_count=observed_question_count,
        first_party_query_count=first_party_query_count,
        eligible_demand_evidence_count=eligible_demand_evidence_count,
        evidence_counts_verified=evidence_counts_verified,
        reddit_health_status=reddit_health_status,
        reddit_health_score=reddit_health_score,
        reddit_health_blocks_cadence_increase=reddit_health_blocks_cadence_increase,
        two_post_review_date=TWO_POST_REVIEW_DATE.isoformat(),
        three_post_review_date=THREE_POST_REVIEW_DATE.isoformat(),
        reasons=reasons,
    )


def _verified_derived_evidence_counts(
    signal_quality: dict,
) -> tuple[dict[str, int], bool]:
    empty = {
        "live_reddit_signal_count": 0,
        "reddit_oauth_signal_count": 0,
        "observed_question_count": 0,
        "first_party_query_count": 0,
        "demand_eligible_signal_count": 0,
    }
    values = signal_quality.get("derived_evidence_counts")
    if (
        signal_quality.get("evidence_counts_verified") is not True
        or not isinstance(values, dict)
    ):
        return empty, False
    derived = {key: _count(values.get(key, 0)) for key in empty}
    if (
        derived["demand_eligible_signal_count"]
        != derived["observed_question_count"]
        + derived["first_party_query_count"]
        or derived["reddit_oauth_signal_count"]
        > derived["live_reddit_signal_count"]
        or derived["live_reddit_signal_count"]
        > derived["observed_question_count"]
    ):
        return empty, False
    return derived, True


def build_cadence_alert_message(
    site_name: str,
    site_url: str,
    review: CadenceReview,
    reddit_user_agent: str = "easy-pc-fix-guide/0.1 by your-reddit-username",
) -> str:
    lines = [
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
        f"- 수집 신호 상태: {review.signal_quality_status}",
        f"- Reddit OAuth 신호 수: {review.reddit_oauth_signal_count}",
        f"- Reddit public JSON 신호 수: {review.reddit_public_json_signal_count}",
        f"- Reddit QUERY_PLAN 수(판단 점수 0): {review.reddit_google_site_search_signal_count}",
        f"- Reddit fallback 신호 수: {review.fallback_reddit_signal_count}",
        f"- OBSERVED_QUESTION 근거 수: {review.observed_question_count}",
        f"- FIRST_PARTY_QUERY 근거 수: {review.first_party_query_count}",
        f"- 수요 판단 가능 근거 수: {review.eligible_demand_evidence_count}",
        f"- signal_evidence 파생 집계 검증: {'통과' if review.evidence_counts_verified else '실패'}",
        f"- Reddit Health 상태: {review.reddit_health_status}",
        f"- Reddit Health 점수: {review.reddit_health_score}/100",
        f"- Reddit Health 증량 차단: {'예' if review.reddit_health_blocks_cadence_increase else '아니오'}",
        "",
        "판단 근거:",
        *[f"- {reason}" for reason in review.reasons],
    ]
    if needs_reddit_oauth_action(review):
        lines.extend(
            [
                "",
                "필요 조치:",
                "- QUERY_PLAN·FALLBACK_TEMPLATE·SEARCH_SUGGESTION은 표현 확장용이며 수요·READY·발행량 판단에는 사용하지 않습니다.",
                "- 자동 public_json 응답은 원문 검증 전 QUERY_PLAN입니다.",
                "- 발행량 확대 판단에는 OBSERVED_QUESTION 또는 FIRST_PARTY_QUERY 근거가 필요합니다.",
                "- Reddit 승인 메일이 오면 script app을 만들고 client id/client secret을 추가해도 됩니다.",
                f"- Reddit 앱 생성: {REDDIT_APPS_URL}",
                f"- GitHub Actions Secrets에 {reddit_oauth_secret_label()}을 저장하세요.",
                f"- GitHub Secrets: {GITHUB_SECRETS_URL}",
                "- 저장 후 Actions > Easy PC Fix Reddit OAuth Health를 수동 실행해 연결을 확인하세요.",
            ]
        )
        lines.extend(
            [
                "",
                "Reddit 앱 입력값:",
                *[f"- {item}" for item in reddit_app_field_guide(f"{site_name} Automation", reddit_user_agent)],
                "",
                "GitHub에 넣을 값:",
                *[f"- {item}" for item in github_secret_mapping()],
            ]
        )
    lines.extend(
        [
            "",
            "운영 원칙:",
            "- 자동으로 발행량을 늘리지는 않습니다.",
            "- 전환 가능 알림이 오면 승인 후 스케줄을 변경합니다.",
        ]
    )
    return "\n".join(lines)


def needs_reddit_oauth_action(review: CadenceReview) -> bool:
    if review.eligible_demand_evidence_count > 0:
        return False
    if review.reddit_health_blocks_cadence_increase:
        return True
    return (
        review.signal_quality_status == "fallback_only"
        or review.fallback_reddit_signal_count > 0
        or review.reddit_google_site_search_signal_count > 0
        or review.observed_reddit_signal_count == 0
    )


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
