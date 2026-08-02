from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import is_dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from difflib import SequenceMatcher
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any
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
DEFAULT_TOPIC_BOARD_MODE = "shadow"
TOPIC_BOARD_MODES = {"ready_first", "registry_only", "shadow", "legacy"}
NEW_POST_ACTION = "NEW_POST"
MAINTENANCE_ACTIONS = {"UPDATE_EXISTING", "FAQ_ADD"}
MAINTENANCE_STATUSES = {"READY", "UPDATE_DUE"}
MAX_WEEKLY_MAINTENANCE_ITEMS = 2


class MaintenanceReconciliationRequired(RuntimeError):
    """A Blogger update may have happened and must not be sent again."""

    reconciliation_only = True


def default_start_date(now: datetime | None = None) -> date:
    selected_now = now or datetime.now(tz=KST)
    selected_date = selected_now.astimezone(KST).date() if selected_now.tzinfo else selected_now.date()
    days_until_monday = (7 - selected_date.weekday()) % 7
    return selected_date + timedelta(days=days_until_monday)


def iso_week_label(selected_date: date) -> str:
    year, week, _ = selected_date.isocalendar()
    return f"{year}-W{week:02d}"


def weekly_queue_path(site: str, selected_date: date | None = None) -> Path:
    target_date = selected_date or default_start_date()
    return QUEUE_DIR / f"{site}_weekly_queue_{iso_week_label(target_date)}.json"


def maintenance_queue_path(site: str, selected_date: date | None = None) -> Path:
    target_date = selected_date or default_start_date()
    return QUEUE_DIR / f"{site}_maintenance_queue_{iso_week_label(target_date)}.json"


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


def today_queue_candidates(site: str, selected_date: date | None = None, max_posts: int = 1) -> list[dict]:
    target_date = selected_date or datetime.now(tz=KST).date()
    queue = load_weekly_queue(site, target_date)
    if not queue:
        return []

    items = [
        item
        for item in queue.get("items", [])
        if item.get("date") == target_date.isoformat() and item.get("status", "scheduled") not in BLOCKED_STATUSES
    ]
    store = load_topic_store()
    registry_provenance_valid = queue_registry_provenance_valid(
        queue,
        site,
        store,
    )
    selected: list[dict] = []
    seen_topic_ids: set[str] = set()
    for item in items:
        candidate = candidate_from_queue_item(queue, item)
        topic_id = str(candidate.get("topic_id") or "")
        if topic_id:
            if not registry_provenance_valid:
                continue
            if topic_id in seen_topic_ids:
                continue
            is_valid, candidate = revalidate_registry_candidate(candidate, site, store=store)
            if not is_valid:
                continue
            seen_topic_ids.add(topic_id)
        selected.append(candidate)
        if len(selected) >= max_posts:
            break
    return selected


def queue_registry_provenance_valid(queue: dict, site: str, store) -> bool:
    """Fail closed when an AI queue is detached from its completed research run."""

    if store is None:
        return False
    state = topic_rollout_state(store, site)
    if str(state.get("mode") or "").upper() != "READY_FIRST":
        return False
    if str(state.get("last_status") or "").upper() != "SUCCESS":
        return False
    if not bool((state.get("backfill") or {}).get("complete")):
        return False
    research_run_id = str(queue.get("research_run_id") or "")
    if not research_run_id or research_run_id != str(state.get("last_run_id") or ""):
        return False
    if str(queue.get("rollout_mode") or "").upper() != "READY_FIRST":
        return False
    try:
        queued_revision = int(queue.get("registry_revision") or 0)
        current_revision = int(store._load_registry(site).get("revision") or 0)
    except Exception:
        return False
    return queued_revision > 0 and current_revision >= queued_revision


