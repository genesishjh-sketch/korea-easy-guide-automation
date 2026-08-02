from __future__ import annotations

import logging
from urllib.parse import quote_plus

import requests

from src.models import TopicSignal
from src.utils.text import clean_space


LOGGER = logging.getLogger(__name__)

EVIDENCE_SEARCH_SUGGESTION = "SEARCH_SUGGESTION"
EVIDENCE_FALLBACK_TEMPLATE = "FALLBACK_TEMPLATE"
SEED_ENRICHER_ROLE = "seed_enricher"


FALLBACK_SUGGESTIONS = {
    "incheon airport to seoul": [
        "incheon airport to seoul station",
        "incheon airport to seoul by train",
        "incheon airport to myeongdong",
        "incheon airport to hongdae",
        "arex express train vs airport bus",
    ],
    "korea esim for tourists": [
        "best esim for korea travel",
        "korea esim incheon airport",
        "korea esim vs sim card",
    ],
}


WINDOWS_FALLBACK_SUGGESTIONS = {
    "wifi button missing windows 11": [
        "wifi option disappeared windows 11",
        "windows 11 no wifi button only ethernet",
        "wifi adapter missing device manager windows 11",
        "network reset windows 11 wifi missing",
        "windows 11 wifi button missing after update",
    ],
    "snipping tool not working windows 11": [
        "snipping tool not opening windows 11",
        "windows shift s not working windows 11",
        "snipping tool screenshot not saving",
        "repair snipping tool windows 11",
        "reset snipping tool app windows 11",
    ],
    "microsoft store download stuck": [
        "microsoft store stuck downloading windows 11",
        "microsoft store pending download not moving",
        "microsoft store app download stuck at 0",
        "repair microsoft store windows 11",
        "microsoft store cache reset beginner",
    ],
    "microsoft store apps not updating": [
        "microsoft store apps not updating windows 11",
        "microsoft store update pending stuck",
        "microsoft store library updates not working",
        "repair microsoft store apps windows 11",
        "windows app update stuck microsoft store",
    ],
    "photos app not opening windows 11": [
        "photos app crashes on startup windows 11",
        "microsoft photos not opening windows 11",
        "repair photos app windows 11",
        "reset photos app windows 11",
        "photos app blank screen windows 11",
    ],
    "windows update error 0x80073712": [
        "windows update error 0x80073712 windows 11",
        "0x80073712 component store corrupted",
        "fix windows update 0x80073712 safely",
        "sfc dism 0x80073712 windows update",
        "windows update troubleshooter 0x80073712",
    ],
    "windows update error 0x80070103": [
        "windows update error 0x80070103 driver update",
        "0x80070103 windows 11 update failed",
        "hide driver update 0x80070103",
        "windows update keeps showing 0x80070103",
        "is 0x80070103 safe to ignore",
    ],
}


class GoogleSuggestSeedEnricher:
    def __init__(self, timeout: int = 12) -> None:
        self.timeout = timeout
        self.diagnostics: dict = {}

    def collect(self, query: str, limit: int = 10) -> list[TopicSignal]:
        self.diagnostics = {
            "collector_name": "google_suggest_seed_enricher",
            "collector_role": SEED_ENRICHER_ROLE,
            "query": query,
            "status": "not_started",
            "live_suggestion_count": 0,
            "fallback_suggestion_count": 0,
            "search_suggestion_count": 0,
            "fallback_template_count": 0,
            "demand_eligible_signal_count": 0,
            "evidence_type_counts": {},
            "used_fallback": False,
            "fallback_reason": "",
            "error": "",
        }
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q={quote_plus(query)}"
        collection_method = "live"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            suggestions = payload[1] if len(payload) > 1 else []
            self.diagnostics["status"] = "live_connected" if suggestions else "no_google_suggestions"
            self.diagnostics["live_suggestion_count"] = len(suggestions)
        except Exception as exc:
            LOGGER.warning("Google suggestion collection failed: %s", exc)
            self.diagnostics["error"] = str(exc)
            suggestions = fallback_suggestions(query)
            collection_method = "fallback_template"
            self.diagnostics["status"] = "fallback_only" if suggestions else "no_google_suggestions"
            self.diagnostics["fallback_suggestion_count"] = len(suggestions)
            self.diagnostics["used_fallback"] = bool(suggestions)
            if suggestions:
                self.diagnostics["fallback_reason"] = "Google Suggest request failed; used local query-intent fallback."

        evidence_type = (
            EVIDENCE_SEARCH_SUGGESTION
            if collection_method == "live"
            else EVIDENCE_FALLBACK_TEMPLATE
        )
        signals = [
            TopicSignal(
                source="google_suggest",
                keyword=query,
                title=clean_space(suggestion),
                score=0.0,
                metadata={
                    "collection_method": collection_method,
                    "evidence_type": evidence_type,
                    "collector_role": SEED_ENRICHER_ROLE,
                    "query_expansion_only": True,
                    "is_fallback": collection_method == "fallback_template",
                    "suggestion_order": index,
                    "demand_weight": 0.0,
                    "stability_weight": 0.0,
                    "ready_weight": 0.0,
                    "cadence_weight": 0.0,
                },
            )
            for index, suggestion in enumerate(suggestions[:limit])
            if clean_space(suggestion)
        ]
        self.diagnostics["search_suggestion_count"] = (
            len(signals) if evidence_type == EVIDENCE_SEARCH_SUGGESTION else 0
        )
        self.diagnostics["fallback_template_count"] = (
            len(signals) if evidence_type == EVIDENCE_FALLBACK_TEMPLATE else 0
        )
        self.diagnostics["evidence_type_counts"] = {evidence_type: len(signals)} if signals else {}
        return signals


def fallback_suggestions(query: str) -> list[str]:
    normalized = query.lower().strip()
    if normalized in FALLBACK_SUGGESTIONS:
        return FALLBACK_SUGGESTIONS[normalized]
    if normalized in WINDOWS_FALLBACK_SUGGESTIONS:
        return WINDOWS_FALLBACK_SUGGESTIONS[normalized]
    if looks_like_windows_query(normalized):
        return [
            f"{normalized} fix",
            f"{normalized} windows 11",
            f"{normalized} safe beginner steps",
            f"{normalized} microsoft support",
            f"{normalized} after update",
        ]
    return []


def looks_like_windows_query(query: str) -> bool:
    return any(
        term in query
        for term in [
            "windows",
            "microsoft store",
            "file explorer",
            "snipping tool",
            "onedrive",
            "bluetooth",
            "printer",
            "device manager",
            "taskbar",
            "start menu",
            "0x",
        ]
    )


# Backwards-compatible import for existing pipeline code and third-party callers.
GoogleSuggestCollector = GoogleSuggestSeedEnricher
