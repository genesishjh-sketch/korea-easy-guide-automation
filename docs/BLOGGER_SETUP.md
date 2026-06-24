# Blogger API Setup

This project publishes generated articles to Blogger with the Blogger API v3.

## Current Blog

- Blog title: `Korea Easy Guide`
- Blog URL: `https://koreaeasyguide.blogspot.com/`
- Blog ID: `288143591612645486`

## Google Cloud Setup

1. Open Google Cloud Console.
2. Create or select a project.
3. Enable `Blogger API v3`.
4. Configure OAuth consent screen.
5. Create OAuth client credentials.
6. Choose application type: `Desktop app`.
7. Download the JSON file.
8. Save it locally as:

```text
korea_blog_automation/.credentials/client_secret.json
```

## Local `.env`

```env
BLOGGER_BLOG_ID=288143591612645486
GOOGLE_OAUTH_CLIENT_SECRET_FILE=.credentials/client_secret.json
GOOGLE_OAUTH_TOKEN_FILE=.credentials/google_token.json
BLOGGER_PUBLISH_MODE=draft
```

## First Auth Run

The first run opens a Google authorization page in your browser.

```bash
python -m src.pipeline.stage2_publish --mode draft
```

After approval, a token is saved at:

```text
.credentials/google_token.json
```

Do not commit `.credentials/` or `.env`.

## Publish Modes

Draft mode:

```bash
python -m src.pipeline.stage2_publish --mode draft
```

Public publish mode:

```bash
python -m src.pipeline.stage2_publish --mode publish
```

Use draft mode until article quality and image hosting are stable.
