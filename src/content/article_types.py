from __future__ import annotations

import re


WINDOWS_ARTICLE_TYPE_ORDER = ("symptom_fix", "error_code_fix", "beginner_guide")
KOREA_ARTICLE_TYPE_ORDER = ("how_to", "comparison", "checklist")


def infer_article_type(seed: str, category: str = "", content_domain: str = "korea_travel") -> str:
    text = f"{seed} {category}".casefold()
    if content_domain == "windows_help":
        return infer_windows_article_type(text)
    return infer_korea_article_type(text)


def infer_windows_article_type(text: str) -> str:
    if re.search(r"\b0x[0-9a-f]{6,8}\b", text):
        return "error_code_fix"
    if text.startswith("how to ") or any(
        token in text
        for token in (
            "safe mode",
            "check windows version",
            "free up disk space",
            "take a screenshot",
            "make text bigger",
            "beginner",
        )
    ):
        return "beginner_guide"
    return "symptom_fix"


def infer_korea_article_type(text: str) -> str:
    if any(token in text for token in (" vs ", "compare", "comparison", "which", "best", "where to stay")):
        return "comparison"
    if any(token in text for token in ("checklist", "before", "mistake", "tips", "what to know", "esim", "t-money")):
        return "checklist"
    return "how_to"


def preferred_article_type_order(content_domain: str) -> tuple[str, ...]:
    if content_domain == "windows_help":
        return WINDOWS_ARTICLE_TYPE_ORDER
    return KOREA_ARTICLE_TYPE_ORDER
