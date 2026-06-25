from __future__ import annotations

import json
from pathlib import Path

from src.config import ROOT_DIR


def read_daily_success_report(site_key: str, report_dir: Path | None = None) -> dict:
    directory = report_dir or ROOT_DIR / "reports"
    path = directory / f"{site_key}-daily-success.json"
    if not path.exists():
        return {"status": "not_uploaded", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}
    data.setdefault("path", str(path))
    if is_validation_success_report(data):
        return migrate_legacy_validation_success_report(site_key, path, data)
    return data


def is_validation_success_report(report: dict) -> bool:
    return report.get("mode") == "validate" or report.get("status") == "validated"


def migrate_legacy_validation_success_report(site_key: str, path: Path, data: dict) -> dict:
    validation_path = path.with_name(f"{site_key}-daily-validation-success.json")
    migrated_payload = dict(data)
    migrated_payload["path"] = str(validation_path)
    migrated_payload["migrated_from"] = str(path)
    if not validation_path.exists():
        validation_path.write_text(json.dumps(migrated_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return {
        "status": "not_uploaded",
        "path": str(path),
        "migrated_legacy_validation_report": str(validation_path),
        "note": "Legacy validate-mode daily-success report was moved to daily-validation-success.",
    }
