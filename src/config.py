from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

from src.sites import get_site_profile


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    site_key: str
    app_env: str
    site_name: str
    site_url: str
    default_author: str
    content_domain: str
    seed_file: str
    generated_output_dir: str
    automation_start_date: str
    reddit_subreddits: list[str]
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    google_search_provider: str
    google_api_key: str
    google_cse_id: str
    pexels_api_key: str
    blogger_blog_id: str
    google_oauth_client_secret_file: str
    google_oauth_token_file: str
    blogger_publish_mode: str
    search_console_site_url: str
    ga4_property_id: str
    ga4_measurement_id: str
    notification_provider: str
    telegram_bot_token: str
    telegram_chat_id: str


def load_settings(site_key: str | None = None) -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    selected_site_key = site_key or os.getenv("SITE_KEY", "korea_easy_guide")
    profile = get_site_profile(selected_site_key)
    prefix = profile.key.upper()
    allow_global_site_values = profile.key == (os.getenv("SITE_KEY") or "korea_easy_guide")

    def getenv(name: str, default: str = "") -> str:
        return os.getenv(f"{prefix}_{name}") or os.getenv(name, default)

    def site_getenv(name: str, default: str = "") -> str:
        if os.getenv(f"{prefix}_{name}"):
            return os.getenv(f"{prefix}_{name}", default)
        if allow_global_site_values:
            return os.getenv(name, default)
        return default

    return Settings(
        site_key=profile.key,
        app_env=getenv("APP_ENV", "local"),
        site_name=site_getenv("SITE_NAME", profile.name),
        site_url=site_getenv("SITE_URL", profile.url),
        default_author=site_getenv("DEFAULT_AUTHOR", profile.author),
        content_domain=site_getenv("CONTENT_DOMAIN", profile.content_domain),
        seed_file=site_getenv("SEED_FILE", str(profile.seed_file)),
        generated_output_dir=site_getenv("GENERATED_OUTPUT_DIR", str(profile.output_dir)),
        automation_start_date=site_getenv("AUTOMATION_START_DATE", profile.automation_start_date),
        reddit_subreddits=[
            value.strip()
            for value in site_getenv("REDDIT_SUBREDDITS", ",".join(profile.reddit_subreddits)).split(",")
            if value.strip()
        ],
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        reddit_user_agent=site_getenv("REDDIT_USER_AGENT", profile.reddit_user_agent),
        google_search_provider=os.getenv("GOOGLE_SEARCH_PROVIDER", "suggest"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        blogger_blog_id=site_getenv("BLOGGER_BLOG_ID", profile.default_blogger_blog_id),
        google_oauth_client_secret_file=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", ""),
        google_oauth_token_file=os.getenv("GOOGLE_OAUTH_TOKEN_FILE", ".credentials/google_token.json"),
        blogger_publish_mode=os.getenv("BLOGGER_PUBLISH_MODE", "draft"),
        search_console_site_url=site_getenv("SEARCH_CONSOLE_SITE_URL", profile.default_search_console_site_url or profile.url),
        ga4_property_id=site_getenv("GA4_PROPERTY_ID", ""),
        ga4_measurement_id=site_getenv("GA4_MEASUREMENT_ID", profile.default_ga4_measurement_id),
        notification_provider=os.getenv("NOTIFICATION_PROVIDER", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )
