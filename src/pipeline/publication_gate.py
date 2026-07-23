from __future__ import annotations

import json
import os
from pathlib import Path


def new_publication_created(result: dict) -> bool:
    if isinstance(result.get("published"), list):
        return bool(result["published"])
    if result.get("mode") != "publish" or result.get("daily_limit_skipped"):
        return False
    result_path = Path(str(result.get("publish_result") or ""))
    if not result_path.exists():
        return False
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    blogger = payload.get("blogger") or {}
    return (
        not payload.get("draft")
        and not payload.get("skipped")
        and str(blogger.get("status") or "").upper() == "LIVE"
        and bool(blogger.get("url"))
    )


def write_github_publication_output(result: dict) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    value = "true" if new_publication_created(result) else "false"
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"new_publication={value}\n")
