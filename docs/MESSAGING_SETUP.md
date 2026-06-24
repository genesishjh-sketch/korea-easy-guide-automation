# Messenger Notification Setup

## Recommended Option: Telegram

Telegram is the easiest zero-cost option for automated blog messages.

The automation can send:

- A daily completion message after a post draft is uploaded.
- The weekly Korean report after it is generated.

## Environment Variables

```text
NOTIFICATION_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

## How To Create A Telegram Bot

1. Open Telegram.
2. Search for `BotFather`.
3. Send `/newbot`.
4. Choose a bot name and username.
5. Copy the bot token.
6. Send one message to your new bot.
7. Open this URL in a browser after replacing the token:

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

8. Find your `chat.id` value and use it as `TELEGRAM_CHAT_ID`.

## Local Test

After `.env` is configured:

```bash
python -m src.pipeline.stage3_weekly_report
```

If Telegram is configured correctly, the report will arrive as a message.

## GitHub Actions Variables And Secrets

Set these repository variables:

```text
NOTIFICATION_PROVIDER=telegram
TELEGRAM_CHAT_ID=123456789
SEARCH_CONSOLE_SITE_URL=https://koreaeasyguide.blogspot.com/
GA4_PROPERTY_ID=336981737
```

Set these repository secrets:

```text
TELEGRAM_BOT_TOKEN
GOOGLE_OAUTH_CLIENT_SECRET_JSON
GOOGLE_OAUTH_TOKEN_JSON
GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON
GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON
```

`GOOGLE_OAUTH_TOKEN_JSON` is used by Blogger publishing.

`GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON` and `GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON` are used by the report workflow.
