from __future__ import annotations

from collections import Counter

from src.models import TopicCandidate, TopicSignal


CATEGORY_RULES = [
    ("Transportation", ["airport", "seoul", "arex", "train", "bus", "taxi", "ktx", "subway", "t-money"]),
    ("Mobile & Internet", ["esim", "sim", "wifi", "data", "roaming"]),
    ("Apps in Korea", ["kakao", "naver", "coupang", "baemin", "yogiyo", "papago"]),
    ("Food & Delivery", ["food", "delivery", "restaurant", "convenience store"]),
    ("Accommodation", ["hotel", "stay", "airbnb", "guesthouse", "goshiwon"]),
]


def infer_category(keyword: str) -> str:
    normalized = keyword.lower()
    for category, terms in CATEGORY_RULES:
        if any(term in normalized for term in terms):
            return category
    return "Travel Basics"


def infer_intent(keyword: str) -> str:
    normalized = keyword.lower()
    if normalized.startswith("how ") or "how to" in normalized:
        return "how-to"
    if any(term in normalized for term in ["best", "vs", "compare"]):
        return "comparison"
    if any(term in normalized for term in ["cost", "price", "fare"]):
        return "cost"
    return "practical-guide"


def build_candidate(seed: str, signals: list[TopicSignal]) -> TopicCandidate:
    weighted = Counter()
    for signal in signals:
        weighted[signal.title.lower()] += signal.score

    source_bonus = len({signal.source for signal in signals}) * 5
    activity_score = min(60, sum(signal.score for signal in signals) / max(1, len(signals)))
    diversity_score = min(20, len(weighted) * 2)
    score = round(activity_score + diversity_score + source_bonus, 2)

    return TopicCandidate(
        keyword=seed,
        category=infer_category(seed),
        intent=infer_intent(seed),
        score=score,
        signals=signals,
    )
