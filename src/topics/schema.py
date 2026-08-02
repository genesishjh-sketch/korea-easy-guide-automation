from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import FormatChecker


SCHEMA_VERSION = 1
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "topics" / "schemas"
SCHEMA_FILES = {
    "weekly": "weekly_research_bundle.schema.json",
    "monthly_bundle": "monthly_proposal_bundle.schema.json",
    "registry": "registry.schema.json",
    "inbox": "inbox.schema.json",
    "categories": "categories.schema.json",
    "proposals": "monthly_proposals.schema.json",
    "sheet_sync": "sheet_sync.schema.json",
    "sheet_decisions": "sheet_decision_bundle.schema.json",
    "research_campaign": "research_campaign.schema.json",
}


def _schema(kind: str) -> dict[str, Any]:
    path = SCHEMA_DIR / SCHEMA_FILES[kind]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load authoritative schema {path}: {exc}") from exc
    Draft202012Validator.check_schema(data)
    return data


def validate_schema(kind: str, instance: Any) -> dict[str, Any]:
    validator = Draft202012Validator(
        _schema(kind),
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    if errors:
        formatted = []
        for error in errors[:20]:
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            formatted.append(f"{location}: {error.message}")
        raise ValueError(f"{kind} schema validation failed: " + "; ".join(formatted))
    if not isinstance(instance, dict):
        raise ValueError(f"{kind} must be a JSON object")
    return instance


def validate_persistent_document(kind: str, data: Any, site: str) -> None:
    document = validate_schema(kind, data)
    if str(document.get("site") or "") != site:
        raise ValueError(f"{kind}.site must be {site}")


def validate_weekly_bundle(bundle: Any) -> dict[str, Any]:
    return validate_schema("weekly", bundle)


def validate_monthly_proposal_bundle(bundle: Any) -> dict[str, Any]:
    return validate_schema("monthly_bundle", bundle)


def validate_sheet_decision_bundle(bundle: Any) -> dict[str, Any]:
    return validate_schema("sheet_decisions", bundle)
