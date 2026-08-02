from __future__ import annotations

import logging
from urllib.parse import quote_plus

import requests

from src.models import TopicSignal
from src.utils.text import clean_space


LOGGER = logging.getLogger(__name__)

EVIDENCE_OBSERVED_QUESTION = "OBSERVED_QUESTION"
EVIDENCE_FIRST_PARTY_QUERY = "FIRST_PARTY_QUERY"
EVIDENCE_SEARCH_SUGGESTION = "SEARCH_SUGGESTION"
EVIDENCE_QUERY_PLAN = "QUERY_PLAN"
EVIDENCE_FALLBACK_TEMPLATE = "FALLBACK_TEMPLATE"
EVIDENCE_TYPES = {
    EVIDENCE_OBSERVED_QUESTION,
    EVIDENCE_FIRST_PARTY_QUERY,
    EVIDENCE_SEARCH_SUGGESTION,
    EVIDENCE_QUERY_PLAN,
    EVIDENCE_FALLBACK_TEMPLATE,
}
ELIGIBLE_EVIDENCE_TYPES = {
    EVIDENCE_OBSERVED_QUESTION,
    EVIDENCE_FIRST_PARTY_QUERY,
}
SEED_ENRICHER_ROLE = "seed_enricher"

DEFAULT_SUBREDDITS = [
    "koreatravel",
    "korea",
    "Living_in_Korea",
    "travel",
    "solotravel",
]


FALLBACK_REDDIT_QUESTIONS = [
    "What is the easiest way to get from Incheon Airport to Seoul?",
    "Should I use AREX or airport bus from Incheon Airport?",
    "Can foreigners use Kakao Taxi in Korea?",
    "Which eSIM is best for Korea travel?",
    "Can I buy KTX tickets without a Korean phone number?",
]


WINDOWS_FALLBACK_REDDIT_QUESTIONS = [
    "Why is the Wi-Fi button missing on Windows 11?",
    "How do I fix a Windows Update error without resetting my PC?",
    "Why did Bluetooth disappear from Windows settings?",
    "What should I try first when Windows sound stops working?",
    "How do I fix a printer that says offline in Windows 11?",
    "Why does File Explorer keep freezing on Windows?",
    "How do I start Windows in Safe Mode if normal startup fails?",
    "Is it safe for a beginner to run SFC or DISM commands?",
    "What information should I write down before asking for Windows help?",
]


SEARCH_INTENT_MODIFIERS = [
    "question",
    "problem",
    "beginner",
]


def _evidence_metadata(evidence_type: str, **metadata) -> dict:
    if evidence_type not in EVIDENCE_TYPES:
        raise ValueError(f"unsupported evidence_type: {evidence_type}")
    eligible = evidence_type in ELIGIBLE_EVIDENCE_TYPES
    return {
        **metadata,
        "evidence_type": evidence_type,
        "collector_role": SEED_ENRICHER_ROLE,
        "demand_weight": 1.0 if eligible else 0.0,
        "stability_weight": 1.0 if eligible else 0.0,
        "ready_weight": 1.0 if eligible else 0.0,
        "cadence_weight": 1.0 if eligible else 0.0,
    }


