from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from src.topics.ids import normalize_text
from src.topics.migration import _question_from_bundle
from src.topics.store import TopicStore


SITE_SCOPE_CONFLICT_TERMS = {
    "korea_easy_guide": {"windows", "device-specific", "pc fix"},
    "easy_pc_fix_guide": {"korea travel", "ktx", "transit cards"},
}


def _read_bundle(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read archived run {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Archived run must be an object: {path}")
    return payload


def audit_run_projections(store: TopicStore, site: str) -> dict[str, Any]:
    state = store.get_rollout_state(site)
    applied_corrections = {
        str((item.get("details") or {}).get("correction_of") or ""): dict(
            (item.get("details") or {}).get("corrected_details") or {}
        )
        for item in state.get("recent_runs") or []
        if str((item.get("details") or {}).get("run_type") or "").upper()
        == "PROJECTION_REPAIR"
        and (item.get("details") or {}).get("correction_of")
    }
    recorded = {
        str(item.get("run_id") or ""): item
        for item in state.get("recent_runs") or []
    }
    repairs = []
    scope_warnings = []
    for path in sorted((store.site_dir(site) / "runs").glob("*.json")):
        bundle = _read_bundle(path)
        run_id = str(bundle.get("run_id") or path.stem)
        record = recorded.get(run_id)
        if record is None:
            continue
        ended_at = str(bundle.get("ended_at") or bundle.get("run_at") or "")
        questions = [
            _question_from_bundle(site, raw, ended_at)
            for raw in bundle.get("questions") or []
            if isinstance(raw, dict)
        ]
        eligible = [item for item in questions if item.eligible_evidence]
        archived_scope = [str(scope) for scope in bundle.get("unexplored_scope") or []]
        conflicting_scope = [
            scope
            for scope in archived_scope
            if any(
                term in normalize_text(scope)
                for term in SITE_SCOPE_CONFLICT_TERMS.get(site, set())
            )
        ]
        expected = {
            "verified_questions": len(eligible),
            "source_count": len(
                {
                    normalize_text(item.source)
                    for item in eligible
                    if normalize_text(item.source)
                }
            ),
            "unexplored_scope": [
                scope for scope in archived_scope if scope not in conflicting_scope
            ],
        }
        current = dict(
            applied_corrections.get(run_id) or record.get("details") or {}
        )
        changed = {
            key: {
                "current": current.get(key),
                "expected": value,
            }
            for key, value in expected.items()
            if current.get(key) != value
        }
        if changed:
            repair_material = json.dumps(
                {
                    "site": site,
                    "run_id": run_id,
                    "changes": changed,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            repairs.append(
                {
                    "correction_run_id": (
                        f"repair-{run_id}-"
                        + sha256(repair_material.encode("utf-8")).hexdigest()[:10]
                    ),
                    "correction_of": run_id,
                    "run_at": ended_at,
                    "changes": changed,
                    "corrected_details": {**current, **expected},
                }
            )
        for scope in conflicting_scope:
            scope_warnings.append(
                {
                    "run_id": run_id,
                    "scope": scope,
                    "reason": "cross-site unexplored_scope removed in correction",
                }
            )
    return {
        "site": site,
        "repair_count": len(repairs),
        "repairs": repairs,
        "scope_warnings": scope_warnings,
    }


def apply_run_projection_repairs(
    store: TopicStore,
    site: str,
) -> dict[str, Any]:
    report = audit_run_projections(store, site)
    applied = []
    for repair in report["repairs"]:
        details = {
            "run_type": "PROJECTION_REPAIR",
            "correction_of": repair["correction_of"],
            "corrected_details": repair["corrected_details"],
            "changes": repair["changes"],
            "complete": True,
            "schema_valid": True,
        }
        store.record_rollout_run(
            site,
            repair["correction_run_id"],
            "SUCCESS",
            run_at=repair["run_at"],
            qualifying=False,
            details=details,
        )
        applied.append(repair["correction_run_id"])
    return {**report, "applied_correction_run_ids": applied}
