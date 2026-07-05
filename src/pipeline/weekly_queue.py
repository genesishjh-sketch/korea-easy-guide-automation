from __future__ import annotations

import argparse
from datetime import date
from datetime import datetime
from datetime import timedelta
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR
from src.config import load_settings
from src.content.article_types import infer_article_type
from src.content.topic_scoring import infer_category
from src.notifications.telegram import NotificationClient
from src.pipeline.daily_draft import choose_publish_seed_candidates
from src.pipeline.daily_draft import normalize_match_text
from src.pipeline.daily_draft import seed_quality_precheck
from src.pipeline.daily_draft import title_matches_existing
from src.pipeline.daily_draft import used_keywords
from src.publishing.blogger import BloggerPublisher


KST = ZoneInfo("Asia/Seoul")
QUEUE_DIR = ROOT_DIR / "data" / "plans"
MIN_TITLE_SIMILARITY = 0.72
MIN_TOPIC_OVERLAP = 0.82
READY_PRECHECK_STATUSES = {"ready", "not_applicable"}
BLOCKED_STATUSES = {"published", "skipped", "failed"}
EVERGREEN_SLOT = "evergreen"
TREND_SLOT = "trend_or_seasonal"


def default_start_date(now: datetime | None = None) -> date:
    selected_now = now or datetime.now(tz=KST)
    return selected_now.date() + timedelta(days=1)


def iso_week_label(selected_date: date) -> str:
    year, week, _ = selected_date.isocalendar()
    return f"{year}-W{week:02d}"


def weekly_queue_path(site: str, selected_date: date | None = None) -> Path:
    target_date = selected_date or default_start_date()
    return QUEUE_DIR / f"{site}_weekly_queue_{iso_week_label(target_date)}.json"


def load_weekly_queue(site: str, selected_date: date | None = None) -> dict | None:
    target_date = selected_date or datetime.now(tz=KST).date()
    candidates = [weekly_queue_path(site, target_date)]
    if QUEUE_DIR.exists():
        candidates.extend(sorted(QUEUE_DIR.glob(f"{site}_weekly_queue_*.json"), reverse=True))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        queue = json.loads(path.read_text(encoding="utf-8"))
        start = date.fromisoformat(queue["start_date"])
        end = date.fromisoformat(queue["end_date"])
        if start <= target_date <= end:
            queue["_path"] = str(path)
            return queue
    return None


def today_queue_candidates(site: str, selected_date: date | None = None, max_posts: int = 3) -> list[dict]:
    target_date = selected_date or datetime.now(tz=KST).date()
    queue = load_weekly_queue(site, target_date)
    if not queue:
        return []

    items = [
        item
        for item in queue.get("items", [])
        if item.get("date") == target_date.isoformat() and item.get("status", "scheduled") not in BLOCKED_STATUSES
    ]
    return [candidate_from_queue_item(queue, item) for item in items[:max_posts]]


def candidate_from_queue_item(queue: dict, item: dict) -> dict:
    return {
        "seed": item["seed"],
        "category": item.get("category", ""),
        "article_type": item.get("article_type", ""),
        "quality_precheck": item.get("quality_precheck") or {"status": "ready"},
        "recent_category": False,
        "weekly_queue": {
            "week": queue.get("week"),
            "path": queue.get("_path"),
            "date": item.get("date"),
            "slot_strategy": item.get("slot_strategy", EVERGREEN_SLOT),
            "strategy_reason": item.get("strategy_reason", ""),
            "difference_from_existing": item.get("difference_from_existing", ""),
            "avoid_overlap_with": item.get("avoid_overlap_with", []),
            "image_direction": item.get("image_direction", ""),
        },
    }


