from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from bs4 import BeautifulSoup


SHINGLE_SIZE = 7
REWRITE_BODY_SIMILARITY = 0.35
MAX_BODY_SIMILARITY = 0.45
MAX_REPEATED_TITLE_ENDING = 2
GENERIC_TITLE_ENDINGS = (
    "safe fixes for beginners",
    "simple fixes for beginners",
    "easy windows fixes for beginners",
    "easy guide for foreign visitors",
    "guide for first time visitors",
    "what it means and how to fix it",
)


@dataclass(frozen=True)
class OriginalityMatch:
    title: str
    url: str
    similarity: float


def article_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(["style", "script", "noscript"]):
        node.decompose()
    return " ".join(re.findall(r"[a-z0-9']+", soup.get_text(" ", strip=True).casefold()))


def shingle_similarity(first_html: str, second_html: str, size: int = SHINGLE_SIZE) -> float:
    first = shingles(article_text(first_html), size)
    second = shingles(article_text(second_html), size)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def shingles(text: str, size: int = SHINGLE_SIZE) -> set[tuple[str, ...]]:
    words = text.split()
    if len(words) < size:
        return set()
    return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}


def closest_match(
    candidate_html: str,
    posts: list[dict],
    *,
    exclude_url: str = "",
) -> OriginalityMatch | None:
    best = None
    for post in posts:
        url = str(post.get("url") or "")
        if exclude_url and url.rstrip("/") == exclude_url.rstrip("/"):
            continue
        similarity = shingle_similarity(candidate_html, str(post.get("content_html") or post.get("content") or ""))
        if best is None or similarity > best.similarity:
            best = OriginalityMatch(str(post.get("title") or "Untitled"), url, similarity)
    return best


def generic_title_ending(title: str) -> str:
    normalized = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
    return next((ending for ending in GENERIC_TITLE_ENDINGS if normalized.endswith(ending)), "")


def repeated_title_ending_count(title: str, existing_titles: list[str]) -> int:
    ending = generic_title_ending(title)
    if not ending:
        return 0
    counts = Counter(generic_title_ending(existing) for existing in existing_titles)
    return counts[ending]
