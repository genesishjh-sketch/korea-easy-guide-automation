from __future__ import annotations


REDDIT_APPS_URL = "https://www.reddit.com/prefs/apps"
GITHUB_SECRETS_URL = "https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions"
REDDIT_CLIENT_ID_SECRET = "REDDIT_CLIENT_ID"
REDDIT_CLIENT_SECRET_SECRET = "REDDIT_CLIENT_SECRET"
REDDIT_OAUTH_SECRET_NAMES = (REDDIT_CLIENT_ID_SECRET, REDDIT_CLIENT_SECRET_SECRET)


def reddit_oauth_secret_label() -> str:
    return ", ".join(REDDIT_OAUTH_SECRET_NAMES)


def reddit_app_field_guide(recommended_app_name: str, recommended_user_agent: str) -> list[str]:
    return [
        f"Reddit 앱 이름: {recommended_app_name}",
        "앱 타입: script",
        "description/about url: 비워도 됩니다.",
        "redirect uri: http://localhost:8080",
        "client id: Reddit 앱 이름 아래에 표시되는 짧은 문자열을 REDDIT_CLIENT_ID에 저장하세요.",
        "client secret: Reddit 앱 상세 화면의 secret 값을 REDDIT_CLIENT_SECRET에 저장하세요.",
        f"User-Agent: {recommended_user_agent}",
    ]


def github_secret_mapping() -> list[str]:
    return [
        "REDDIT_CLIENT_ID = Reddit 앱 이름 아래에 표시되는 client id",
        "REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret",
        "EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT = 권장 User-Agent 문자열",
    ]
