from __future__ import annotations


REDDIT_APPS_URL = "https://www.reddit.com/prefs/apps"
GITHUB_SECRETS_URL = "https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions"
REDDIT_CLIENT_ID_SECRET = "REDDIT_CLIENT_ID"
REDDIT_CLIENT_SECRET_SECRET = "REDDIT_CLIENT_SECRET"
REDDIT_OAUTH_SECRET_NAMES = (REDDIT_CLIENT_ID_SECRET, REDDIT_CLIENT_SECRET_SECRET)


def reddit_oauth_secret_label() -> str:
    return ", ".join(REDDIT_OAUTH_SECRET_NAMES)
