from __future__ import annotations

import shutil
from pathlib import Path

from src.config import ROOT_DIR


WINDOWS_AI_ASSET_DIR = ROOT_DIR / "src" / "images" / "ai_assets" / "windows"
KOREA_AI_ASSET_DIR = ROOT_DIR / "src" / "images" / "ai_assets" / "korea"


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


def install_korea_ai_assets(article_dir: Path, title: str, keyword: str) -> str:
    scene = korea_scene(f"{keyword} {title}")
    source_dir = KOREA_AI_ASSET_DIR / scene
    if not source_dir.exists():
        source_dir = KOREA_AI_ASSET_DIR / "general"
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Korea AI image library is missing scene '{scene}' and fallback 'general'. "
            "Generate Codex AI images and save hero.jpg/inline-1.jpg/inline-2.jpg before publishing."
        )

    assets_dir = article_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("ai-hero.jpg", "ai-inline-1.jpg", "ai-inline-2.jpg", "ai-inline-3.jpg", "ai-inline-4.jpg"):
        try:
            (assets_dir / stale).unlink()
        except FileNotFoundError:
            pass
    role_assets = [
        ("hero", ("hero.jpg",), "ai-hero.jpg", True),
        ("checklist", ("checklist.jpg", "inline-2.jpg"), "ai-inline-1.jpg", True),
        ("process", ("process.jpg",), "ai-inline-2.jpg", False),
        ("decision", ("decision.jpg",), "ai-inline-3.jpg", False),
    ]
    for role, source_names, target_name, required in role_assets:
        source = next((source_dir / name for name in source_names if (source_dir / name).exists()), None)
        if source is None:
            if required:
                expected = " or ".join(str(source_dir / name) for name in source_names)
                raise FileNotFoundError(f"Missing Korea AI image asset for role '{role}': {expected}")
            continue
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
    if any(token in value for token in ["download stuck", "stuck at 0", "stuck at 0%", "stuck downloading"]):
        return "update_download"
    if any(token in value for token in ["cleanup", "clean up", "disk cleanup", "storage sense"]):
        return "update_cleanup"
    if any(token in value for token in ["0x", "error code", "install error", "update error"]):
        return "update_error_code"
    if any(token in value for token in ["pending restart", "restart stuck", "restart required"]):
        return "update_restart"
    if any(token in value for token in ["update", "restart"]):
        return "update"
    return "general"


def korea_scene(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ["airport", "incheon", "arex", "limousine"]):
        return "airport"
    if any(token in value for token in ["ktx", "korail", "train", "rail"]):
        return "ktx"
    if any(token in value for token in ["esim", "sim", "mobile data", "roaming"]):
        return "esim"
    if any(token in value for token in ["taxi", "kakao t", "ride"]):
        return "taxi"
    if any(token in value for token in ["naver map", "kakaomap", "map", "navigation"]):
        return "map"
    if any(token in value for token in ["t-money", "tmoney", "transport card", "subway", "bus"]):
        return "transport"
    if any(token in value for token in ["baemin", "delivery", "coupang", "shopping", "convenience"]):
        return "delivery"
    return "general"
