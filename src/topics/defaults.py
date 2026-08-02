from __future__ import annotations

from src.topics.ids import category_id_for
from src.topics.models import CategoryRecord


DEFAULT_CATEGORY_NAMES = {
    "korea_easy_guide": [
        "Transportation",
        "Mobile & Internet",
        "Apps in Korea",
        "Food & Delivery",
        "Accommodation",
        "Travel Basics",
    ],
    "easy_pc_fix_guide": [
        "Wi-Fi & Internet",
        "Bluetooth & Devices",
        "Sound & Microphone",
        "Printer & Scanner",
        "Boot & Recovery",
        "File Explorer",
        "Windows Search",
        "OneDrive & Account",
        "Apps & Settings",
        "Beginner PC Tips",
        "Windows Update",
        "Error Codes",
        "Computer Help",
    ],
}


def default_categories(site: str) -> list[CategoryRecord]:
    names = DEFAULT_CATEGORY_NAMES.get(site)
    if names is None:
        raise ValueError(f"No default categories configured for {site}")
    return [
        CategoryRecord(
            category_id=category_id_for(site, name),
            site=site,
            name=name,
            blogger_label=name,
        )
        for name in names
    ]


def default_category_id(site: str, name: str) -> str:
    return category_id_for(site, name)
