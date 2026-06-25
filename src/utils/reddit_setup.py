from __future__ import annotations


REDDIT_APPS_URL = "https://www.reddit.com/prefs/apps"
GITHUB_SECRETS_URL = "https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions"
REDDIT_CLIENT_ID_SECRET = "REDDIT_CLIENT_ID"
REDDIT_CLIENT_SECRET_SECRET = "REDDIT_CLIENT_SECRET"
REDDIT_OAUTH_SECRET_NAMES = (REDDIT_CLIENT_ID_SECRET, REDDIT_CLIENT_SECRET_SECRET)
DEFAULT_REDDIT_REDIRECT_URI = "http://localhost:8080"
DEFAULT_REDDIT_USER_AGENT = "easy-pc-fix-guide/0.1 by posting-automation-alert-bot"


def reddit_oauth_secret_label() -> str:
    return ", ".join(REDDIT_OAUTH_SECRET_NAMES)


def reddit_app_field_guide(recommended_app_name: str, recommended_user_agent: str) -> list[str]:
    return [
        f"Reddit 앱 이름: {recommended_app_name}",
        "앱 타입: script",
        "description/about url: 비워도 됩니다.",
        f"redirect uri: {DEFAULT_REDDIT_REDIRECT_URI}",
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


def user_action_checklist(recommended_app_name: str, recommended_user_agent: str) -> list[str]:
    return [
        f"Reddit 앱 페이지에서 create app 또는 create another app을 누르고 이름을 '{recommended_app_name}'로 입력하세요.",
        "앱 타입은 반드시 script를 선택하세요. web app이나 installed app이 아닙니다.",
        f"redirect uri에는 {DEFAULT_REDDIT_REDIRECT_URI}를 그대로 입력하세요.",
        "생성 후 앱 이름 아래의 짧은 client id를 GitHub Secret REDDIT_CLIENT_ID에 저장하세요.",
        "앱 상세의 secret 값을 GitHub Secret REDDIT_CLIENT_SECRET에 저장하세요.",
        f"GitHub Variable EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT가 비어 있으면 '{recommended_user_agent}'로 저장하세요.",
        "저장 후 Actions > Easy PC Fix Reddit OAuth Health workflow를 Run workflow로 실행하세요.",
    ]