def _evidence_type_counts(signals: list[TopicSignal]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for signal in signals:
        evidence_type = str(
            (signal.metadata or {}).get("evidence_type") or EVIDENCE_FALLBACK_TEMPLATE
        )
        counts[evidence_type] = counts.get(evidence_type, 0) + 1
    return dict(sorted(counts.items()))


class RedditSeedEnricher:
    def __init__(
        self,
        user_agent: str,
        client_id: str = "",
        client_secret: str = "",
        subreddits: list[str] | None = None,
        timeout: int = 12,
        skip_public_json: bool = False,
        skip_public_json_reason: str = "",
    ) -> None:
        self.user_agent = user_agent
        self.client_id = client_id
        self.client_secret = client_secret
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.timeout = timeout
        self.skip_public_json = skip_public_json
        self.skip_public_json_reason = skip_public_json_reason
        self.diagnostics: dict = {}

    def collect(self, query: str, limit: int = 10) -> list[TopicSignal]:
        self.diagnostics = {
            "collector_name": "reddit_seed_enricher",
            "collector_role": SEED_ENRICHER_ROLE,
            "query": query,
            "subreddits": list(self.subreddits),
            "oauth_configured": bool(self.client_id and self.client_secret),
            "oauth_error": "",
            "public_json_attempted_subreddits": [],
            "public_json_failed_subreddits": [],
            "public_json_error_count": 0,
            "public_json_skipped": bool(self.skip_public_json),
            "public_json_skip_reason": self.skip_public_json_reason if self.skip_public_json else "",
            "google_site_search_signal_count": 0,
            "public_json_signal_count": 0,
            "query_plan_count": 0,
            "observed_signal_count": 0,
            "first_party_query_count": 0,
            "fallback_template_count": 0,
            "demand_eligible_signal_count": 0,
            "evidence_type_counts": {},
            "used_fallback": False,
            "fallback_reason": "",
        }
        if self.client_id and self.client_secret:
            oauth_signals = self._collect_with_praw(query, limit)
            if oauth_signals:
                self._mark_observed_questions(oauth_signals, "oauth")
                self.diagnostics["status"] = "oauth_connected"
                self._record_evidence_diagnostics(oauth_signals)
                return oauth_signals

        signals: list[TopicSignal] = []
        if not self.skip_public_json:
            for subreddit in self.subreddits:
                self.diagnostics["public_json_attempted_subreddits"].append(subreddit)
                url = f"https://www.reddit.com/r/{subreddit}/search.json?q={quote_plus(query)}&restrict_sr=1&sort=relevance&limit={limit}"
                try:
                    response = requests.get(
                        url,
                        headers={"User-Agent": self.user_agent},
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    children = response.json().get("data", {}).get("children", [])
                except Exception as exc:
                    LOGGER.warning("Reddit collection failed for r/%s: %s", subreddit, exc)
                    self.diagnostics["public_json_failed_subreddits"].append(
                        {
                            "subreddit": subreddit,
                            "error": str(exc),
                        }
                    )
                    continue

                for child in children:
                    data = child.get("data", {})
                    title = clean_space(data.get("title", ""))
                    if not title:
                        continue
                    signals.append(
                        TopicSignal(
                            source="reddit",
                            keyword=query,
                            title=title,
                            url=f"https://www.reddit.com{data.get('permalink', '')}",
                            score=0.0,
                            metadata=_evidence_metadata(
                                EVIDENCE_QUERY_PLAN,
                                subreddit=subreddit,
                                collection_method="public_json",
                                reddit_item_id=str(data.get("id") or ""),
                                canonical_public_page_url=f"https://www.reddit.com{data.get('permalink', '')}",
                                verified_by_codex=False,
                                query_expansion_only=True,
                                reported_score=data.get("score", 0),
                                num_comments=data.get("num_comments", 0),
                                created_utc=data.get("created_utc"),
                            ),
                        )
                    )

        if signals:
            self.diagnostics["status"] = "public_json_unverified"
            self.diagnostics["public_json_error_count"] = len(self.diagnostics["public_json_failed_subreddits"])
            self.diagnostics["public_json_signal_count"] = len(signals)
            self.diagnostics["query_plan_count"] = len(signals)
            self._record_evidence_diagnostics(signals)
            return signals

        search_signals = self._google_site_search_signals(query, limit)
        if search_signals:
            self.diagnostics["status"] = "query_plan_only"
            self.diagnostics["public_json_error_count"] = len(self.diagnostics["public_json_failed_subreddits"])
            self.diagnostics["google_site_search_signal_count"] = len(search_signals)
            self.diagnostics["query_plan_count"] = len(search_signals)
            self._record_evidence_diagnostics(search_signals)
            return search_signals

        query_terms = {part for part in query.lower().split() if len(part) > 2}
        fallback_signals = []
        for question in self._fallback_questions():
            question_terms = set(question.lower().split())
            overlap = len(query_terms & question_terms)
            if overlap == 0:
                continue
            fallback_signals.append(
                TopicSignal(
                    source="reddit_fallback",
                    keyword=query,
                    title=question,
                    score=0.0,
                    metadata=_evidence_metadata(
                        EVIDENCE_FALLBACK_TEMPLATE,
                        collection_method="fallback",
                        overlap_term_count=overlap,
                        query_expansion_only=True,
                    ),
                )
            )
        self.diagnostics["status"] = "fallback_only" if fallback_signals else "no_reddit_signals"
        self.diagnostics["public_json_error_count"] = len(self.diagnostics["public_json_failed_subreddits"])
        self.diagnostics["used_fallback"] = bool(fallback_signals)
        if fallback_signals:
            if self.skip_public_json:
                self.diagnostics["fallback_reason"] = self.skip_public_json_reason or "Public Reddit JSON collection was skipped."
            elif self.diagnostics["public_json_error_count"]:
                self.diagnostics["fallback_reason"] = "All available Reddit live collection paths returned no usable signals; public JSON had errors."
            else:
                self.diagnostics["fallback_reason"] = "Reddit live collection returned no matching signals."
        self._record_evidence_diagnostics(fallback_signals)
        return sorted(fallback_signals, key=lambda item: item.score, reverse=True)[:limit]

    def _google_site_search_signals(self, query: str, limit: int) -> list[TopicSignal]:
        signals: list[TopicSignal] = []
        normalized_query = clean_space(query)
        if not normalized_query:
            return signals
        windows_mode = self._uses_windows_subreddits()
        subreddits = self.subreddits[: max(1, min(len(self.subreddits), 4))]
        for subreddit in subreddits:
            search_query = f'site:reddit.com/r/{subreddit} "{normalized_query}"'
            url = f"https://www.google.com/search?q={quote_plus(search_query)}"
            signals.append(
                TopicSignal(
                    source="reddit_search",
                    keyword=query,
                    title=f"Reddit questions about {normalized_query} in r/{subreddit}",
                    url=url,
                    score=0.0,
                    metadata=_evidence_metadata(
                        EVIDENCE_QUERY_PLAN,
                        subreddit=subreddit,
                        collection_method="google_site_search",
                        search_query=search_query,
                        query_expansion_only=True,
                    ),
                )
            )
        for index, modifier in enumerate(SEARCH_INTENT_MODIFIERS):
            search_query = f'site:reddit.com "{normalized_query}" {modifier}'
            if windows_mode:
                search_query = f'{search_query} windows'
            signals.append(
                TopicSignal(
                    source="reddit_search",
                    keyword=query,
                    title=f"Reddit {modifier} searches for {normalized_query}",
                    url=f"https://www.google.com/search?q={quote_plus(search_query)}",
                    score=0.0,
                    metadata=_evidence_metadata(
                        EVIDENCE_QUERY_PLAN,
                        collection_method="google_site_search",
                        search_query=search_query,
                        query_expansion_only=True,
                        modifier_order=index,
                    ),
                )
            )
        return signals[:limit]

    def _record_evidence_diagnostics(self, signals: list[TopicSignal]) -> None:
        counts = _evidence_type_counts(signals)
        observed_count = counts.get(EVIDENCE_OBSERVED_QUESTION, 0)
        first_party_query_count = counts.get(EVIDENCE_FIRST_PARTY_QUERY, 0)
        self.diagnostics["evidence_type_counts"] = counts
        self.diagnostics["observed_signal_count"] = int(observed_count)
        self.diagnostics["first_party_query_count"] = int(first_party_query_count)
        self.diagnostics["fallback_template_count"] = int(
            counts.get(EVIDENCE_FALLBACK_TEMPLATE, 0)
        )
        self.diagnostics["demand_eligible_signal_count"] = int(
            observed_count + first_party_query_count
        )

    @staticmethod
    def _mark_observed_questions(signals: list[TopicSignal], collection_method: str) -> None:
        for signal in signals:
            if signal.source != "reddit":
                continue
            metadata = dict(signal.metadata or {})
            metadata.update(
                _evidence_metadata(
                    EVIDENCE_OBSERVED_QUESTION,
                    **{
                        key: value
                        for key, value in metadata.items()
                        if key
                        not in {
                            "evidence_type",
                            "collector_role",
                            "demand_weight",
                            "stability_weight",
                            "ready_weight",
                            "cadence_weight",
                        }
                    },
                )
            )
            metadata["collection_method"] = collection_method
            signal.metadata = metadata

    def _fallback_questions(self) -> list[str]:
        if self._uses_windows_subreddits():
            return WINDOWS_FALLBACK_REDDIT_QUESTIONS
        return FALLBACK_REDDIT_QUESTIONS

    def _uses_windows_subreddits(self) -> bool:
        windows_subreddits = {"windowshelp", "windows11", "techsupport", "pchelp"}
        return any(subreddit.lower() in windows_subreddits for subreddit in self.subreddits)

    def _collect_with_praw(self, query: str, limit: int) -> list[TopicSignal]:
        try:
            import praw

            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            signals: list[TopicSignal] = []
            for subreddit in self.subreddits:
                for submission in reddit.subreddit(subreddit).search(query, sort="relevance", limit=limit):
                    title = clean_space(submission.title)
                    if not title:
                        continue
                    signals.append(
                        TopicSignal(
                            source="reddit",
                            keyword=query,
                            title=title,
                            url=f"https://www.reddit.com{submission.permalink}",
                            score=float(submission.score) + float(submission.num_comments) * 1.5,
                            metadata=_evidence_metadata(
                                EVIDENCE_OBSERVED_QUESTION,
                                subreddit=subreddit,
                                collection_method="oauth",
                                source_item_id=str(submission.id),
                                canonical_public_page_url=f"https://www.reddit.com{submission.permalink}",
                                num_comments=submission.num_comments,
                                created_utc=submission.created_utc,
                            ),
                        )
                    )
            return sorted(signals, key=lambda item: item.score, reverse=True)
        except Exception as exc:
            LOGGER.warning("Reddit OAuth collection failed, falling back to public JSON: %s", exc)
            self.diagnostics["oauth_error"] = str(exc)
            return []


# Backwards-compatible import for existing pipeline code and third-party callers.
RedditCollector = RedditSeedEnricher
