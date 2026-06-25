from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.pipeline import stage2_refresh_post


class RefreshPostTests(unittest.TestCase):
    def test_refresh_uses_selected_site_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            stage2_refresh_post, "load_article", return_value=("Title", "<p>Body</p>", ["Windows"])
        ) as load_article, patch.object(stage2_refresh_post, "load_settings") as load_settings, patch.object(
            stage2_refresh_post, "BloggerPublisher"
        ) as publisher:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(json.dumps({"article": {"title": "Title"}}), encoding="utf-8")
            (article_dir / "blogger_publish_result.json").write_text(
                json.dumps({"blogger": {"id": "post-123"}}),
                encoding="utf-8",
            )
            settings = Mock(site_key="easy_pc_fix_guide")
            load_settings.return_value = settings
            publisher.return_value.update_post.return_value = {
                "id": "post-123",
                "url": "https://easypcfixguide.blogspot.com/post.html",
                "selfLink": "https://www.googleapis.com/blogger/v3/blogs/blog/posts/post-123",
                "status": "LIVE",
                "updated": "2026-06-25T00:00:00Z",
            }

            result_path = stage2_refresh_post.run(article_dir, site="easy_pc_fix_guide")
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        load_article.assert_called_once_with(article_dir, "easy_pc_fix_guide")
        load_settings.assert_called_once_with("easy_pc_fix_guide")
        publisher.assert_called_once_with(settings)
        self.assertEqual(payload["blogger"]["id"], "post-123")


if __name__ == "__main__":
    unittest.main()
