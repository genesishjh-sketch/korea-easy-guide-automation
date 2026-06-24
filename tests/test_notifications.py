from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from src.notifications.telegram import NotificationClient
from src.notifications.telegram import split_message


class TelegramNotificationTests(unittest.TestCase):
    def test_send_returns_false_when_telegram_request_raises(self) -> None:
        settings = SimpleNamespace(
            notification_provider="telegram",
            telegram_bot_token="token",
            telegram_chat_id="123",
        )
        client = NotificationClient(settings)

        with patch("src.notifications.telegram.requests.post", side_effect=requests.Timeout("timeout")):
            sent = client.send("hello")

        self.assertFalse(sent)

    def test_split_message_keeps_chunks_under_telegram_limit(self) -> None:
        message = "\n".join(["line " + ("x" * 100)] * 80)
        chunks = split_message(message)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
