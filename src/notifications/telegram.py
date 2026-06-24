from __future__ import annotations

import logging

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
            response = requests.post(
                f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": self.settings.telegram_chat_id,
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
