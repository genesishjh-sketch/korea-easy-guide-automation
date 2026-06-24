from __future__ import annotations

import logging
from urllib.parse import quote_plus

import requests

from src.models import TopicSignal
from src.utils.text import clean_space


LOGGER = logging.getLogger(__name__)

SUBREDDITS = [
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


class RedditCollector:
    def __init__(
        self,
        user_agent: str,
        client_id: str = "",
        client_secret: str = "",
        timeout: int = 12,
    ) -> None:
        self.user_agent = user_agent
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

    def collect(self, query: str, limit: int = 10) -> list[TopicSignal]:
        if self.client_id and self.client_secret:
            oauth_signals = self._collect_with_praw(query, limit)
            if oauth_signals:
                return oauth_signals

        signals: list[TopicSignal] = []
        for subreddit in SUBREDDITS:
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
                            "num_comments": data.get("num_comments", 0),
                            "created_utc": data.get("created_utc"),
                        },
                    )
                )

        if signals:
            return sorted(signals, key=lambda item: item.score, reverse=True)

        return [
            TopicSignal(source="reddit_fallback", keyword=query, title=question, score=2.0)
            for question in FALLBACK_REDDIT_QUESTIONS
            if any(part in question.lower() for part in query.lower().split())
        ][:limit]

    def _collect_with_praw(self, query: str, limit: int) -> list[TopicSignal]:
        try:
            import praw

            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            signals: list[TopicSignal] = []
            for subreddit in SUBREDDITS:
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
                                "num_comments": submission.num_comments,
                                "created_utc": submission.created_utc,
                            },
                        )
                    )
            return sorted(signals, key=lambda item: item.score, reverse=True)
        except Exception as exc:
            LOGGER.warning("Reddit OAuth collection failed, falling back to public JSON: %s", exc)
            return []
