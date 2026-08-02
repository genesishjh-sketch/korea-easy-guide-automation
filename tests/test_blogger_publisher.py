from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from src.publishing.blogger import BloggerPublisher


class BloggerPublisherTests(unittest.TestCase):
    def test_list_live_posts_marks_every_filtered_item_live(self) -> None:
        publisher = BloggerPublisher(
            SimpleNamespace(blogger_blog_id="blog-1"),
        )
        request = MagicMock()
        request.execute.return_value = {
            "items": [
                {"id": "post-1", "title": "One"},
                {"id": "post-2", "title": "Two", "status": "DRAFT"},
            ]
        }
        service = MagicMock()
        service.posts.return_value.list.return_value = request
        service.posts.return_value.list_next.return_value = None

        with patch.object(publisher, "_service", return_value=service):
            posts = publisher.list_live_posts(fetch_bodies=True)

        self.assertEqual([item["status"] for item in posts], ["LIVE", "LIVE"])
        service.posts.return_value.list.assert_called_once_with(
            blogId="blog-1",
            fetchBodies=True,
            status=["LIVE"],
            maxResults=500,
        )


if __name__ == "__main__":
    unittest.main()