def generate_weekly_queue(
    site: str | None = None,
    start_date: date | None = None,
    days: int = 7,
    posts_per_day: int = 1,
    notify: bool = True,
) -> dict:
    settings = load_settings(site)
    selected_start = start_date or default_start_date()
    publish_used = used_keywords(settings.site_key, include_validation=False)
    generated_used = used_keywords(settings.site_key, include_validation=True)
    existing_titles = public_post_titles(settings.site_key)
    existing_topics = [normalize_match_text(title) for title in existing_titles]
    max_precheck = int(os.getenv("WEEKLY_QUEUE_MAX_PRECHECK", "80"))

    candidates: list[dict] = []
    selected_topic_texts: list[str] = []
    for seed in choose_publish_seed_candidates(None, settings.site_key)[:max_precheck]:
        normalized_seed = seed.casefold()
        if normalized_seed in publish_used or normalized_seed in generated_used:
            continue
        if is_too_close_to_existing(seed, existing_titles, existing_topics):
            continue
        if is_too_close_to_selected(seed, selected_topic_texts):
            continue

        category = infer_category(seed, settings.content_domain)
        article_type = infer_article_type(seed, category, settings.content_domain)
        precheck = seed_quality_precheck(seed, settings.content_domain)
        if precheck.get("status") not in READY_PRECHECK_STATUSES:
            continue

        overlaps = closest_topics(seed, existing_titles, limit=3)
        slot_strategy, strategy_reason = classify_slot_strategy(seed, category, article_type, settings.content_domain)
        candidates.append(
            {
                "seed": seed,
                "category": category,
                "article_type": article_type,
                "slot_strategy": slot_strategy,
                "strategy_reason": strategy_reason,
                "quality_precheck": precheck,
                "avoid_overlap_with": [item["title"] for item in overlaps],
                "difference_from_existing": difference_note(seed, overlaps, settings.content_domain),
                "image_direction": image_direction(seed, category, article_type, settings.content_domain),
            }
        )
        selected_topic_texts.append(normalize_match_text(seed))

    items = assign_candidates_to_week(candidates, selected_start, days, posts_per_day, settings.site_key)
    queue = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "week": iso_week_label(selected_start),
        "created_at": datetime.now(tz=KST).isoformat(),
        "start_date": selected_start.isoformat(),
        "end_date": (selected_start + timedelta(days=days - 1)).isoformat(),
        "days": days,
        "posts_per_day": posts_per_day,
        "status": "approved",
        "duplicate_policy": {
            "title_similarity_block": MIN_TITLE_SIMILARITY,
            "topic_overlap_block": MIN_TOPIC_OVERLAP,
            "published_and_generated_history_checked": True,
            "weekly_selected_topics_checked": True,
        },
        "topic_mix_policy": topic_mix_policy(posts_per_day),
        "items": items,
        "candidate_pool_count": len(candidates),
    }
    path = save_weekly_queue(queue)
    queue["_path"] = str(path)
    if notify:
        NotificationClient(settings).send(build_weekly_queue_message(queue))
    return queue


def assign_candidates_to_week(
    candidates: list[dict],
    start_date: date,
    days: int,
    posts_per_day: int,
    site: str,
) -> list[dict]:
    items: list[dict] = []
    used_indexes: set[int] = set()
    previous_category = ""
    slots = [
        {
            "date": start_date + timedelta(days=offset),
            "slot_number": slot_number + 1,
            "slot_strategy": slot_strategy_for(slot_number, posts_per_day),
        }
        for offset in range(days)
        for slot_number in range(posts_per_day)
    ]

    for slot in slots:
        candidate_index = next_candidate_index(
            candidates,
            used_indexes,
            previous_category,
            preferred_strategy=slot["slot_strategy"],
        )
        if candidate_index is None:
            break
        used_indexes.add(candidate_index)
        candidate = candidates[candidate_index]
        previous_category = candidate["category"]
        planned_strategy = slot["slot_strategy"]
        actual_strategy = candidate.get("slot_strategy", EVERGREEN_SLOT)
        items.append(
            {
                "date": slot["date"].isoformat(),
                "site": site,
                "slot_number": slot["slot_number"],
                "slot_strategy": planned_strategy,
                "actual_topic_strategy": actual_strategy,
                "strategy_reason": candidate.get("strategy_reason", ""),
                "strategy_fallback": planned_strategy != actual_strategy,
                "seed": candidate["seed"],
                "topic": candidate["seed"],
                "category": candidate["category"],
                "article_type": candidate["article_type"],
                "intent": candidate["article_type"],
                "difference_from_existing": candidate["difference_from_existing"],
                "avoid_overlap_with": candidate["avoid_overlap_with"],
                "image_direction": candidate["image_direction"],
                "quality_precheck": candidate["quality_precheck"],
                "status": "scheduled",
            }
        )
    return items


