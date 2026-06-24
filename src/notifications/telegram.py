from __future__ import annotations

import logging
from typing import Any

import requests

from src.config import Settings


LOGGER = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4096


class NotificationClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return (
            self.settings.notification_provider.lower() == "telegram"
            and bool(self.settings.telegram_bot_token)
            and bool(self.settings.telegram_chat_id)
        )

    def send(self, message: str) -> bool:
        if not self.enabled:
            LOGGER.info("Notification skipped because Telegram is not configured.")
            return False

        chunks = split_message(message)
        ok = True
        for chunk in chunks:
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": self.settings.telegram_chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=20,
                )
            except requests.RequestException as exc:
                LOGGER.warning("Telegram notification failed: %s", exc)
                return False
            if not response.ok:
                ok = False
                LOGGER.warning("Telegram notification failed: %s %s", response.status_code, response.text[:500])
        return ok


def get_updates(bot_token: str) -> dict[str, Any]:
    response = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates", timeout=20)
    response.raise_for_status()
    return response.json()


def latest_chat_id(bot_token: str) -> str | None:
    updates = get_updates(bot_token)
    for item in reversed(updates.get("result", [])):
        message = item.get("message") or item.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None:
            return str(chat_id)
    return None


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> bool:
    ok = True
    for chunk in split_message(message):
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not response.ok:
            ok = False
            LOGGER.warning("Telegram notification failed: %s %s", response.status_code, response.text[:500])
    return ok


def split_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_LIMIT:
        return [message]

    chunks = []
    current = ""
    for line in message.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= TELEGRAM_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line
    if current:
        chunks.append(current)
    return chunks
