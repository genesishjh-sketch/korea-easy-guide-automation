from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    app_env: str
    site_name: str
    site_url: str
    default_author: str
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


def load_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        site_name=os.getenv("SITE_NAME", "Korea Easy Guide"),
        site_url=os.getenv("SITE_URL", "https://koreaeasyguide.blogspot.com"),
        default_author=os.getenv("DEFAULT_AUTHOR", "Korea Easy Guide Editorial Team"),
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "korea-easy-guide/0.1"),
        google_search_provider=os.getenv("GOOGLE_SEARCH_PROVIDER", "suggest"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", ""),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        blogger_blog_id=os.getenv("BLOGGER_BLOG_ID", ""),
        google_oauth_client_secret_file=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", ""),
        google_oauth_token_file=os.getenv("GOOGLE_OAUTH_TOKEN_FILE", ".credentials/google_token.json"),
        blogger_publish_mode=os.getenv("BLOGGER_PUBLISH_MODE", "draft"),
        search_console_site_url=os.getenv("SEARCH_CONSOLE_SITE_URL", os.getenv("SITE_URL", "https://koreaeasyguide.blogspot.com")),
        ga4_property_id=os.getenv("GA4_PROPERTY_ID", ""),
        ga4_measurement_id=os.getenv("GA4_MEASUREMENT_ID", ""),
    )
