from __future__ import annotations

import logging
from urllib.parse import quote_plus

import requests

from src.models import TopicSignal
from src.utils.text import clean_space


LOGGER = logging.getLogger(__name__)

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


class RedditCollector:
    def __init__(
        self,
        user_agent: str,
        client_id: str = "",
        client_secret: str = "",
        subreddits: list[str] | None = None,
        timeout: int = 12,
    ) -> None:
        self.user_agent = user_agent
        self.client_id = client_id
        self.client_secret = client_secret
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.timeout = timeout

    def collect(self, query: str, limit: int = 10) -> list[TopicSignal]:
        if self.client_id and self.client_secret:
            oauth_signals = self._collect_with_praw(query, limit)
            if oauth_signals:
                return oauth_signals

        signals: list[TopicSignal] = []
        for subreddit in self.subreddits:
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
                        score=float(data.get("score", 0)) + float(data.get("num_comments", 0)) * 1.5,
                        metadata={
                            "subreddit": subreddit,
                            "collection_method": "public_json",
                            "num_comments": data.get("num_comments", 0),
                            "created_utc": data.get("created_utc"),
                        },
                    )
                )

        if signals:
            return sorted(signals, key=lambda item: item.score, reverse=True)

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
                    score=2.0 + overlap,
                    metadata={"collection_method": "fallback"},
                )
            )
        return sorted(fallback_signals, key=lambda item: item.score, reverse=True)[:limit]

    def _fallback_questions(self) -> list[str]:
        windows_subreddits = {"windowshelp", "windows11", "techsupport", "pchelp"}
        if any(subreddit.lower() in windows_subreddits for subreddit in self.subreddits):
            return WINDOWS_FALLBACK_REDDIT_QUESTIONS
        return FALLBACK_REDDIT_QUESTIONS

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
                            metadata={
                                "subreddit": subreddit,
                                "collection_method": "oauth",
                                "num_comments": submission.num_comments,
                                "created_utc": submission.created_utc,
                            },
                        )
                    )
            return sorted(signals, key=lambda item: item.score, reverse=True)
        except Exception as exc:
            LOGGER.warning("Reddit OAuth collection failed, falling back to public JSON: %s", exc)
            return []
