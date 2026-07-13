from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

import requests


DIRECT_POST_PATH = re.compile(r"^/\d{4}/\d{2}/[^/?#]+\.html$")
TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "before",
    "beginner",
    "beginners",
    "easy",
    "fix",
    "fixes",
    "for",
    "foreign",
    "foreigner",
    "foreigners",
    "from",
    "guide",
    "how",
    "in",
    "is",
    "it",
    "korea",
    "of",
    "on",
    "safe",
    "simple",
    "the",
    "this",
    "to",
    "tourist",
    "tourists",
    "visitor",
    "visitors",
    "what",
    "windows",
    "with",
    "your",
}


@dataclass(frozen=True)
class PublishedPost:
    title: str
    url: str
    labels: tuple[str, ...] = ()
    published: str = ""


def is_direct_post_url(url: str, site_url: str = "") -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if site_url and parsed.netloc != urlparse(site_url).netloc:
        return False
    return bool(DIRECT_POST_PATH.fullmatch(parsed.path))


def fetch_published_posts(site_url: str, max_results: int = 100) -> list[PublishedPost]:
    response = requests.get(
        f"{site_url.rstrip('/')}/feeds/posts/default?alt=json&max-results={max_results}",
        timeout=20,
    )
    response.raise_for_status()
    posts = []
    for entry in response.json().get("feed", {}).get("entry", []):
        url = next(
            (link.get("href", "") for link in entry.get("link", []) if link.get("rel") == "alternate"),
            "",
        )
        if not is_direct_post_url(url, site_url):
            continue
        posts.append(
            PublishedPost(
                title=entry.get("title", {}).get("$t", "").strip(),
                url=url,
                labels=tuple(item.get("term", "") for item in entry.get("category", []) if item.get("term")),
                published=entry.get("published", {}).get("$t", ""),
            )
        )
    return posts


def resolve_related_posts(
    site_url: str,
    topic: str,
    category: str = "",
    *,
    current_title: str = "",
    current_url: str = "",
    limit: int = 3,
    posts: list[PublishedPost] | None = None,
) -> list[dict[str, str]]:
    if limit < 1:
        return []
    try:
        candidates = list(posts) if posts is not None else fetch_published_posts(site_url)
    except requests.RequestException:
        return []

    topic_tokens = meaningful_tokens(f"{topic} {category}")
    normalized_title = normalize_title(current_title)
    normalized_url = current_url.rstrip("/")
    ranked = []
    for post in candidates:
        if not post.title or not is_direct_post_url(post.url, site_url):
            continue
        if normalize_title(post.title) == normalized_title or post.url.rstrip("/") == normalized_url:
            continue
        post_tokens = meaningful_tokens(f"{post.title} {' '.join(post.labels)}")
        overlap = len(topic_tokens & post_tokens)
        coverage = overlap / max(1, len(topic_tokens))
        label_match = 1 if category and any(category.casefold() == label.casefold() for label in post.labels) else 0
        ranked.append((label_match, overlap, coverage, post.published, post))

    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    selected = [item[-1] for item in ranked[:limit]]
    return [{"title": post.title, "url": post.url} for post in selected]


def meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold().replace("wi-fi", "wifi"))
        if len(token) > 1 and token not in TOKEN_STOPWORDS
    }


def normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold().replace("wi-fi", "wifi")))
