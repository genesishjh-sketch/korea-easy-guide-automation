from __future__ import annotations

from collections import Counter
import re

from src.models import TopicCandidate, TopicSignal


CATEGORY_RULES = [
    ("Transportation", ["airport", "arex", "train", "bus", "taxi", "ktx", "subway", "t-money"]),
    ("Mobile & Internet", ["esim", "sim", "wifi", "data", "roaming"]),
    ("Apps in Korea", ["kakao", "naver", "coupang", "baemin", "yogiyo", "papago"]),
    ("Food & Delivery", ["food", "delivery", "restaurant", "convenience store"]),
    ("Accommodation", ["hotel", "stay", "airbnb", "guesthouse", "goshiwon"]),
]

WINDOWS_CATEGORY_RULES = [
    ("Wi-Fi & Internet", ["wifi", "wi-fi", "internet", "dns", "network", "airplane mode"]),
    ("Bluetooth & Devices", ["bluetooth", "device not detected", "device not recognized", "device manager", "pairing", "usb", "camera", "touchpad", "mouse", "keyboard", "external hard drive", "sd card", "second monitor", "driver"]),
    ("Sound & Microphone", ["sound", "audio", "microphone", "mic", "headphones", "realtek"]),
    ("Printer & Scanner", ["printer", "scanner", "print queue", "offline"]),
    ("Boot & Recovery", ["boot", "recovery", "restore point", "safe mode", "blue screen", "bsod", "automatic repair", "restarting screen", "preparing automatic repair", "black screen", "blank desktop"]),
    ("File Explorer", ["file explorer", "folder", "files", "freezing", "desktop icons", "recycle bin", "cannot find file", "pdf files"]),
    ("Windows Search", ["windows search", "search", "indexing"]),
    ("OneDrive & Account", ["onedrive", "account", "pin", "login", "sign in", "password sign in", "fingerprint", "windows hello"]),
    ("Apps & Settings", ["settings app", "microsoft store", "photos app", "snipping tool", "calculator app", "default apps", "default browser", "uninstall apps", "taskbar", "start menu", "notifications", "clock", "startup apps", "windows explorer"]),
    ("Beginner PC Tips", ["screenshot", "disk space", "storage space", "text bigger", "windows version", "slow after update", "high disk", "high cpu", "high memory", "battery draining", "sleep mode", "wake from sleep", "screen brightness", "display resolution", "night light", "troubleshooter", "activated", "storage space"]),
    ("Windows Update", ["windows update", "update error", "pending restart", "download stuck", "install error", "cleanup safe", "0x800f0922", "0x80070002", "0x80070005", "0x80070643"]),
    ("Error Codes", ["0x"]),
]


def infer_category(keyword: str, content_domain: str = "korea_travel") -> str:
    normalized = keyword.lower()
    if content_domain == "windows_help":
        for category, terms in WINDOWS_CATEGORY_RULES:
            if matches_terms(normalized, terms):
                return category
        return "Computer Help"

    for category, terms in CATEGORY_RULES:
        if matches_terms(normalized, terms):
            return category
    return "Travel Basics"


def matches_terms(text: str, terms: list[str]) -> bool:
    for term in terms:
        if len(term) <= 3 and term.isalnum():
            if re.search(rf"\b{re.escape(term)}\b", text):
                return True
            continue
        if term in text:
            return True
    return False


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