def next_candidate_index(
    candidates: list[dict],
    used_indexes: set[int],
    previous_category: str,
    preferred_strategy: str | None = None,
) -> int | None:
    if preferred_strategy:
        for index, candidate in enumerate(candidates):
            if (
                index not in used_indexes
                and candidate.get("slot_strategy", EVERGREEN_SLOT) == preferred_strategy
                and candidate["category"] != previous_category
            ):
                return index
        for index, candidate in enumerate(candidates):
            if index not in used_indexes and candidate.get("slot_strategy", EVERGREEN_SLOT) == preferred_strategy:
                return index

    for index, candidate in enumerate(candidates):
        if index not in used_indexes and candidate["category"] != previous_category:
            return index
    for index, _candidate in enumerate(candidates):
        if index not in used_indexes:
            return index
    return None


def slot_strategy_for(slot_number_zero_based: int, posts_per_day: int) -> str:
    if posts_per_day >= 3 and slot_number_zero_based == 2:
        return TREND_SLOT
    return EVERGREEN_SLOT


def topic_mix_policy(posts_per_day: int) -> dict:
    if posts_per_day >= 3:
        return {
            "daily_slots": [
                {"slot_number": 1, "slot_strategy": EVERGREEN_SLOT, "purpose": "stable search demand"},
                {"slot_number": 2, "slot_strategy": EVERGREEN_SLOT, "purpose": "stable search demand"},
                {"slot_number": 3, "slot_strategy": TREND_SLOT, "purpose": "seasonal, recent-update, or issue-sensitive demand"},
            ],
            "note": "If no safe trend/seasonal candidate passes duplicate and quality checks, the slot falls back to evergreen.",
        }
    return {
        "daily_slots": [
            {"slot_number": index + 1, "slot_strategy": EVERGREEN_SLOT, "purpose": "stable search demand"}
            for index in range(posts_per_day)
        ],
        "note": "Trend/seasonal slots start when daily cadence is at least three posts.",
    }


def classify_slot_strategy(seed: str, category: str, article_type: str, content_domain: str) -> tuple[str, str]:
    text = f"{seed} {category} {article_type}".casefold()
    if content_domain == "windows_help":
        trend_tokens = (
            "after update",
            "latest",
            "cumulative update",
            "security update",
            "after windows update",
            "blue screen after",
            "slow after update",
            "pending restart",
            "download stuck",
            "install error",
        )
        if any(token in text for token in trend_tokens):
            return TREND_SLOT, "Windows update or recent-issue demand"
        return EVERGREEN_SLOT, "Evergreen Windows beginner/search problem"

    seasonal_tokens = (
        "season",
        "rainy season",
        "heavy rain",
        "summer",
        "winter",
        "spring",
        "fall",
        "autumn",
        "cherry blossom",
        "foliage",
        "chuseok",
        "seollal",
        "holiday",
        "public holidays",
        "night arrival",
        "late night",
        "airport pickup",
        "emergency",
        "lose passport",
    )
    if any(token in text for token in seasonal_tokens):
        return TREND_SLOT, "Korea seasonal, trip-timing, or urgent travel demand"
    return EVERGREEN_SLOT, "Evergreen Korea travel/living demand"


def save_weekly_queue(queue: dict) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = weekly_queue_path(queue["site"], date.fromisoformat(queue["start_date"]))
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def public_post_titles(site: str) -> list[str]:
    try:
        settings = load_settings(site)
        return [post.get("title", "") for post in BloggerPublisher(settings).list_live_posts()]
    except Exception:
        return []


def is_too_close_to_existing(seed: str, existing_titles: list[str], existing_topics: list[str]) -> bool:
    normalized_seed = normalize_match_text(seed)
    if any(title_matches_existing(normalized_seed, title) for title in existing_titles):
        return True
    return any(topic_similarity(normalized_seed, topic) >= MIN_TITLE_SIMILARITY for topic in existing_topics)


