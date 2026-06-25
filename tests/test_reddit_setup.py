from __future__ import annotations

import unittest

from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import reddit_oauth_secret_label


class RedditSetupTests(unittest.TestCase):
    def test_reddit_setup_links_and_secret_label_are_centralized(self) -> None:
        self.assertEqual(REDDIT_APPS_URL, "https://www.reddit.com/prefs/apps")
        self.assertIn("/settings/secrets/actions", GITHUB_SECRETS_URL)
        self.assertEqual(reddit_oauth_secret_label(), "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET")


if __name__ == "__main__":
    unittest.main()
