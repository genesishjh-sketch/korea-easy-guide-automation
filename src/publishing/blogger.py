from __future__ import annotations

from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import ROOT_DIR, Settings


SCOPES = ["https://www.googleapis.com/auth/blogger"]


class BloggerCredentialsError(RuntimeError):
    pass


class BloggerPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.blog_id = settings.blogger_blog_id
        if not self.blog_id:
            raise BloggerCredentialsError("BLOGGER_BLOG_ID is missing in .env")

    def publish(
        self,
        title: str,
        html: str,
        labels: list[str],
        draft: bool = True,
    ) -> dict[str, Any]:
        service = self._service()
        body = {
            "kind": "blogger#post",
            "blog": {"id": self.blog_id},
            "title": title,
            "content": html,
            "labels": labels,
        }
        request = service.posts().insert(blogId=self.blog_id, body=body, isDraft=draft)
        return request.execute()

    def update_post(
        self,
        post_id: str,
        title: str,
        html: str,
        labels: list[str],
    ) -> dict[str, Any]:
        service = self._service()
        body = {
            "kind": "blogger#post",
            "id": post_id,
            "blog": {"id": self.blog_id},
            "title": title,
            "content": html,
            "labels": labels,
        }
        return service.posts().update(blogId=self.blog_id, postId=post_id, body=body).execute()

    def publish_post(self, post_id: str) -> dict[str, Any]:
        service = self._service()
        return service.posts().publish(blogId=self.blog_id, postId=post_id).execute()

    def upsert_page(self, title: str, html: str) -> dict[str, Any]:
        service = self._service()
        existing = self.find_page_by_title(title)
        body = {
            "kind": "blogger#page",
            "blog": {"id": self.blog_id},
            "title": title,
            "content": html,
        }
        if existing:
            request = service.pages().update(
                blogId=self.blog_id,
                pageId=existing["id"],
                body={**existing, **body},
            )
        else:
            request = service.pages().insert(blogId=self.blog_id, body=body)
        return request.execute()

    def find_page_by_title(self, title: str) -> dict[str, Any] | None:
        service = self._service()
        request = service.pages().list(blogId=self.blog_id, fetchBodies=False)
        while request is not None:
            response = request.execute()
            for page in response.get("items", []):
                if page.get("title", "").strip().lower() == title.strip().lower():
                    return page
            request = service.pages().list_next(request, response)
        return None

    def _service(self):
        credentials = self._credentials()
        return build("blogger", "v3", credentials=credentials)

    def _credentials(self) -> Credentials:
        token_path = self._resolve_path(self.settings.google_oauth_token_file)
        secret_path_value = self.settings.google_oauth_client_secret_file
        if not secret_path_value:
            raise BloggerCredentialsError(
                "GOOGLE_OAUTH_CLIENT_SECRET_FILE is missing in .env. "
                "Create a Google Cloud OAuth Desktop client JSON and set its path."
            )

        secret_path = self._resolve_path(secret_path_value)
        if not secret_path.exists():
            raise BloggerCredentialsError(f"OAuth client secret file does not exist: {secret_path}")

        credentials = None
        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            credentials = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        return credentials

    def _resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path