def is_too_close_to_selected(seed: str, selected_topics: list[str]) -> bool:
    normalized_seed = normalize_match_text(seed)
    return any(topic_similarity(normalized_seed, topic) >= MIN_TOPIC_OVERLAP for topic in selected_topics)


def topic_similarity(left: str, right: str) -> float:
    left_tokens = topic_tokens(left)
    right_tokens = topic_tokens(right)
    if not left_tokens or not right_tokens:
        return SequenceMatcher(None, left, right).ratio()
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    ratio = SequenceMatcher(None, left, right).ratio()
    return max(overlap, ratio)


def topic_tokens(text: str) -> set[str]:
    normalized = normalize_match_text(text)
    return {token for token in normalized.split() if len(token) >= 3}


def closest_topics(seed: str, titles: list[str], limit: int = 3) -> list[dict]:
    normalized_seed = normalize_match_text(seed)
    unique_titles = list(dict.fromkeys(title for title in titles if title))
    scored = [
        {"title": title, "score": round(topic_similarity(normalized_seed, normalize_match_text(title)), 3)}
        for title in unique_titles
    ]
    return [item for item in sorted(scored, key=lambda item: item["score"], reverse=True)[:limit] if item["score"] >= 0.28]


def difference_note(seed: str, overlaps: list[dict], content_domain: str) -> str:
    if not overlaps:
        return "New angle with no close published title found."
    closest = overlaps[0]["title"]
    if content_domain == "windows_help":
        return f"Keep this article focused on '{seed}' only; do not reuse the troubleshooting path from '{closest}'."
    return f"Keep this article focused on '{seed}' only; do not repeat the travel decisions already covered in '{closest}'."


def image_direction(seed: str, category: str, article_type: str, content_domain: str) -> str:
    if content_domain == "windows_help":
        return (
            f"Create distinct beginner PC help visuals for '{seed}'. Use a different scene, composition, color mood, "
            f"and troubleshooting object than recent posts; avoid repeating generic laptop-on-desk or Wi-Fi router imagery."
        )
    return (
        f"Create distinct Korea travel guide visuals for '{seed}'. Use topic-specific locations, tools, signs, tickets, "
        f"or app-like abstract scenes; avoid repeating the same cover composition across transportation, shopping, and apps."
    )


def build_weekly_queue_message(queue: dict) -> str:
    lines = [
        "[Posting Bot] 주간 주제 계획 생성",
        "",
        f"- 블로그: {queue.get('site_name')}",
        f"- 기간: {queue.get('start_date')} ~ {queue.get('end_date')}",
        f"- 목표: 하루 {queue.get('posts_per_day')}개, 총 {len(queue.get('items') or [])}개",
        "- 주제 믹스: 하루 3개 기준 스테디 2개 + 이슈/시즌 1개",
        f"- 중복 검사: 기존 발행/생성 이력 + 이번 주 선택 주제",
        "",
        "발행 예정:",
    ]
    for item in queue.get("items", []):
        strategy = item.get("slot_strategy", EVERGREEN_SLOT)
        fallback = " fallback" if item.get("strategy_fallback") else ""
        lines.append(
            f"- {item.get('date')} #{item.get('slot_number', '-')}: {item.get('seed')} "
            f"({strategy}{fallback} / {item.get('category')} / {item.get('article_type')})"
        )
    if not queue.get("items"):
        lines.extend(["", "주의: 조건을 통과한 주제가 없어 이번 주 큐가 비었습니다."])
    return "\n".join(lines)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a weekly topic queue for automated Blogger publishing.")
    parser.add_argument("--site", required=True, help="Site profile key, for example: korea_easy_guide")
    parser.add_argument("--start-date", help="YYYY-MM-DD. Defaults to tomorrow in Asia/Seoul.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--posts-per-day", type=int, default=int(os.getenv("WEEKLY_QUEUE_POSTS_PER_DAY", "1")))
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    queue = generate_weekly_queue(
        site=args.site,
        start_date=parse_date(args.start_date),
        days=args.days,
        posts_per_day=args.posts_per_day,
        notify=not args.no_notify,
    )
    print(json.dumps(queue, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
