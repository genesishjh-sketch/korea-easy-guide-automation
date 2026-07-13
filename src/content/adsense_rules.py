from __future__ import annotations

from dataclasses import dataclass
import re


DEFAULT_DAILY_PUBLISH_LIMIT = 1
MAX_DAILY_PUBLISH_LIMIT = 2
EMERGENCY_DAILY_PUBLISH_LIMIT = 3

KOREAN_MIN_CHAR_COUNT = 1500
ENGLISH_MIN_WORD_COUNT = 800
META_DESCRIPTION_MIN_CHARS = 120
META_DESCRIPTION_MAX_CHARS = 170

FORBIDDEN_PROMOTIONAL_PHRASES = {
    "best guide ever",
    "this will change everything",
    "you must know this",
    "guaranteed",
    "무조건",
    "반드시 돈 번다",
    "꿀팁",
    "개이득",
    "ㅋㅋ",
}

FORBIDDEN_MONETIZATION_PATTERNS = (
    r"coupa?ng\s*partners?",
    r"affiliate\s+link",
    r"referral\s+link",
    r"paid\s+promotion",
    r"sponsored\s+by",
    r"buy\s+now",
    r"limited\s+time\s+deal",
    r"쿠팡\s*파트너스",
    r"제휴\s*링크",
)

FORBIDDEN_POLICY_TOPICS = {
    "casino",
    "betting",
    "gambling",
    "porn",
    "adult content",
    "crack download",
    "pirated software",
    "activation bypass",
    "kms activator",
    "high return guaranteed",
    "guaranteed profit",
    "카지노",
    "도박",
    "불법 다운로드",
    "크랙",
    "우회 방법",
    "고수익 보장",
}


@dataclass(frozen=True)
class AdsenseDomainRule:
    content_domain: str
    topic_description: str
    required_topic_terms: tuple[str, ...]
    blocked_topic_terms: tuple[str, ...]


DOMAIN_RULES = {
    "korea_travel": AdsenseDomainRule(
        content_domain="korea_travel",
        topic_description="Korea travel and Korea living guide for foreign visitors",
        required_topic_terms=(
            "korea",
            "seoul",
            "incheon",
            "ktx",
            "tmoney",
            "t-money",
            "esim",
            "kakao",
            "naver",
            "foreigner",
            "foreign visitors",
            "tourists",
            "travel",
        ),
        blocked_topic_terms=(
            "windows update",
            "microsoft support",
            "device driver",
            "windows driver",
            "registry",
            "investment",
            "crypto",
            "medical treatment",
        ),
    ),
    "windows_help": AdsenseDomainRule(
        content_domain="windows_help",
        topic_description="Windows and PC troubleshooting guide for beginners",
        required_topic_terms=(
            "windows",
            "pc",
            "computer",
            "microsoft",
            "update",
            "wi-fi",
            "wifi",
            "printer",
            "bluetooth",
            "onedrive",
            "error",
            "app",
        ),
        blocked_topic_terms=(
            "korea travel",
            "seoul",
            "hotel",
            "flight",
            "casino",
            "crypto",
            "medical treatment",
        ),
    ),
}


def domain_rule(content_domain: str) -> AdsenseDomainRule:
    return DOMAIN_RULES.get(content_domain, DOMAIN_RULES["korea_travel"])


def contains_forbidden_phrase(text_lower: str) -> list[str]:
    matches = set()
    for phrase in FORBIDDEN_PROMOTIONAL_PHRASES:
        for match in re.finditer(re.escape(phrase), text_lower):
            context = text_lower[max(0, match.start() - 24) : match.end() + 24]
            if any(guard in context for guard in ("not ", "no ", "does not ", "do not ", "without ")):
                continue
            matches.add(phrase)
    if re.search(r"\b100%\s+(?:guaranteed|works|success|safe|profit|approved)\b", text_lower):
        matches.add("100%")
    return sorted(matches)


def contains_forbidden_monetization(text_lower: str) -> list[str]:
    matches: list[str] = []
    for pattern in FORBIDDEN_MONETIZATION_PATTERNS:
        if re.search(pattern, text_lower):
            matches.append(pattern)
    return matches


def contains_forbidden_policy_topic(text_lower: str) -> list[str]:
    return sorted(topic for topic in FORBIDDEN_POLICY_TOPICS if topic in text_lower)


def daily_publish_limit_from_env(value: str | None, quality_review_enabled: bool = True) -> int:
    # Stabilization always defaults to one. Higher limits must be explicit after a cadence review.
    default_limit = DEFAULT_DAILY_PUBLISH_LIMIT
    if not value:
        return default_limit
    try:
        requested = int(value)
    except ValueError:
        return default_limit
    return max(1, min(requested, EMERGENCY_DAILY_PUBLISH_LIMIT))
