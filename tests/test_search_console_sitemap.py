from __future__ import annotations

import unittest

from src.pipeline.stage3_submit_sitemap import build_message


class SearchConsoleSitemapMessageTests(unittest.TestCase):
    def test_success_message_is_korean_and_contains_sitemap(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "submitted",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
            },
        )

        self.assertIn("Search Console sitemap 제출 결과", message)
        self.assertIn("제출 완료", message)
        self.assertIn("https://easypcfixguide.blogspot.com/sitemap.xml", message)

    def test_error_message_contains_action_items(self) -> None:
        message = build_message(
            "Easy PC Fix Guide",
            {
                "status": "error",
                "site_url": "https://easypcfixguide.blogspot.com/",
                "sitemap_url": "https://easypcfixguide.blogspot.com/sitemap.xml",
                "error": "permission denied",
            },
        )

        self.assertIn("제출 실패", message)
        self.assertIn("permission denied", message)
        self.assertIn("조치 필요", message)


if __name__ == "__main__":
    unittest.main()
