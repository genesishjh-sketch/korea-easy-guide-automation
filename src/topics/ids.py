from __future__ import annotations

from hashlib import sha256
import re
import unicodedata
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "ref",
    "referrer",
    "source",
}


def normalize_text(value: str) -> str:
    """Return a conservative match key without changing the stored text."""

    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def canonical_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.netloc:
        return value.rstrip("/")

    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    scheme = (parsed.scheme or "https").casefold()
    netloc = parsed.netloc.casefold()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def stable_id(prefix: str, *parts: object, length: int = 18) -> str:
    material = "\x1f".join(normalize_text(str(part)) for part in parts)
    digest = sha256(material.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def topic_id_for(site: str, identity_key: str) -> str:
    return stable_id("topic", site, identity_key)


def category_id_for(site: str, identity_key: str) -> str:
    return stable_id("cat", site, identity_key, length=14)


def question_id_for(
    site: str,
    source: str,
    source_item_id: str = "",
    url: str = "",
    title: str = "",
) -> str:
    if source_item_id:
        identity = f"item:{source}:{source_item_id}"
    elif canonical_url(url):
        identity = f"url:{canonical_url(url)}"
    else:
        identity = f"title:{source}:{normalize_text(title)}"
    return stable_id("question", site, identity)


def publication_key(blogger_post_id: str = "", url: str = "") -> str:
    if blogger_post_id:
        return f"post:{blogger_post_id.strip()}"
    return f"url:{canonical_url(url)}"
