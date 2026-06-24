from __future__ import annotations

import re


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def title_case_keyword(keyword: str) -> str:
    small_words = {"to", "in", "for", "as", "a", "an", "the", "and", "or", "of"}
    words = clean_space(keyword).split(" ")
    titled = []
    for index, word in enumerate(words):
        lower = word.lower()
        if index > 0 and lower in small_words:
            titled.append(lower)
        else:
            titled.append(lower.capitalize())
    return " ".join(titled)
