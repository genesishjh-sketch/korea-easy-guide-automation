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

WINDOWS_CATEGORY_RULES = [
    ("Wi-Fi & Internet", ["wifi", "wi-fi", "internet", "dns", "network"]),
    ("Bluetooth & Devices", ["bluetooth", "device not detected", "device manager", "pairing"]),
    ("Sound & Microphone", ["sound", "audio", "microphone", "mic"]),
    ("Printer & Scanner", ["printer", "scanner", "print queue", "offline"]),
    ("Boot & Recovery", ["boot", "recovery", "safe mode", "blue screen", "bsod"]),
    ("File Explorer", ["file explorer", "folder", "files", "freezing"]),
    ("Windows Search", ["windows search", "search", "indexing"]),
    ("OneDrive & Account", ["onedrive", "account", "pin", "login", "sign in"]),
    ("Beginner PC Tips", ["screenshot", "disk space", "text bigger", "windows version"]),
    ("Windows Update", ["windows update stuck", "update error", "0x800f0922", "0x80070002", "0x80070005", "0x80070643"]),
    ("Error Codes", ["0x"]),
]


def infer_category(keyword: str, content_domain: str = "korea_travel") -> str:
    normalized = keyword.lower()
    if content_domain == "windows_help":
        for category, terms in WINDOWS_CATEGORY_RULES:
            if any(term in normalized for term in terms):
                return category
        return "Computer Help"

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


def build_candidate(seed: str, signals: list[TopicSignal], content_domain: str = "korea_travel") -> TopicCandidate:
    weighted = Counter()
    for signal in signals:
        weighted[signal.title.lower()] += signal.score

    source_bonus = len({signal.source for signal in signals}) * 5
    activity_score = min(60, sum(signal.score for signal in signals) / max(1, len(signals)))
    diversity_score = min(20, len(weighted) * 2)
    score = round(activity_score + diversity_score + source_bonus, 2)

    return TopicCandidate(
        keyword=seed,
        category=infer_category(seed, content_domain),
        intent=infer_intent(seed),
        score=score,
        signals=signals,
    )
