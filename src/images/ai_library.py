from __future__ import annotations

import shutil
from pathlib import Path

from src.config import ROOT_DIR


WINDOWS_AI_ASSET_DIR = ROOT_DIR / "src" / "images" / "ai_assets" / "windows"


def install_windows_ai_assets(article_dir: Path, title: str, keyword: str) -> str:
    scene = windows_scene(f"{keyword} {title}")
    source_dir = WINDOWS_AI_ASSET_DIR / scene
    if not source_dir.exists():
        source_dir = WINDOWS_AI_ASSET_DIR / "general"
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Windows AI image library is missing scene '{scene}' and fallback 'general'. "
            "Generate Codex AI images and save hero.png/inline.png before publishing."
        )

    assets_dir = article_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in (("hero.jpg", "ai-hero.jpg"), ("inline.jpg", "ai-inline-1.jpg")):
        source = source_dir / source_name
        if not source.exists():
            raise FileNotFoundError(f"Missing Windows AI image asset: {source}")
        shutil.copy2(source, assets_dir / target_name)
    return scene


def windows_scene(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ["wi-fi", "wifi", "internet", "network"]):
        return "network"
    if "bluetooth" in value or "device" in value:
        return "device"
    if any(token in value for token in ["sound", "audio", "microphone", "mic"]):
        return "audio"
    if any(token in value for token in ["printer", "scanner"]):
        return "printer"
    if any(token in value for token in ["onedrive", "account", "sign in", "sync"]):
        return "account"
    if any(token in value for token in ["search", "file explorer", "folder", "explorer"]):
        return "files"
    if any(token in value for token in ["boot", "startup", "recovery", "repair"]):
        return "recovery"
    if any(token in value for token in ["version", "edition", "build", "about windows"]):
        return "version"
    if any(token in value for token in ["update", "restart", "0x", "error code"]):
        return "update"
    return "general"
