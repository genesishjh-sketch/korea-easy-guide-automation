from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from src.topics.models import utc_now
from src.topics.schema import validate_schema
from src.topics.store import TopicStore


SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
TERMINAL_STATES = {"DONE", "SATURATED"}
WORK_STATES = {"PENDING", "RUNNING", "PAUSED", "DONE", "BLOCKED", "SATURATED"}


def _coverage_hash(
    *,
    site: str,
    run_type: str,
    window_start: str,
    window_end: str,
    logic_version: str,
    work_items: list[dict[str, Any]],
) -> str:
    normalized = [
        {
            "work_id": str(item.get("work_id") or ""),
            "source": str(item.get("source") or ""),
            "query_family": str(item.get("query_family") or ""),
            "required": bool(item.get("required", True)),
        }
        for item in work_items
    ]
    normalized.sort(key=lambda item: item["work_id"])
    material = {
        "site": site,
        "run_type": run_type,
        "window_start": window_start,
        "window_end": window_end,
        "logic_version": logic_version,
        "work_items": normalized,
    }
    return sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ResearchCampaignStore:
    """Durable, resumable source/query work ledger for one TopicStore root."""

    def __init__(self, topic_store: TopicStore) -> None:
        self.topic_store = topic_store

    def path(self, site: str, campaign_id: str) -> Path:
        if not SAFE_ID.fullmatch(campaign_id):
            raise ValueError("campaign_id contains unsafe characters")
        return (
            self.topic_store.site_dir(site)
            / "research_campaigns"
            / f"{campaign_id}.json"
        )

    def _load(self, site: str, campaign_id: str) -> dict[str, Any]:
        path = self.path(site, campaign_id)
        if not path.exists():
            raise ValueError(f"Unknown research campaign: {campaign_id}")
        document = self.topic_store._read_json(path, {})
        validate_schema("research_campaign", document)
        if document.get("site") != site:
            raise ValueError("research campaign site mismatch")
        return document

    def create(
        self,
        site: str,
        campaign_id: str,
        *,
        run_type: str,
        window_start: str,
        window_end: str,
        logic_version: str,
        work_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selected_run_type = run_type.strip().upper()
        if selected_run_type not in {"BACKFILL_RESEARCH", "WEEKLY_RESEARCH"}:
            raise ValueError(f"Unsupported run_type: {run_type}")
        if not work_items:
            raise ValueError("research campaign requires work_items")
        now = utc_now()
        normalized_items: dict[str, dict[str, Any]] = {}
        for raw in work_items:
            work_id = str(raw.get("work_id") or "").strip()
            if not work_id or not SAFE_ID.fullmatch(work_id):
                raise ValueError(f"Invalid work_id: {work_id!r}")
            if work_id in normalized_items:
                raise ValueError(f"Duplicate work_id: {work_id}")
            source = str(raw.get("source") or "").strip()
            query_family = str(raw.get("query_family") or "").strip()
            if not source or not query_family:
                raise ValueError(f"{work_id} requires source and query_family")
            normalized_items[work_id] = {
                "work_id": work_id,
                "source": source,
                "query_family": query_family,
                "required": bool(raw.get("required", True)),
                "state": "PENDING",
                "cursor": "",
                "attempts": 0,
                "last_error": "",
                "discovered_ids": [],
                "updated_at": now,
            }
        coverage_hash = _coverage_hash(
            site=site,
            run_type=selected_run_type,
            window_start=window_start,
            window_end=window_end,
            logic_version=logic_version,
            work_items=list(normalized_items.values()),
        )
        document = {
            "schema_version": 1,
            "site": site,
            "campaign_id": campaign_id,
            "run_type": selected_run_type,
            "state": "PENDING",
            "window_start": window_start,
            "window_end": window_end,
            "logic_version": logic_version,
            "coverage_hash": coverage_hash,
            "work_items": normalized_items,
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
        }
        validate_schema("research_campaign", document)
        path = self.path(site, campaign_id)
        with self.topic_store._lock(site):
            if path.exists():
                existing = self._load(site, campaign_id)
                if existing["coverage_hash"] != coverage_hash:
                    raise ValueError(
                        f"campaign_id content mismatch: {campaign_id}"
                    )
                return deepcopy(existing)
            self.topic_store._atomic_write(path, document)
        return deepcopy(document)

    def status(self, site: str, campaign_id: str) -> dict[str, Any]:
        return deepcopy(self._load(site, campaign_id))

    @staticmethod
    def _derive_state(document: dict[str, Any]) -> str:
        work_items = list((document.get("work_items") or {}).values())
        required = [item for item in work_items if item.get("required") is True]
        if required and all(item.get("state") in TERMINAL_STATES for item in required):
            return "DONE"
        if any(item.get("state") == "RUNNING" for item in work_items):
            return "RUNNING"
        if any(
            item.get("required") is True and item.get("state") == "BLOCKED"
            for item in work_items
        ):
            return "BLOCKED"
        if any(item.get("state") == "PAUSED" for item in work_items):
            return "PAUSED"
        return "PENDING"

    def claim_next(self, site: str, campaign_id: str) -> dict[str, Any] | None:
        with self.topic_store._lock(site):
            document = self._load(site, campaign_id)
            candidates = [
                item
                for item in document["work_items"].values()
                if item["state"] in {"PENDING", "PAUSED"}
            ]
            candidates.sort(
                key=lambda item: (
                    not bool(item["required"]),
                    item["source"],
                    item["query_family"],
                    item["work_id"],
                )
            )
            if not candidates:
                return None
            selected = candidates[0]
            selected["state"] = "RUNNING"
            selected["attempts"] = int(selected.get("attempts") or 0) + 1
            selected["last_error"] = ""
            selected["updated_at"] = utc_now()
            document["state"] = "RUNNING"
            document["updated_at"] = selected["updated_at"]
            validate_schema("research_campaign", document)
            self.topic_store._atomic_write(
                self.path(site, campaign_id),
                document,
            )
            return deepcopy(selected)

    def checkpoint(
        self,
        site: str,
        campaign_id: str,
        work_id: str,
        *,
        state: str,
        cursor: str = "",
        last_error: str = "",
        discovered_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        selected_state = state.strip().upper()
        if selected_state not in WORK_STATES:
            raise ValueError(f"Unsupported work state: {state}")
        with self.topic_store._lock(site):
            document = self._load(site, campaign_id)
            item = document["work_items"].get(work_id)
            if item is None:
                raise ValueError(f"Unknown research work item: {work_id}")
            item["state"] = selected_state
            item["cursor"] = cursor
            item["last_error"] = last_error.strip()
            item["discovered_ids"] = list(
                dict.fromkeys(
                    [
                        *list(item.get("discovered_ids") or []),
                        *list(discovered_ids or []),
                    ]
                )
            )
            item["updated_at"] = utc_now()
            document["state"] = self._derive_state(document)
            document["updated_at"] = item["updated_at"]
            document["completed_at"] = (
                item["updated_at"] if document["state"] == "DONE" else ""
            )
            validate_schema("research_campaign", document)
            self.topic_store._atomic_write(
                self.path(site, campaign_id),
                document,
            )
            return deepcopy(document)

    def bundle_metadata(self, site: str, campaign_id: str) -> dict[str, Any]:
        document = self._load(site, campaign_id)
        unexplored = [
            f"{item['source']}:{item['query_family']}"
            for item in document["work_items"].values()
            if item["required"] is True
            and item["state"] not in TERMINAL_STATES
        ]
        return {
            "campaign_id": document["campaign_id"],
            "logic_version": document["logic_version"],
            "coverage_hash": document["coverage_hash"],
            "coverage_manifest": [
                {
                    "source": item["source"],
                    "query_family": item["query_family"],
                    "required": item["required"],
                    "state": item["state"],
                    "cursor": item["cursor"],
                    "attempts": item["attempts"],
                    "last_error": item["last_error"],
                    "window_start": document["window_start"],
                    "window_end": document["window_end"],
                }
                for item in document["work_items"].values()
            ],
            "complete": document["state"] == "DONE",
            "unexplored_scope": unexplored,
        }