def candidate_from_queue_item(queue: dict, item: dict) -> dict:
    return {
        "seed": item["seed"],
        "category": item.get("category", ""),
        "topic_id": item.get("topic_id", ""),
        "cluster_id": item.get("cluster_id", ""),
        "category_id": item.get("category_id", ""),
        "action": item.get("action") or item.get("topic_action") or NEW_POST_ACTION,
        "topic_action": item.get("topic_action") or item.get("action") or NEW_POST_ACTION,
        "revision": item.get("revision") or item.get("topic_revision") or 0,
        "topic_revision": item.get("topic_revision") or item.get("revision") or 0,
        "editor_brief": item.get("editor_brief") or {},
        "reader_questions": list(item.get("reader_questions") or []),
        "difference_from_existing": item.get("difference_from_existing", ""),
        "existing_post_refs": list(item.get("existing_post_refs") or []),
        "topic_source": item.get("topic_source", "legacy"),
        "registry_status": item.get("registry_status", ""),
        "claim_run_id": item.get("claim_run_id", ""),
        "article_type": item.get("article_type", ""),
        "quality_precheck": item.get("quality_precheck") or {"status": "ready"},
        "recent_category": False,
        "weekly_queue": {
            "week": queue.get("week"),
            "path": queue.get("_path"),
            "research_run_id": queue.get("research_run_id", ""),
            "research_run_at": queue.get("research_run_at", ""),
            "registry_revision": queue.get("registry_revision", 0),
            "source_commit_sha": queue.get("source_commit_sha", ""),
            "rollout_mode": queue.get("rollout_mode", ""),
            "date": item.get("date"),
            "slot_strategy": item.get("slot_strategy", EVERGREEN_SLOT),
            "strategy_reason": item.get("strategy_reason", ""),
            "difference_from_existing": item.get("difference_from_existing", ""),
            "avoid_overlap_with": item.get("avoid_overlap_with", []),
            "image_direction": item.get("image_direction", ""),
            "topic_source": item.get("topic_source", queue.get("topic_source", "legacy")),
            "topic_revision": item.get("revision", 0),
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
    published_topic_ids = locally_published_topic_ids(settings.site_key)
    existing_titles = public_post_titles(settings.site_key)
    existing_topics = [normalize_match_text(title) for title in existing_titles]
    max_precheck = int(os.getenv("WEEKLY_QUEUE_MAX_PRECHECK", "80"))
    store = load_topic_store()
    reservation_sweep = sweep_topic_reservations(store, settings.site_key)
    rollout_state = topic_rollout_state(store, settings.site_key) if store is not None else {}
    rollout_degraded = topic_rollout_is_degraded(rollout_state)
    selection_mode = topic_board_mode(settings.site_key, store=store)
    registry_revision = 0
    if store is not None:
        try:
            registry_revision = int(
                store._load_registry(settings.site_key).get("revision") or 0
            )
        except Exception:
            registry_revision = 0
    research_run_id = str(rollout_state.get("last_run_id") or "")
    research_run_at = str(rollout_state.get("last_run_at") or "")
    source_commit_sha = str(
        os.getenv("SOURCE_COMMIT_SHA")
        or os.getenv("GITHUB_SHA")
        or ""
    )
    registry_candidates = (
        list_registry_ready_candidates(
            settings.site_key,
            limit=max_precheck,
            store=store,
            # Selection mode is enforced above. Bypassing the store gate here
            # also lets SHADOW runs measure the READY backlog without using it.
            require_rollout_gate=False,
        )
        if selection_mode != "legacy"
        else []
    )
    legacy_candidates = []
    if selection_mode != "registry_only":
        legacy_candidates = [
            legacy_topic_candidate(seed)
            for seed in choose_publish_seed_candidates(None, settings.site_key)[:max_precheck]
        ]
    if selection_mode == "registry_only":
        source_candidates = registry_candidates
    elif selection_mode == "ready_first":
        source_candidates = registry_candidates + legacy_candidates
    else:
        source_candidates = legacy_candidates

    candidates: list[dict] = []
    selected_topic_texts: list[str] = []
    selected_topic_ids: set[str] = set()
    for source_candidate in source_candidates:
        seed = str(source_candidate.get("seed") or "").strip()
        if not seed:
            continue
        normalized_seed = seed.casefold()
        topic_id = str(source_candidate.get("topic_id") or "")
        if topic_id and (topic_id in selected_topic_ids or topic_id in published_topic_ids):
            continue
        if normalize_topic_action(source_candidate.get("action")) != NEW_POST_ACTION:
            continue
        if topic_has_publication(source_candidate):
            continue
        if normalized_seed in publish_used or normalized_seed in generated_used:
            continue
        if is_too_close_to_existing(seed, existing_titles, existing_topics):
            continue
        if is_too_close_to_selected(seed, selected_topic_texts):
            continue

        category = str(source_candidate.get("category") or infer_category(seed, settings.content_domain))
        article_type = str(
            source_candidate.get("article_type")
            or infer_article_type(seed, category, settings.content_domain)
        )
        precheck = seed_quality_precheck(seed, settings.content_domain)
        if precheck.get("status") not in READY_PRECHECK_STATUSES:
            continue

        overlaps = closest_topics(seed, existing_titles, limit=3)
        slot_strategy, strategy_reason = classify_slot_strategy(seed, category, article_type, settings.content_domain)
        existing_post_refs = list(source_candidate.get("existing_post_refs") or [])
        referenced_titles = [
            str(item.get("title") or "")
            for item in existing_post_refs
            if isinstance(item, dict) and item.get("title")
        ]
        candidates.append(
            {
                "seed": seed,
                "category": category,
                "topic_id": topic_id,
                "cluster_id": source_candidate.get("cluster_id", ""),
                "category_id": source_candidate.get("category_id", ""),
                "action": NEW_POST_ACTION,
                "topic_action": NEW_POST_ACTION,
                "revision": source_candidate.get("revision", 0),
                "topic_revision": source_candidate.get("revision", 0),
                "editor_brief": source_candidate.get("editor_brief") or {},
                "reader_questions": list(source_candidate.get("reader_questions") or []),
                "existing_post_refs": existing_post_refs,
                "topic_source": source_candidate.get("topic_source", "legacy"),
                "registry_status": source_candidate.get("registry_status", ""),
                "article_type": article_type,
                "slot_strategy": slot_strategy,
                "strategy_reason": strategy_reason,
                "quality_precheck": precheck,
                "avoid_overlap_with": list(
                    dict.fromkeys([*referenced_titles, *[item["title"] for item in overlaps]])
                ),
                "difference_from_existing": (
                    source_candidate.get("difference_from_existing")
                    or difference_note(seed, overlaps, settings.content_domain)
                ),
                "image_direction": image_direction(seed, category, article_type, settings.content_domain),
            }
        )
        selected_topic_texts.append(normalize_match_text(seed))
        if topic_id:
            selected_topic_ids.add(topic_id)

    items = assign_candidates_to_week(candidates, selected_start, days, posts_per_day, settings.site_key)
    items, scheduling_failures = schedule_registry_items(
        items,
        candidates,
        selected_start,
        days,
        posts_per_day,
        settings.site_key,
        store,
    )
    maintenance_enabled, maintenance_hold_reason = maintenance_rollout_gate(
        store,
        settings.site_key,
        selection_mode=selection_mode,
    )
    maintenance_queue = generate_maintenance_queue(
        settings.site_key,
        selected_start,
        store=store,
        max_items=MAX_WEEKLY_MAINTENANCE_ITEMS,
        enabled=maintenance_enabled,
        hold_reason=maintenance_hold_reason,
    )
    registry_selected_count = sum(1 for item in items if item.get("topic_source") == "registry")
    legacy_selected_count = sum(1 for item in items if item.get("topic_source") == "legacy")
    fallback_reason = ""
    if rollout_degraded:
        queue_status = "DEGRADED"
        fallback_reason = (
            "registry_degraded_ready_backlog"
            if selection_mode == "ready_first"
            else "registry_degraded_legacy_fallback"
        )
    elif selection_mode in {"ready_first", "registry_only"} and not registry_candidates:
        queue_status = "DEGRADED"
        fallback_reason = "registry_ready_empty"
    elif scheduling_failures:
        queue_status = "DEGRADED"
        fallback_reason = "registry_schedule_transition_failed"
    elif selection_mode == "shadow":
        queue_status = "SHADOW"
        fallback_reason = "rollout_shadow_uses_legacy"
    else:
        queue_status = "approved"
    queue = {
        "site": settings.site_key,
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "week": iso_week_label(selected_start),
        "research_run_id": research_run_id,
        "research_run_at": research_run_at,
        "registry_revision": registry_revision,
        "source_commit_sha": source_commit_sha,
        "rollout_mode": str(rollout_state.get("mode") or ""),
        "created_at": datetime.now(tz=KST).isoformat(),
        "start_date": selected_start.isoformat(),
        "end_date": (selected_start + timedelta(days=days - 1)).isoformat(),
        "days": days,
        "posts_per_day": posts_per_day,
        "status": queue_status,
        "fallback_reason": fallback_reason,
        "duplicate_policy": {
            "title_similarity_block": MIN_TITLE_SIMILARITY,
            "topic_overlap_block": MIN_TOPIC_OVERLAP,
            "published_and_generated_history_checked": True,
            "weekly_selected_topics_checked": True,
        },
        "topic_mix_policy": topic_mix_policy(posts_per_day),
        "topic_selection": {
            "mode": selection_mode,
            "rollout_mode": str(rollout_state.get("mode") or ""),
            "research_run_id": research_run_id,
            "research_run_at": research_run_at,
            "registry_revision": registry_revision,
            "source_commit_sha": source_commit_sha,
            "backfill_complete": bool(
                (rollout_state.get("backfill") or {}).get("complete")
            ),
            "registry_available": store is not None,
            "registry_ready_count": len(registry_candidates),
            "selected_source": (
                "registry"
                if registry_selected_count and not legacy_selected_count
                else "legacy"
                if legacy_selected_count and not registry_selected_count
                else "mixed"
                if items
                else "none"
            ),
            "fallback_source": "legacy" if fallback_reason and legacy_selected_count else "",
            "fallback_reason": fallback_reason,
            "registry_selected_count": registry_selected_count,
            "legacy_selected_count": legacy_selected_count,
            "shadow_registry_count": len(registry_candidates) if selection_mode == "shadow" else 0,
            "scheduling_failures": scheduling_failures,
            "reservation_sweep": reservation_sweep,
        },
        "maintenance_queue": {
            "path": maintenance_queue.get("_path", ""),
            "item_count": len(maintenance_queue.get("items") or []),
            "max_items_per_site_week": MAX_WEEKLY_MAINTENANCE_ITEMS,
            "status": maintenance_queue.get("status", ""),
            "hold_reason": maintenance_queue.get("hold_reason", ""),
        },
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
    schedule_expires_at = datetime.combine(
        start_date + timedelta(days=days),
        datetime.min.time(),
        tzinfo=KST,
    ).isoformat()
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
                "topic_id": candidate.get("topic_id", ""),
                "cluster_id": candidate.get("cluster_id", ""),
                "category_id": candidate.get("category_id", ""),
                "action": candidate.get("action", NEW_POST_ACTION),
                "topic_action": candidate.get("action", NEW_POST_ACTION),
                "revision": candidate.get("revision", 0),
                "topic_revision": candidate.get("revision", 0),
                "editor_brief": candidate.get("editor_brief") or {},
                "reader_questions": list(candidate.get("reader_questions") or []),
                "existing_post_refs": list(candidate.get("existing_post_refs") or []),
                "topic_source": candidate.get("topic_source", "legacy"),
                "registry_status": candidate.get("registry_status", ""),
                "article_type": candidate["article_type"],
                "intent": candidate["article_type"],
                "difference_from_existing": candidate["difference_from_existing"],
                "avoid_overlap_with": candidate["avoid_overlap_with"],
                "image_direction": candidate["image_direction"],
                "quality_precheck": candidate["quality_precheck"],
                "schedule_expires_at": schedule_expires_at,
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


def schedule_registry_items(
    items: list[dict],
    candidates: list[dict],
    start_date: date,
    days: int,
    posts_per_day: int,
    site: str,
    store,
) -> tuple[list[dict], list[dict]]:
    selected_items = list(items)
    available_candidates = list(candidates)
    scheduled_records: dict[str, dict] = {}
    failures: list[dict] = []

    while True:
        failed_topic_ids: set[str] = set()
        for item in selected_items:
            topic_id = str(item.get("topic_id") or "")
            if not topic_id or item.get("topic_source") != "registry":
                continue
            if topic_id in scheduled_records:
                scheduled = scheduled_records[topic_id]
                item["revision"] = scheduled.get("revision", item.get("revision", 0))
                item["topic_revision"] = item["revision"]
                item["registry_status"] = "SCHEDULED"
                continue
            scheduled = mark_topic_scheduled(store, site, item)
            if scheduled is not None:
                scheduled_records[topic_id] = scheduled
                item["revision"] = scheduled.get("revision", item.get("revision", 0))
                item["topic_revision"] = item["revision"]
                item["registry_status"] = "SCHEDULED"
                continue
            failed_topic_ids.add(topic_id)
            failures.append(
                {
                    "topic_id": topic_id,
                    "revision": item.get("revision", 0),
                    "reason": "registry_schedule_transition_failed",
                }
            )
        if not failed_topic_ids:
            release_orphaned_schedules(
                store,
                site,
                scheduled_records,
                selected_items,
            )
            return selected_items, failures
        available_candidates = [
            candidate
            for candidate in available_candidates
            if str(candidate.get("topic_id") or "") not in failed_topic_ids
        ]
        replacement_items = assign_candidates_to_week(
            available_candidates,
            start_date,
            days,
            posts_per_day,
            site,
        )
        if replacement_items == selected_items:
            final_items = [
                item
                for item in selected_items
                if str(item.get("topic_id") or "") not in failed_topic_ids
            ]
            release_orphaned_schedules(
                store,
                site,
                scheduled_records,
                final_items,
            )
            return final_items, failures
        selected_items = replacement_items


def mark_topic_scheduled(store, site: str, item: dict) -> dict | None:
    topic_id = str(item.get("topic_id") or "")
    if not topic_id or store is None:
        return None
    method = getattr(store, "mark_topic_status", None)
    if not callable(method):
        return None
    try:
        from src.topics.models import TopicStatus

        status = TopicStatus.SCHEDULED
    except (ImportError, AttributeError):
        status = "SCHEDULED"
    try:
        result = method(
            site,
            topic_id,
            status,
            reason=(
                f"Scheduled for {item.get('date')} in weekly queue "
                f"at revision {item.get('revision', 0)}."
            ),
            expected_revision=normalize_revision(item.get("revision")),
        )
    except TypeError:
        try:
            result = method(
                site,
                topic_id,
                status,
                reason=(
                    f"Scheduled for {item.get('date')} in weekly queue "
                    f"at revision {item.get('revision', 0)}."
                ),
            )
        except Exception:
            return None
    except Exception:
        return None
    if result is False or result is None:
        return None
    normalized = normalize_topic_record(result)
    if not normalized.get("topic_id"):
        normalized = {
            **item,
            "registry_status": "SCHEDULED",
        }
    record_reservation = getattr(store, "record_schedule_reservation", None)
    if callable(record_reservation):
        try:
            reservation = record_reservation(
                site,
                topic_id,
                expected_revision=normalize_revision(
                    normalized.get("revision") or item.get("revision")
                ),
                scheduled_for=str(item.get("date") or ""),
                expires_at=str(item.get("schedule_expires_at") or ""),
            )
            if isinstance(reservation, dict):
                normalized["schedule_started_at"] = reservation.get("started_at", "")
                normalized["schedule_expires_at"] = reservation.get("expires_at", "")
        except Exception:
            try:
                method(
                    site,
                    topic_id,
                    "READY",
                    reason="Schedule reservation could not be persisted.",
                    expected_revision=normalize_revision(normalized.get("revision")),
                )
            except Exception:
                pass
            return None
    return normalized


def release_orphaned_schedules(
    store,
    site: str,
    scheduled_records: dict[str, dict],
    selected_items: list[dict],
) -> None:
    selected_ids = {
        str(item.get("topic_id") or "")
        for item in selected_items
        if item.get("topic_source") == "registry"
    }
    method = getattr(store, "mark_topic_status", None) if store is not None else None
    if not callable(method):
        return
    try:
        from src.topics.models import TopicStatus

        ready_status = TopicStatus.READY
    except (ImportError, AttributeError):
        ready_status = "READY"
    for topic_id, record in scheduled_records.items():
        if topic_id in selected_ids:
            continue
        try:
            method(
                site,
                topic_id,
                ready_status,
                reason="Released because the weekly queue was rebalanced.",
                expected_revision=normalize_revision(record.get("revision")),
            )
        except Exception:
            continue


def topic_board_mode(site: str = "", store=None) -> str:
    configured_mode = os.getenv("TOPIC_BOARD_MODE") or os.getenv("TOPIC_REGISTRY_MODE")
    selected_store = store if store is not None else load_topic_store()
    state = (
        topic_rollout_state(selected_store, site)
        if selected_store is not None
        else {}
    )

    if configured_mode:
        requested = normalize_topic_board_mode(configured_mode)
        if requested in {"shadow", "legacy"}:
            return requested
        promoted_and_healthy = bool(state.get("promoted")) and not topic_rollout_is_degraded(
            state
        )
        rollout_mode = normalize_topic_board_mode(
            str(state.get("mode") or state.get("selection_mode") or "")
        )
        if promoted_and_healthy and rollout_mode == "ready_first":
            return requested
        return DEFAULT_TOPIC_BOARD_MODE

    if selected_store is None:
        return DEFAULT_TOPIC_BOARD_MODE
    if not state:
        return DEFAULT_TOPIC_BOARD_MODE

    explicit_mode = state.get("mode") or state.get("selection_mode")
    if topic_rollout_is_degraded(state):
        policy = str(
            state.get("degraded_policy")
            or state.get("fallback_policy")
            or "legacy"
        ).strip().casefold()
        return (
            "legacy"
            if policy in {"legacy", "legacy_only", "disable_registry"}
            else "ready_first"
        )

    if explicit_mode:
        normalized = normalize_topic_board_mode(str(explicit_mode))
        if normalized != DEFAULT_TOPIC_BOARD_MODE or str(explicit_mode).strip().casefold() in {
            "shadow",
            "legacy",
        }:
            return normalized
    if state.get("promoted") or state.get("ready_first_enabled") or state.get("locked"):
        return "ready_first"
    try:
        qualifying_runs = int(
            state.get("qualifying_runs")
            or state.get("consecutive_qualifying_runs")
            or state.get("successful_shadow_runs")
            or state.get("gate_pass_count")
            or 0
        )
        required_runs = int(state.get("required_qualifying_runs") or 2)
    except (TypeError, ValueError):
        qualifying_runs = 0
        required_runs = 2
    return "ready_first" if qualifying_runs >= max(1, required_runs) else "shadow"


def topic_rollout_is_degraded(state: dict) -> bool:
    explicit_mode = state.get("mode") or state.get("selection_mode")
    raw_mode = str(explicit_mode or "").strip().upper()
    health = str(state.get("health") or state.get("status") or "").strip().upper()
    return (
        bool(state.get("degraded"))
        or raw_mode == "DEGRADED"
        or health in {"DEGRADED", "FAILED", "UNHEALTHY"}
    )


def maintenance_rollout_gate(
    store,
    site: str,
    *,
    selection_mode: str | None = None,
) -> tuple[bool, str]:
    """Allow external maintenance only after a healthy rollout promotion."""

    if store is None:
        return False, "topic_registry_unavailable"
    state = topic_rollout_state(store, site)
    if topic_rollout_is_degraded(state):
        return False, "rollout_degraded_reconciliation_hold"
    if not bool(state.get("promoted")):
        return False, "shadow_rollout_not_promoted"
    rollout_mode = normalize_topic_board_mode(
        str(state.get("mode") or state.get("selection_mode") or "")
    )
    selected = normalize_topic_board_mode(
        selection_mode or rollout_mode
    )
    if rollout_mode != "ready_first" or selected not in {
        "ready_first",
        "registry_only",
    }:
        return False, "maintenance_requires_ready_first"
    return True, ""


def normalize_topic_board_mode(value: str) -> str:
    raw_mode = str(value or DEFAULT_TOPIC_BOARD_MODE).strip().casefold()
    aliases = {
        "auto": "ready_first",
        "primary": "ready_first",
        "ready": "ready_first",
        "registry": "ready_first",
        "off": "legacy",
        "disabled": "legacy",
    }
    mode = aliases.get(raw_mode, raw_mode)
    return mode if mode in TOPIC_BOARD_MODES else DEFAULT_TOPIC_BOARD_MODE


def topic_rollout_state(store, site: str) -> dict:
    for method_name in ("get_rollout_state", "rollout_state", "load_rollout_state", "get_rollout_mode"):
        method = getattr(store, method_name, None)
        if not callable(method):
            continue
        try:
            state = method(site)
        except TypeError:
            try:
                state = method()
            except Exception:
                continue
        except Exception:
            continue
        normalized = plain_topic_value(asdict(state) if is_dataclass(state) else state)
        if isinstance(normalized, dict):
            return normalized
        if normalized and method_name == "get_rollout_mode":
            return {"mode": str(normalized)}
    state = getattr(store, "rollout", None)
    normalized = plain_topic_value(asdict(state) if is_dataclass(state) else state)
    return normalized if isinstance(normalized, dict) else {}


def load_topic_store():
    try:
        from src.topics.store import TopicStore

        return TopicStore()
    except (ImportError, OSError, TypeError, ValueError):
        return None


def sweep_topic_reservations(store, site: str) -> list[dict]:
    method = getattr(store, "sweep_expired_reservations", None) if store is not None else None
    if not callable(method):
        return []
    try:
        swept = method(site)
    except Exception:
        return []
    return list(swept or [])


def list_registry_ready_candidates(
    site: str,
    limit: int | None = None,
    store=None,
    *,
    require_rollout_gate: bool = True,
) -> list[dict]:
    selected_store = store if store is not None else load_topic_store()
    if selected_store is None:
        return []
    try:
        records = selected_store.list_ready_topics(
            site,
            limit=limit,
            require_rollout_gate=require_rollout_gate,
        )
    except TypeError:
        try:
            records = selected_store.list_ready_topics(site, limit=limit)
        except TypeError:
            records = selected_store.list_ready_topics(site)
            if limit is not None:
                records = list(records)[:limit]
    except Exception:
        return []

    candidates = []
    for record in records or []:
        candidate = normalize_topic_record(record)
        candidate["category"] = resolve_topic_category_label(
            selected_store,
            site,
            candidate.get("category_id", ""),
            candidate.get("category", ""),
        )
        if not candidate.get("seed") or not candidate.get("topic_id"):
            continue
        if normalize_topic_status(candidate.get("registry_status")) != "READY":
            continue
        if normalize_topic_action(candidate.get("action")) != NEW_POST_ACTION:
            continue
        if topic_has_publication(candidate):
            continue
        candidates.append(candidate)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def legacy_topic_candidate(seed: str) -> dict:
    return {
        "seed": seed,
        "topic_id": "",
        "cluster_id": "",
        "category_id": "",
        "category": "",
        "action": NEW_POST_ACTION,
        "topic_action": NEW_POST_ACTION,
        "revision": 0,
        "topic_revision": 0,
        "editor_brief": {},
        "reader_questions": [],
        "difference_from_existing": "",
        "existing_post_refs": [],
        "publication_refs": [],
        "topic_source": "legacy",
        "registry_status": "",
        "claim_run_id": "",
    }


def normalize_topic_record(record: Any) -> dict:
    payload = plain_topic_value(asdict(record) if is_dataclass(record) else record)
    if not isinstance(payload, dict):
        payload = {}

    def value(*names: str, default=None):
        for name in names:
            if name in payload and payload[name] is not None:
                return payload[name]
            if hasattr(record, name):
                selected = plain_topic_value(getattr(record, name))
                if selected is not None:
                    return selected
        return default

    seed = value(
        "canonical_topic",
        "canonical_title",
        "topic",
        "seed",
        "title",
        "primary_question",
        default="",
    )
    category_id = str(value("category_id", default="") or "")
    category = value("category_label", "blogger_label", "category_name", "category", default="")
    if str(category or "") == category_id:
        category = ""
    editor_brief = value("editor_brief", default={})
    if isinstance(editor_brief, str):
        editor_brief = {"summary": editor_brief}
    elif not isinstance(editor_brief, dict):
        editor_brief = {}
    reader_questions = value("reader_questions", default=[])
    existing_post_refs = value(
        "existing_post_refs",
        "matched_post_refs",
        "matched_posts",
        default=[],
    )
    publication_refs = value(
        "publication_refs",
        "publications",
        "published_posts",
        default=[],
    )
    return {
        "seed": str(seed or "").strip(),
        "topic_id": str(value("topic_id", "id", default="") or ""),
        "cluster_id": str(value("cluster_id", default="") or ""),
        "category_id": category_id,
        "category": str(category or ""),
        "action": normalize_topic_action(value("action", "topic_action", default=NEW_POST_ACTION)),
        "topic_action": normalize_topic_action(value("topic_action", "action", default=NEW_POST_ACTION)),
        "revision": normalize_revision(value("revision", "topic_revision", default=0)),
        "topic_revision": normalize_revision(value("topic_revision", "revision", default=0)),
        "editor_brief": editor_brief,
        "reader_questions": list(reader_questions or []),
        "difference_from_existing": str(
            value("difference_from_existing", "difference", default="") or ""
        ),
        "existing_post_refs": normalize_reference_list(existing_post_refs),
        "publication_refs": normalize_reference_list(publication_refs),
        "published_url": str(value("published_url", default="") or ""),
        "blogger_post_id": str(value("blogger_post_id", default="") or ""),
        "article_type": str(value("article_type", "intent", default="") or ""),
        "quality_precheck": value("quality_precheck", default={}) or {},
        "topic_source": "registry",
        "registry_status": normalize_topic_status(value("status", default="")),
        "registry_updated_at": str(
            value("updated_at", "last_validated_at", default="") or ""
        ),
        "claim_run_id": str(value("claim_run_id", default="") or ""),
    }


def resolve_topic_category_label(store, site: str, category_id: str, fallback: str = "") -> str:
    if fallback and fallback != category_id:
        return fallback
    if store is None or not category_id:
        return ""
    category = None
    for method_name in ("get_category", "category_for", "get_category_record"):
        method = getattr(store, method_name, None)
        if not callable(method):
            continue
        try:
            category = method(site, category_id)
        except TypeError:
            try:
                category = method(category_id)
            except Exception:
                category = None
        except Exception:
            category = None
        if category is not None:
            break
    if category is None:
        list_categories = getattr(store, "list_categories", None)
        if callable(list_categories):
            try:
                categories = list_categories(site)
            except Exception:
                categories = []
            category = next(
                (
                    item
                    for item in categories or []
                    if str(
                        (item.get("category_id") if isinstance(item, dict) else getattr(item, "category_id", ""))
                        or ""
                    )
                    == category_id
                ),
                None,
            )
    if category is None:
        return ""
    payload = plain_topic_value(asdict(category) if is_dataclass(category) else category)
    if isinstance(payload, dict):
        return str(payload.get("blogger_label") or payload.get("name") or "")
    return str(
        getattr(category, "blogger_label", "")
        or getattr(category, "name", "")
        or ""
    )


def plain_topic_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: plain_topic_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): plain_topic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain_topic_value(item) for item in value]
    return value


def normalize_reference_list(value: Any) -> list[dict]:
    if not value:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    references = []
    for item in values:
        normalized = plain_topic_value(item)
        if isinstance(normalized, dict):
            references.append(normalized)
        elif normalized:
            references.append({"url": str(normalized)})
    return references


def normalize_topic_action(value: Any) -> str:
    normalized = str(plain_topic_value(value) or NEW_POST_ACTION).strip().upper()
    return normalized.replace("-", "_").replace(" ", "_")


def normalize_topic_status(value: Any) -> str:
    return str(plain_topic_value(value) or "").strip().upper().replace("-", "_").replace(" ", "_")


def normalize_revision(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def topic_has_publication(candidate: dict) -> bool:
    return bool(
        candidate.get("publication_refs")
        or candidate.get("published_url")
        or candidate.get("blogger_post_id")
        or normalize_topic_status(candidate.get("registry_status")) == "PUBLISHED"
    )


def revalidate_registry_candidate(candidate: dict, site: str, store=None) -> tuple[bool, dict]:
    topic_id = str(candidate.get("topic_id") or "")
    if not topic_id:
        return True, candidate

    selected_store = store if store is not None else load_topic_store()
    if selected_store is None:
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": "topic_registry_unavailable",
            },
        }
    try:
        record = selected_store.get_topic(site, topic_id)
    except Exception as exc:
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": "topic_registry_lookup_failed",
                "error": str(exc),
            },
        }
    if record is None:
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": "topic_missing",
            },
        }

    fresh = normalize_topic_record(record)
    fresh["category"] = resolve_topic_category_label(
        selected_store,
        site,
        fresh.get("category_id", ""),
        fresh.get("category", ""),
    )
    current_status = normalize_topic_status(fresh.get("registry_status"))
    if current_status not in {"READY", "SCHEDULED"}:
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": f"topic_status_{current_status.lower() or 'unknown'}",
            },
        }
    if normalize_topic_action(fresh.get("action")) != NEW_POST_ACTION:
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": "topic_no_longer_new_post",
            },
        }
    if topic_has_publication(fresh):
        return False, {
            **candidate,
            "registry_revalidation": {
                "status": "failed",
                "reason": "topic_already_published",
            },
        }

    refreshed = {
        **candidate,
        **fresh,
        "category": fresh.get("category") or candidate.get("category", ""),
        "article_type": fresh.get("article_type") or candidate.get("article_type", ""),
        "quality_precheck": candidate.get("quality_precheck") or {"status": "ready"},
        "weekly_queue": {
            **(candidate.get("weekly_queue") or {}),
            "registry_revision": fresh.get("revision", 0),
        },
        "registry_revalidation": {
            "status": "passed",
            "queued_revision": normalize_revision(candidate.get("revision")),
            "current_revision": normalize_revision(fresh.get("revision")),
        },
    }
    return True, refreshed


