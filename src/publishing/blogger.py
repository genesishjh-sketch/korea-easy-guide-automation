from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build

from src.config import Settings
from src.google_auth import BLOGGER_SCOPE, GoogleCredentialsError, get_credentials


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

    def delete_post(self, post_id: str) -> None:
        service = self._service()
        service.posts().delete(blogId=self.blog_id, postId=post_id).execute()

    def public_post_count(self) -> int:
        service = self._service()
        count = 0
        request = service.posts().list(blogId=self.blog_id, fetchBodies=False, status=["LIVE"])
        while request is not None:
            response = request.execute()
            count += len(response.get("items", []))
            request = service.posts().list_next(request, response)
        return count

    def list_live_posts(self, fetch_bodies: bool = False) -> list[dict[str, Any]]:
        service = self._service()
        posts: list[dict[str, Any]] = []
        request = service.posts().list(blogId=self.blog_id, fetchBodies=fetch_bodies, status=["LIVE"], maxResults=500)
        while request is not None:
            response = request.execute()
            # Blogger's list response does not consistently echo the requested
            # status on each item. The endpoint was explicitly filtered to LIVE,
            # so preserve that verified catalog fact for downstream reconciliation.
            posts.extend(
                {**item, "status": "LIVE"}
                for item in response.get("items", [])
            )
            request = service.posts().list_next(request, response)
        return posts

    def get_post(self, post_id: str) -> dict[str, Any]:
        if not str(post_id or "").strip():
            raise ValueError("post_id is required")
        service = self._service()
        return service.posts().get(
            blogId=self.blog_id,
            postId=str(post_id),
            view="ADMIN",
        ).execute()

    def update_post_labels(
        self,
        post_id: str,
        labels: list[str],
        *,
        post: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = post or self.get_post(post_id)
        body = {
            "kind": "blogger#post",
            "id": str(post_id),
            "blog": {"id": self.blog_id},
            "title": str(current.get("title") or ""),
            "content": str(current.get("content") or ""),
            "labels": list(labels),
        }
        return self._service().posts().update(
            blogId=self.blog_id,
            postId=str(post_id),
            body=body,
        ).execute()

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

    def _credentials(self):
        try:
            return get_credentials(self.settings, [BLOGGER_SCOPE])
        except GoogleCredentialsError as exc:
            raise BloggerCredentialsError(str(exc)) from exc
