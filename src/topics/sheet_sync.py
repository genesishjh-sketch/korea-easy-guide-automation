from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from src.topics.models import utc_now
from src.topics.schema import validate_persistent_document
from src.topics.store import TopicStore


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SYNC_STATUSES = {"PENDING", "SUCCESS", "FAILED"}


def _default(site: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "site": site,
        "runs": {},
        "updated_at": "",
    }


def sheet_sync_path(store: TopicStore, site: str):
    return store.site_dir(site) / "sheet_sync.json"


def load_sheet_sync_state(
    store: TopicStore,
    site: str,
) -> dict[str, Any]:
    document = store._read_json(sheet_sync_path(store, site), _default(site))
    validate_persistent_document("sheet_sync", document, site)
    return document


def _known_run(store: TopicStore, site: str, run_id: str) -> bool:
    if (store.site_dir(site) / "runs" / f"{run_id}.json").exists():
        return True
    return any(
        str(item.get("run_id") or "") == run_id
        for item in store.get_rollout_state(site).get("recent_runs") or []
    )


def record_sheet_sync(
    store: TopicStore,
    site: str,
    run_id: str,
    status: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    selected_run_id = str(run_id or "").strip()
    if not RUN_ID_PATTERN.fullmatch(selected_run_id):
        raise ValueError("run_id may only contain letters, numbers, dot, underscore, or hyphen")
    normalized_status = str(status or "").strip().upper()
    if normalized_status not in SYNC_STATUSES:
        raise ValueError("sheet sync status must be PENDING, SUCCESS, or FAILED")
    if not _known_run(store, site, selected_run_id):
        raise ValueError(f"Unknown topic-intelligence run: {selected_run_id}")
    if normalized_status == "SUCCESS" and error:
        raise ValueError("successful Sheet sync cannot include an error")
    selected_error = str(error or "").strip()
    if normalized_status == "FAILED" and not selected_error:
        selected_error = "Sheet synchronization failed"

    with store._lock(site):
        path = sheet_sync_path(store, site)
        document = store._read_json(path, _default(site))
        validate_persistent_document("sheet_sync", document, site)
        existing = dict(document["runs"].get(selected_run_id) or {})
        if (
            existing.get("status") == normalized_status
            and existing.get("last_error", "") == selected_error
        ):
            return deepcopy(existing)
        selected_now = utc_now()
        record = {
            "run_id": selected_run_id,
            "status": normalized_status,
            "pending": normalized_status != "SUCCESS",
            "attempts": int(existing.get("attempts") or 0) + 1,
            "last_error": selected_error if normalized_status != "SUCCESS" else "",
            "updated_at": selected_now,
            "last_success_at": (
                selected_now
                if normalized_status == "SUCCESS"
                else str(existing.get("last_success_at") or "")
            ),
        }
        document["runs"][selected_run_id] = record
        document["updated_at"] = selected_now
        validate_persistent_document("sheet_sync", document, site)
        store._atomic_write(path, document)
    return deepcopy(record)


def sheet_sync_record(
    store: TopicStore,
    site: str,
    run_id: str,
) -> dict[str, Any]:
    return deepcopy(
        load_sheet_sync_state(store, site)["runs"].get(run_id) or {}
    )