def locally_published_topic_ids(site: str) -> set[str]:
    try:
        settings = load_settings(site)
    except Exception:
        return set()
    topic_ids: set[str] = set()
    for metadata_path in Path(settings.generated_output_dir).glob("*/*/metadata.json"):
        article_dir = metadata_path.parent
        result_path = article_dir / "blogger_publish_result.json"
        if not result_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        candidate = metadata.get("candidate") or {}
        topic_id = str(candidate.get("topic_id") or "")
        blogger = result.get("blogger") or {}
        if (
            topic_id
            and not result.get("draft", False)
            and not result.get("skipped", False)
            and (blogger.get("id") or blogger.get("url"))
        ):
            topic_ids.add(topic_id)
    return topic_ids


def generate_maintenance_queue(
    site: str,
    selected_start: date,
    *,
    store=None,
    max_items: int = MAX_WEEKLY_MAINTENANCE_ITEMS,
    enabled: bool = True,
    hold_reason: str = "",
) -> dict:
    selected_store = (store if store is not None else load_topic_store()) if enabled else None
    records = []
    if selected_store is not None:
        try:
            records = selected_store.list_maintenance_topics(
                site,
                actions=tuple(sorted(MAINTENANCE_ACTIONS)),
                statuses=tuple(sorted(MAINTENANCE_STATUSES)),
            )
        except TypeError:
            try:
                records = selected_store.list_maintenance_topics(site)
            except Exception:
                records = []
        except Exception:
            records = []

    items = []
    seen_topic_ids: set[str] = set()
    for record in records or []:
        candidate = normalize_topic_record(record)
        candidate["category"] = resolve_topic_category_label(
            selected_store,
            site,
            candidate.get("category_id", ""),
            candidate.get("category", ""),
        )
        topic_id = candidate.get("topic_id", "")
        action = normalize_topic_action(candidate.get("action"))
        status = normalize_topic_status(candidate.get("registry_status"))
        if not topic_id or topic_id in seen_topic_ids:
            continue
        if action not in MAINTENANCE_ACTIONS or status not in MAINTENANCE_STATUSES:
            continue
        references = list(
            candidate.get("existing_post_refs")
            or candidate.get("publication_refs")
            or []
        )
        target = select_maintenance_target(references)
        if target is None:
            continue
        items.append(
            {
                "site": site,
                "topic_id": topic_id,
                "cluster_id": candidate.get("cluster_id", ""),
                "seed": candidate.get("seed", ""),
                "category": candidate.get("category", ""),
                "category_id": candidate.get("category_id", ""),
                "action": action,
                "topic_action": action,
                "revision": candidate.get("revision", 0),
                "topic_revision": candidate.get("revision", 0),
                "editor_brief": candidate.get("editor_brief") or {},
                "reader_questions": list(candidate.get("reader_questions") or []),
                "difference_from_existing": candidate.get("difference_from_existing", ""),
                "existing_post_refs": references,
                "maintenance_target": target,
                "status": "maintenance_review",
                "registry_status": status,
            }
        )
        seen_topic_ids.add(topic_id)
        if len(items) >= max(0, min(max_items, MAX_WEEKLY_MAINTENANCE_ITEMS)):
            break

    queue = {
        "site": site,
        "week": iso_week_label(selected_start),
        "created_at": datetime.now(tz=KST).isoformat(),
        "start_date": selected_start.isoformat(),
        "end_date": (selected_start + timedelta(days=6)).isoformat(),
        "max_items_per_site_week": MAX_WEEKLY_MAINTENANCE_ITEMS,
        "status": "review_required" if enabled else "HOLD",
        "hold_reason": "" if enabled else (
            hold_reason or "maintenance_rollout_gate_closed"
        ),
        "items": items,
    }
    path = save_maintenance_queue(queue)
    queue["_path"] = str(path)
    return queue


