from __future__ import annotations

import argparse
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.notifications.telegram import latest_chat_id, send_telegram_message


def update_env(values: dict[str, str]) -> None:
    env_path = ROOT_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    existing = {}
    for index, line in enumerate(lines):
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0]
        existing[key] = index

    for key, value in values.items():
        if key in existing:
            lines[existing[key]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(bot_token: str | None, chat_id: str | None, write_env: bool, message: str) -> dict[str, str | bool | None]:
    settings = load_settings()
    selected_token = bot_token or settings.telegram_bot_token
    if not selected_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing. Create a bot with BotFather and pass --bot-token.")

    selected_chat_id = chat_id or settings.telegram_chat_id or latest_chat_id(selected_token)
    if not selected_chat_id:
        raise ValueError(
            "TELEGRAM_CHAT_ID was not found. Send any message to your Telegram bot first, then run this command again."
        )

    if write_env:
        update_env(
            {
                "NOTIFICATION_PROVIDER": "telegram",
                "TELEGRAM_BOT_TOKEN": selected_token,
                "TELEGRAM_CHAT_ID": selected_chat_id,
            }
        )

    sent = send_telegram_message(selected_token, selected_chat_id, message)
    return {
        "notification_provider": "telegram",
        "chat_id": selected_chat_id,
        "env_updated": write_env,
        "test_message_sent": sent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure and test Telegram notifications.")
    parser.add_argument("--bot-token", help="Telegram bot token from BotFather.")
    parser.add_argument("--chat-id", help="Telegram chat id. If omitted, getUpdates is used.")
    parser.add_argument("--write-env", action="store_true", help="Write Telegram settings to local .env.")
    parser.add_argument(
        "--message",
        default="[Korea Easy Guide] Telegram notification test complete.",
        help="Test message to send.",
    )
    args = parser.parse_args()
    try:
        result = run(args.bot_token, args.chat_id, args.write_env, args.message)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
