# Messenger Notification Setup

## Recommended Option: Telegram

Telegram is the easiest zero-cost option for automated blog messages.

The automation can send:

- A daily morning posting result report after a post draft or public post is uploaded.
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

## Daily Morning Report

The daily pipeline is scheduled for:

```text
09:00 KST every day
```

The Posting Bot daily message includes:

- Blog name and site URL
- Posting status
- Blogger status
- Article title
- Category
- Topic seed
- Quality score
- Blogger URL
- Failure reason if the pipeline fails

## Assisted Setup Command

After creating a Telegram bot with BotFather, send any message to the bot once.

Then run:

```bash
python -m src.pipeline.stage4_telegram_setup --bot-token "YOUR_BOT_TOKEN" --write-env
```

This command will:

- Find the latest chat ID from Telegram `getUpdates`.
- Save `NOTIFICATION_PROVIDER`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` to `.env`.
- Send a test message.

If the bot is in a group or channel, pass the exact chat ID:

```bash
python -m src.pipeline.stage4_telegram_setup --bot-token "YOUR_BOT_TOKEN" --chat-id "YOUR_CHAT_ID" --write-env
```

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