def select_maintenance_target(references: list[dict]) -> dict | None:
    """Return the one explicit primary LIVE Blogger identity, otherwise hold."""

    candidates = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        post_id = str(
            reference.get("blogger_post_id")
            or reference.get("post_id")
            or reference.get("id")
            or ""
        ).strip()
        url = str(reference.get("url") or "").strip()
        status = str(reference.get("status") or "").strip().upper()
        if (
            post_id
            and url
            and reference.get("primary") is True
            and status in {"LIVE", "PUBLISHED"}
        ):
            candidates.append(
                {
                    **reference,
                    "blogger_post_id": post_id,
                    "url": url,
                    "primary": True,
                    "status": status,
                }
            )
    return candidates[0] if len(candidates) == 1 else None


def load_maintenance_queue(site: str, selected_date: date | None = None) -> dict | None:
    target_date = selected_date or datetime.now(tz=KST).date()
    candidates = [maintenance_queue_path(site, target_date)]
    if QUEUE_DIR.exists():
        candidates.extend(sorted(QUEUE_DIR.glob(f"{site}_maintenance_queue_*.json"), reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            queue = json.loads(path.read_text(encoding="utf-8"))
            start = date.fromisoformat(queue["start_date"])
            end = date.fromisoformat(queue["end_date"])
        except (OSError, ValueError, KeyError):
            continue
        if start <= target_date <= end:
            queue["_path"] = str(path)
            return queue
    return None


def maintenance_target_belongs_to_topic(
    store,
    site: str,
    topic_id: str,
    topic: dict,
    *,
    blogger_post_id: str,
    url: str,
) -> bool:
    try:
        from src.topics.ids import canonical_url
    except ImportError:
        canonical_url = lambda value: str(value or "").rstrip("/")  # type: ignore[assignment]

    expected_url = canonical_url(url)
    publications = list(topic.get("publication_refs") or [])
    matched = any(
        str(ref.get("blogger_post_id") or ref.get("post_id") or ref.get("id") or "")
        == blogger_post_id
        and canonical_url(str(ref.get("url") or "")) == expected_url
        for ref in publications
        if isinstance(ref, dict)
    )
    if not matched:
        return False
    owner_lookup = getattr(store, "publication_owner", None)
    if callable(owner_lookup):
        owner = owner_lookup(
            site,
            blogger_post_id=blogger_post_id,
            url=expected_url,
        )
        owner_id = str(
            owner.get("topic_id") if isinstance(owner, dict) else owner or ""
        )
        if owner_id != topic_id:
            return False
    return True


def load_existing_blogger_post(publisher, post_id: str) -> dict:
    get_post = getattr(publisher, "get_post", None)
    if callable(get_post):
        post = get_post(post_id)
        if isinstance(post, dict):
            return post
    posts = publisher.list_live_posts(fetch_bodies=True)
    post = next(
        (
            item
            for item in posts
            if str(item.get("id") or "") == post_id
        ),
        None,
    )
    if not isinstance(post, dict):
        raise ValueError(f"Blogger post {post_id} no longer exists or is not readable.")
    return post


def maintenance_update_labels(
    store,
    site: str,
    item: dict,
    existing_post: dict,
    generated_labels: list[str],
) -> list[str]:
    existing_labels = [
        str(label)
        for label in list(existing_post.get("labels") or [])
        if str(label).strip()
    ]
    proposal_id = str(item.get("approved_label_proposal_id") or "")
    if not proposal_id:
        return existing_labels
    get_proposal = getattr(store, "get_monthly_proposal", None)
    proposal = get_proposal(site, proposal_id) if callable(get_proposal) else None
    kind = getattr(proposal, "kind", "")
    status = getattr(proposal, "status", "")
    kind_value = kind.value if hasattr(kind, "value") else str(kind)
    status_value = status.value if hasattr(status, "value") else str(status)
    payload = dict(getattr(proposal, "payload", {}) or {})
    label_snapshot = dict(getattr(proposal, "label_snapshot", {}) or {})
    snapshot_path = str(getattr(proposal, "snapshot_path", "") or "")
    publication_sync_pending = bool(
        getattr(proposal, "publication_sync_pending", False)
    )
    if (
        proposal is None
        or kind_value.upper() != "LABEL_CHANGE"
        or status_value.upper() != "APPROVED"
        or not str(getattr(proposal, "approved_by", "") or "").strip()
        or not str(getattr(proposal, "approved_at", "") or "").strip()
        or not str(getattr(proposal, "applied_at", "") or "").strip()
        or not publication_sync_pending
        or not label_snapshot
        or not snapshot_path
        or not Path(snapshot_path).is_file()
        or (
            payload.get("category_id")
            and str(payload.get("category_id")) != str(item.get("category_id") or "")
        )
        or (
            payload.get("blogger_post_id")
            and str(payload.get("blogger_post_id"))
            != str(existing_post.get("id") or "")
        )
    ):
        raise ValueError(
            f"Label proposal {proposal_id} does not authorize this Blogger post update."
        )
    proposed = payload.get("labels")
    if isinstance(proposed, list):
        approved_labels = [
            str(label) for label in proposed if str(label).strip()
        ]
        if not approved_labels:
            raise ValueError(
                f"Label proposal {proposal_id} has no approved labels."
            )
        return list(dict.fromkeys(approved_labels))

    new_label = str(payload.get("blogger_label") or "").strip()
    category_id = str(payload.get("category_id") or item.get("category_id") or "")
    categories_snapshot = dict(label_snapshot.get("categories") or {})
    category_snapshot = dict(
        (categories_snapshot.get("categories") or {}).get(category_id) or {}
    )
    old_label = str(
        category_snapshot.get("blogger_label")
        or category_snapshot.get("name")
        or ""
    ).strip()
    if not new_label or not old_label:
        raise ValueError(
            f"Label proposal {proposal_id} lacks an exact old/new label mapping."
        )
    if old_label == new_label:
        return existing_labels
    if old_label not in existing_labels:
        if new_label in existing_labels:
            return existing_labels
        raise ValueError(
            f"Label proposal {proposal_id} cannot find the approved old label "
            f"{old_label!r} on Blogger post {existing_post.get('id') or ''}."
        )
    return list(
        dict.fromkeys(
            new_label if label == old_label else label
            for label in existing_labels
        )
    )


def record_maintenance_update_receipt(
    store,
    site: str,
    topic_id: str,
    *,
    attempt: dict,
    run_id: str,
    expected_revision: int,
    title: str,
    blogger: dict,
) -> dict:
    publication = {
        "blogger_post_id": str(blogger.get("id") or ""),
        "url": str(blogger.get("url") or ""),
        "title": title,
        "status": str(blogger.get("status") or ""),
        "published_at": str(blogger.get("published") or ""),
        "updated_at": str(blogger.get("updated") or ""),
        "last_verified_at": "",
        "primary": bool(attempt.get("target_primary")),
    }
    attempt_id = str(attempt.get("attempt_id") or "")
    try:
        store.record_update_receipt(
            site,
            topic_id,
            attempt_id=attempt_id,
            publication=publication,
            expected_revision=expected_revision,
            run_id=run_id,
        )
        return {
            "status": "recorded_live_unverified",
            "durable": True,
            "attempt_id": attempt_id,
            "operation": "UPDATE",
        }
    except Exception as record_error:
        try:
            entry = store.enqueue_update_receipt(
                site,
                topic_id,
                attempt_id=attempt_id,
                publication=publication,
                run_id=run_id,
                error=str(record_error),
            )
            return {
                "status": "queued",
                "durable": True,
                "attempt_id": attempt_id,
                "operation": "UPDATE",
                "outbox_id": str(entry.get("outbox_id") or ""),
                "error": str(record_error),
            }
        except Exception as outbox_error:
            from src.pipeline.stage2_publish import enqueue_local_publication_sync

            local = enqueue_local_publication_sync(
                site,
                topic_id,
                publication,
                error=(
                    f"update_record={record_error}; "
                    f"update_outbox={outbox_error}"
                ),
                attempt_id=attempt_id,
                topic_revision=expected_revision,
                run_id=run_id,
                attempt_kind="UPDATE",
                action=str(attempt.get("action") or ""),
            )
            try:
                store.mark_update_unknown(
                    site,
                    topic_id,
                    attempt_id=attempt_id,
                    run_id=run_id,
                    error=str(local.get("error") or record_error),
                )
            except Exception:
                pass
            return {
                **local,
                "attempt_id": attempt_id,
                "operation": "UPDATE",
            }


def execute_maintenance_item(
    site: str,
    topic_id: str,
    article_dir: Path,
    *,
    selected_date: date | None = None,
    apply: bool = False,
) -> dict:
    queue = load_maintenance_queue(site, selected_date)
    if not queue:
        raise ValueError(f"No maintenance queue covers the selected date for {site}.")
    item = next(
        (
            candidate
            for candidate in queue.get("items", [])
            if str(candidate.get("topic_id") or "") == topic_id
        ),
        None,
    )
    if item is None:
        raise ValueError(f"Topic {topic_id} is not in this week's maintenance queue.")
    if str(item.get("status") or "").strip().casefold() in {
        "completed",
        "live_unverified",
    }:
        raise ValueError(
            f"Maintenance topic {topic_id} was already sent to Blogger; "
            "verify or reconcile the existing result instead of updating it again."
        )
    action = normalize_topic_action(item.get("action") or item.get("topic_action"))
    if action not in MAINTENANCE_ACTIONS:
        raise ValueError(f"Topic {topic_id} is not an UPDATE_EXISTING/FAQ_ADD action.")
    references = list(item.get("existing_post_refs") or [])
    selected_target = select_maintenance_target(references)
    explicit_target = item.get("maintenance_target")
    if selected_target is None or not isinstance(explicit_target, dict):
        raise ValueError(
            f"Maintenance topic {topic_id} needs exactly one explicit primary LIVE "
            "Blogger post ID+URL target; update is held."
        )
    try:
        from src.topics.ids import canonical_url

        selected_url = canonical_url(str(selected_target.get("url") or ""))
        explicit_url = canonical_url(str(explicit_target.get("url") or ""))
    except ImportError:
        selected_url = str(selected_target.get("url") or "").rstrip("/")
        explicit_url = str(explicit_target.get("url") or "").rstrip("/")
    selected_id = str(selected_target.get("blogger_post_id") or "")
    explicit_id = str(
        explicit_target.get("blogger_post_id")
        or explicit_target.get("post_id")
        or explicit_target.get("id")
        or ""
    )
    if (
        explicit_id != selected_id
        or not explicit_url
        or explicit_url != selected_url
        or explicit_target.get("primary") is not True
        or str(explicit_target.get("status") or "").upper()
        not in {"LIVE", "PUBLISHED"}
    ):
        raise ValueError(
            f"Maintenance topic {topic_id} has a stale or ambiguous explicit target."
        )
    reference = selected_target
    post_id = str(
        reference.get("blogger_post_id")
        or reference.get("post_id")
        or reference.get("id")
        or ""
    )
    metadata_path = article_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Maintenance article is missing metadata.json: {article_dir}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidate = metadata.get("candidate") or {}
    metadata_topic_id = str(candidate.get("topic_id") or "")
    metadata_action = normalize_topic_action(
        candidate.get("action") or candidate.get("topic_action")
    )
    metadata_revision = normalize_revision(
        candidate.get("revision") or candidate.get("topic_revision")
    )
    if metadata_topic_id != topic_id or metadata_action != action:
        raise ValueError(
            "Maintenance article metadata does not match the queued topic_id/action; Blogger update is blocked."
        )
    if metadata_revision != normalize_revision(item.get("revision") or item.get("topic_revision")):
        raise ValueError(
            "Maintenance topic revision changed; regenerate the maintenance article before updating Blogger."
        )

    plan = {
        "site": site,
        "topic_id": topic_id,
        "cluster_id": item.get("cluster_id", ""),
        "action": action,
        "topic_action": action,
        "revision": metadata_revision,
        "topic_revision": metadata_revision,
        "blogger_post_id": post_id,
        "existing_url": reference.get("url", ""),
        "article_dir": str(article_dir),
        "apply": apply,
    }
    if not apply:
        return {**plan, "status": "dry_run", "operation": "BloggerPublisher.update_post"}

    store = load_topic_store()
    if store is None:
        raise RuntimeError("Topic registry is unavailable; maintenance update is held.")
    maintenance_allowed, maintenance_hold_reason = maintenance_rollout_gate(
        store,
        site,
    )
    if not maintenance_allowed:
        raise RuntimeError(
            "Maintenance update is held by the rollout gate: "
            f"{maintenance_hold_reason}."
        )
    run_id = f"maintenance:{site}:{topic_id}:{datetime.now(tz=KST).isoformat()}"
    claim = getattr(store, "claim_topic", None)
    if not callable(claim):
        raise RuntimeError("Topic-specific claim API is unavailable; maintenance update is held.")
    claimed = claim(site, topic_id, run_id, metadata_revision)
    if claimed is None:
        raise RuntimeError("Maintenance topic claim failed or its revision/status changed.")

    fresh_record = store.get_topic(site, topic_id)
    if fresh_record is None:
        try:
            store.release_claim(
                site,
                topic_id,
                run_id,
                status="HOLD",
                reason="Maintenance topic disappeared after claim.",
            )
        finally:
            raise RuntimeError("Maintenance topic disappeared after claim.")
    claimed_topic = normalize_topic_record(fresh_record)
    claimed_revision = normalize_revision(
        claimed_topic.get("revision") or metadata_revision
    )
    claimed_run_id = str(claimed_topic.get("claim_run_id") or run_id)
    claimed_status = normalize_topic_status(claimed_topic.get("registry_status"))
    if claimed_status and claimed_status != "CLAIMED":
        raise RuntimeError(
            f"Maintenance topic claim returned {claimed_status}, not CLAIMED."
        )
    if claimed_run_id != run_id:
        raise RuntimeError("Maintenance topic claim is owned by a different run.")
    fresh_action = normalize_topic_action(claimed_topic.get("action"))
    if fresh_action != action or fresh_action not in MAINTENANCE_ACTIONS:
        try:
            store.release_claim(
                site,
                topic_id,
                run_id,
                status="HOLD",
                reason=(
                    f"Maintenance action changed from {action} to "
                    f"{fresh_action or 'UNKNOWN'} after claim."
                ),
            )
        finally:
            raise RuntimeError(
                f"Maintenance topic action changed to {fresh_action or 'UNKNOWN'}."
            )
    if not maintenance_target_belongs_to_topic(
        store,
        site,
        topic_id,
        claimed_topic,
        blogger_post_id=post_id,
        url=str(reference.get("url") or ""),
    ):
        try:
            store.release_claim(
                site,
                topic_id,
                run_id,
                status="HOLD",
                reason="Maintenance target is stale or belongs to another topic.",
            )
        finally:
            raise RuntimeError(
                "Maintenance Blogger target is stale or belongs to another topic."
            )
    plan["revision"] = claimed_revision
    plan["topic_revision"] = claimed_revision
    plan["claim_run_id"] = run_id
    candidate.update(
        {
            "topic_id": topic_id,
            "cluster_id": item.get("cluster_id", ""),
            "category_id": item.get("category_id", ""),
            "action": action,
            "topic_action": action,
            "revision": claimed_revision,
            "topic_revision": claimed_revision,
            "claim_run_id": run_id,
        }
    )
    update_invoked = False
    hold_on_failure = False
    update_attempt: dict | None = None
    try:
        metadata["candidate"] = candidate
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        from src.pipeline.stage2_publish import attach_topic_registry_sync
        from src.pipeline.stage2_publish import ensure_topic_id_marker
        from src.pipeline.stage2_publish import load_article

        title, html, labels = load_article(article_dir, site)
        publisher = BloggerPublisher(load_settings(site))
        hold_on_failure = True
        existing_post = load_existing_blogger_post(publisher, post_id)
        try:
            from src.topics.ids import canonical_url

            requested_url = canonical_url(str(reference.get("url") or ""))
            live_url = canonical_url(str(existing_post.get("url") or ""))
        except ImportError:
            requested_url = str(reference.get("url") or "").rstrip("/")
            live_url = str(existing_post.get("url") or "").rstrip("/")
        if (
            str(existing_post.get("id") or "") != post_id
            or not requested_url
            or live_url != requested_url
            or str(existing_post.get("status") or "").upper()
            not in {"LIVE", "PUBLISHED"}
        ):
            raise ValueError(
                "The current Blogger post ID/canonical URL does not match the "
                "Registry maintenance target."
            )
        html = ensure_topic_id_marker(html, topic_id)
        labels = maintenance_update_labels(
            store,
            site,
            item,
            existing_post,
            labels,
        )
        update_attempt = store.begin_update_attempt(
            site,
            topic_id,
            action=action,
            blogger_post_id=post_id,
            url=requested_url,
            run_id=run_id,
            expected_revision=claimed_revision,
        )
        if not bool(update_attempt.get("acquired")):
            raise MaintenanceReconciliationRequired(
                "A maintenance attempt already exists for this topic; "
                "reconcile it instead of updating Blogger again."
            )
        update_attempt = store.mark_update_started(
            site,
            topic_id,
            attempt_id=str(update_attempt.get("attempt_id") or ""),
            run_id=run_id,
        )
        if not bool(update_attempt.get("started")):
            raise MaintenanceReconciliationRequired(
                "The Blogger update-start trace already exists; "
                "reconcile the prior attempt instead of updating again."
            )
        plan["update_attempt_id"] = str(
            update_attempt.get("attempt_id") or ""
        )
        update_invoked = True
        try:
            blogger = publisher.update_post(
                post_id=post_id,
                title=title,
                html=html,
                labels=labels,
            )
        except Exception as update_error:
            try:
                store.mark_update_unknown(
                    site,
                    topic_id,
                    attempt_id=str(update_attempt.get("attempt_id") or ""),
                    run_id=run_id,
                    error=str(update_error),
                )
            finally:
                raise MaintenanceReconciliationRequired(
                    "Blogger maintenance outcome is unknown; "
                    "reconcile the reserved target before any retry."
                ) from update_error
        returned_id = str(blogger.get("id") or "")
        returned_url = canonical_url(str(blogger.get("url") or ""))
        if returned_id != post_id or returned_url != requested_url:
            mismatch = (
                "Blogger update response does not match the exact Registry target"
            )
            try:
                store.mark_update_unknown(
                    site,
                    topic_id,
                    attempt_id=str(update_attempt.get("attempt_id") or ""),
                    run_id=run_id,
                    error=mismatch,
                )
            finally:
                raise MaintenanceReconciliationRequired(
                    f"{mismatch}; reconciliation is required."
                )
        sync = record_maintenance_update_receipt(
            store,
            site,
            topic_id,
            attempt=update_attempt,
            run_id=run_id,
            expected_revision=claimed_revision,
            title=title,
            blogger=blogger,
        )
        if not bool(sync.get("durable")):
            raise RuntimeError(
                "Blogger update succeeded but its Registry/outbox receipt was not durable."
            )
        result_path = article_dir / "blogger_maintenance_result.json"
        result = {
            **plan,
            "status": "updated_live_unverified",
            "topic_registry_sync": sync,
            "blogger": {
                "id": blogger.get("id"),
                "url": blogger.get("url"),
                "selfLink": blogger.get("selfLink"),
                "status": blogger.get("status"),
                "published": blogger.get("published"),
                "updated": blogger.get("updated"),
            },
        }
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        attach_topic_registry_sync(result_path, sync)
        verification = confirm_maintenance_publication(
            store,
            site,
            topic_id,
            publisher,
            blogger,
        )
        queue_status = (
            "completed"
            if verification.get("status") == "PUBLISHED"
            else "live_unverified"
        )
        persisted = json.loads(result_path.read_text(encoding="utf-8"))
        persisted["status"] = queue_status
        persisted["topic_publication_verification"] = verification
        result_path.write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        update_maintenance_queue_status(queue, topic_id, queue_status, result_path)
        return {
            **result,
            "status": queue_status,
            "result_path": str(result_path),
            "topic_registry_sync": sync,
            "topic_publication_verification": verification,
        }
    except Exception as exc:
        if getattr(exc, "reconciliation_only", False):
            raise
        release = getattr(store, "release_claim", None)
        if callable(release):
            try:
                from src.topics.models import TopicStatus

                release(
                    site,
                    topic_id,
                    run_id,
                    status=(
                        TopicStatus.HOLD
                        if update_invoked or hold_on_failure
                        else TopicStatus.READY
                    ),
                    reason=f"Maintenance update failed: {exc}",
                )
            except Exception:
                pass
        raise


def confirm_maintenance_publication(
    store,
    site: str,
    topic_id: str,
    publisher,
    blogger: dict,
) -> dict:
    expected_id = str(blogger.get("id") or "")
    expected_url = str(blogger.get("url") or "").rstrip("/")
    live_post = next(
        (
            post
            for post in publisher.list_live_posts()
            if (expected_id and str(post.get("id") or "") == expected_id)
            or (expected_url and str(post.get("url") or "").rstrip("/") == expected_url)
        ),
        None,
    )
    if live_post is None:
        return {
            "topic_id": topic_id,
            "status": "LIVE_UNVERIFIED",
            "reason": "blogger_post_not_visible_yet",
        }
    verified_at = datetime.now(tz=KST).isoformat()
    try:
        verify = getattr(store, "verify_publication", None)
        if callable(verify):
            verify(
                site,
                topic_id,
                blogger_post_id=str(live_post.get("id") or expected_id),
                url=str(live_post.get("url") or expected_url),
                verified_at=verified_at,
                status="LIVE",
            )
        else:
            from src.topics.models import PublicationRef

            store.record_publication(
                site,
                topic_id,
                PublicationRef(
                    blogger_post_id=str(live_post.get("id") or expected_id),
                    url=str(live_post.get("url") or expected_url),
                    title=str(live_post.get("title") or ""),
                    status="LIVE",
                    published_at=str(live_post.get("published") or ""),
                    updated_at=str(live_post.get("updated") or ""),
                    last_verified_at=verified_at,
                ),
            )
    except Exception as exc:
        return {
            "topic_id": topic_id,
            "status": "LIVE_UNVERIFIED",
            "reason": f"registry_confirmation_failed:{exc}",
        }
    return {
        "topic_id": topic_id,
        "status": "PUBLISHED",
        "blogger_post_id": str(live_post.get("id") or expected_id),
        "url": str(live_post.get("url") or expected_url),
        "verified_at": verified_at,
    }


def update_maintenance_queue_status(
    queue: dict,
    topic_id: str,
    status: str,
    result_path: Path,
) -> None:
    for item in queue.get("items", []):
        if str(item.get("topic_id") or "") != topic_id:
            continue
        item["status"] = status
        item["result_path"] = str(result_path)
        item["completed_at"] = datetime.now(tz=KST).isoformat()
        break
    path = Path(queue.get("_path") or maintenance_queue_path(queue["site"], date.fromisoformat(queue["start_date"])))
    payload = {key: value for key, value in queue.items() if key != "_path"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_weekly_queue(queue: dict) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = weekly_queue_path(queue["site"], date.fromisoformat(queue["start_date"]))
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_maintenance_queue(queue: dict) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = maintenance_queue_path(queue["site"], date.fromisoformat(queue["start_date"]))
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
    parser.add_argument("--start-date", help="YYYY-MM-DD. Defaults to the current or next Monday in Asia/Seoul.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--posts-per-day", type=int, default=int(os.getenv("WEEKLY_QUEUE_POSTS_PER_DAY", "1")))
    parser.add_argument("--maintenance-topic-id", help="Execute one queued UPDATE_EXISTING/FAQ_ADD topic.")
    parser.add_argument("--article-dir", help="Generated maintenance article directory.")
    parser.add_argument("--apply", action="store_true", help="Apply the maintenance Blogger update. Default is dry-run.")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    if args.maintenance_topic_id:
        if not args.article_dir:
            parser.error("--article-dir is required with --maintenance-topic-id")
        result = execute_maintenance_item(
            args.site,
            args.maintenance_topic_id,
            Path(args.article_dir).expanduser().resolve(),
            selected_date=parse_date(args.start_date),
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

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
