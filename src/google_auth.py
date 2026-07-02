from __future__ import annotations

from pathlib import Path
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import ROOT_DIR, Settings


BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
SEARCH_CONSOLE_SUBMIT_SCOPE = "https://www.googleapis.com/auth/webmasters"
ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

DEFAULT_SCOPES = [
    BLOGGER_SCOPE,
    SEARCH_CONSOLE_SUBMIT_SCOPE,
    ANALYTICS_READONLY_SCOPE,
]


class GoogleCredentialsError(RuntimeError):
    pass


def get_credentials(settings: Settings, scopes: list[str] | None = None) -> Credentials:
    selected_scopes = scopes or DEFAULT_SCOPES
    token_path = token_path_for_scopes(settings.google_oauth_token_file, selected_scopes)
    secret_path_value = settings.google_oauth_client_secret_file
    if not secret_path_value:
        raise GoogleCredentialsError(
            "GOOGLE_OAUTH_CLIENT_SECRET_FILE is missing in .env. "
            "Create a Google Cloud OAuth Desktop client JSON and set its path."
        )

    secret_path = resolve_path(secret_path_value)
    if not secret_path.exists():
        raise GoogleCredentialsError(f"OAuth client secret file does not exist: {secret_path}")

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), selected_scopes)

    if credentials and credentials.expired and credentials.refresh_token and credentials.has_scopes(selected_scopes):
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
                raise GoogleCredentialsError(
                    f"Google OAuth token refresh failed for {token_path.name}. "
                    "Regenerate the token locally and update the matching GitHub Secret."
                ) from exc
            credentials = None

    if not credentials or not credentials.valid or not credentials.has_scopes(selected_scopes):
        if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            raise GoogleCredentialsError(
                f"Google OAuth token is invalid or missing for {token_path.name}. "
                "Regenerate the token locally and update the matching GitHub Secret."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), selected_scopes)
        credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def token_path_for_scopes(base_token_file: str, scopes: list[str]) -> Path:
    base_path = resolve_path(base_token_file)
    scope_set = set(scopes)
    if scope_set == {BLOGGER_SCOPE}:
        return base_path
    if scope_set == {SEARCH_CONSOLE_SUBMIT_SCOPE}:
        return base_path.with_name(f"{base_path.stem}.search-console{base_path.suffix}")
    if scope_set == {ANALYTICS_READONLY_SCOPE}:
        return base_path.with_name(f"{base_path.stem}.analytics{base_path.suffix}")
    return base_path.with_name(f"{base_path.stem}.combined{base_path.suffix}")
