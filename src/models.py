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
    topic_id: str = ""
    cluster_id: str = ""
    category_id: str = ""
    action: str = "NEW_POST"
    revision: int = 0
    editor_brief: dict = field(default_factory=dict)
    reader_questions: list[str] = field(default_factory=list)
    difference_from_existing: str = ""
    existing_post_refs: list[dict] = field(default_factory=list)
    claim_run_id: str = ""

    @property
    def topic_action(self) -> str:
        return self.action

    @topic_action.setter
    def topic_action(self, value: str) -> None:
        self.action = value

    @property
    def topic_revision(self) -> int:
        return self.revision

    @topic_revision.setter
    def topic_revision(self, value: int) -> None:
        self.revision = value


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
