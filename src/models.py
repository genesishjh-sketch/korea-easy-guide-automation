from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TopicSignal:
    source: str
    keyword: str
    title: str
    url: str = ""
    score: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class TopicCandidate:
    keyword: str
    category: str
    intent: str
    score: float
    signals: list[TopicSignal] = field(default_factory=list)


@dataclass
class ImageAsset:
    path: str
    url: str
    alt: str
    source: str
    credit: str = ""
    caption: str = ""


@dataclass
class Article:
    title: str
    slug: str
    category: str
    tags: list[str]
    meta_description: str
    markdown: str
    html: str
    image: ImageAsset
    sources: list[dict]
    created_at: datetime
    inline_images: list[ImageAsset] = field(default_factory=list)
