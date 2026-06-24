from __future__ import annotations

import logging
from urllib.parse import quote_plus

import requests

from src.models import TopicSignal
from src.utils.text import clean_space


LOGGER = logging.getLogger(__name__)


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


class GoogleSuggestCollector:
    def __init__(self, timeout: int = 12) -> None:
        self.timeout = timeout

    def collect(self, query: str, limit: int = 10) -> list[TopicSignal]:
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q={quote_plus(query)}"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            suggestions = payload[1] if len(payload) > 1 else []
        except Exception as exc:
            LOGGER.warning("Google suggestion collection failed: %s", exc)
            suggestions = FALLBACK_SUGGESTIONS.get(query.lower(), [])

        return [
            TopicSignal(
                source="google_suggest",
                keyword=query,
                title=clean_space(suggestion),
                score=max(1.0, float(limit - index)),
            )
            for index, suggestion in enumerate(suggestions[:limit])
            if clean_space(suggestion)
        ]
