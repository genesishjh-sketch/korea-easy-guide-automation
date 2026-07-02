from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from google.auth.exceptions import RefreshError

from src.config import Settings
from src.google_auth import BLOGGER_SCOPE
from src.google_auth import GoogleCredentialsError
from src.google_auth import get_credentials


def fake_settings(root: Path) -> Settings:
    return Settings(
        site_key="korea_easy_guide",
        app_env="local",
        site_name="Korea Easy Guide",
        site_url="https://koreaeasyguide.blogspot.com",
        default_author="Guide Studio",
        content_domain="korea_travel",
        seed_file="",
        launch_seed_file="",
        generated_output_dir="",
        automation_start_date="2026-06-24",
        reddit_subreddits=[],
        reddit_client_id="",
        reddit_client_secret="",
        reddit_user_agent="",
        reddit_data_access_request_submitted_at="",
        google_search_provider="suggest",
        google_api_key="",
        google_cse_id="",
        pexels_api_key="",
        blogger_blog_id="123",
        google_oauth_client_secret_file=str(root / "client_secret.json"),
        google_oauth_token_file=str(root / "google_token.json"),
        blogger_publish_mode="publish",
        search_console_site_url="",
        ga4_property_id="",
        ga4_measurement_id="",
        notification_provider="",
        telegram_bot_token="",
        telegram_chat_id="",
    )


class GoogleAuthTests(unittest.TestCase):
    def test_local_invalid_grant_starts_new_oauth_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = fake_settings(root)
            Path(settings.google_oauth_client_secret_file).write_text("{}", encoding="utf-8")
            Path(settings.google_oauth_token_file).write_text("{}", encoding="utf-8")
            expired = Mock(expired=True, refresh_token="refresh", valid=False)
            expired.has_scopes.return_value = True
            expired.refresh.side_effect = RefreshError("invalid_grant")
            fresh = Mock(valid=True)
            fresh.to_json.return_value = '{"token":"fresh"}'

            with patch("src.google_auth.Credentials.from_authorized_user_file", return_value=expired), patch(
                "src.google_auth.InstalledAppFlow"
            ) as flow, patch.dict("os.environ", {"GITHUB_ACTIONS": ""}):
                flow.from_client_secrets_file.return_value.run_local_server.return_value = fresh
                credentials = get_credentials(settings, [BLOGGER_SCOPE])

        self.assertIs(credentials, fresh)
        flow.from_client_secrets_file.return_value.run_local_server.assert_called_once_with(port=0)

    def test_github_actions_invalid_grant_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = fake_settings(root)
            Path(settings.google_oauth_client_secret_file).write_text("{}", encoding="utf-8")
            Path(settings.google_oauth_token_file).write_text("{}", encoding="utf-8")
            expired = Mock(expired=True, refresh_token="refresh", valid=False)
            expired.has_scopes.return_value = True
            expired.refresh.side_effect = RefreshError("invalid_grant")

            with patch("src.google_auth.Credentials.from_authorized_user_file", return_value=expired), patch.dict(
                "os.environ", {"GITHUB_ACTIONS": "true"}
            ):
                with self.assertRaises(GoogleCredentialsError) as raised:
                    get_credentials(settings, [BLOGGER_SCOPE])

        self.assertIn("Regenerate the token locally", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
