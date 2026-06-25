from __future__ import annotations

import unittest

from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import REDDIT_DATA_ACCESS_REQUEST_URL
from src.utils.reddit_setup import REDDIT_RESPONSIBLE_BUILDER_POLICY_URL
from src.utils.reddit_setup import github_secret_mapping
from src.utils.reddit_setup import reddit_app_field_guide
from src.utils.reddit_setup import reddit_data_access_request_guide
from src.utils.reddit_setup import reddit_oauth_secret_label
from src.utils.reddit_setup import user_action_checklist


class RedditSetupTests(unittest.TestCase):
    def test_reddit_setup_links_and_secret_label_are_centralized(self) -> None:
        self.assertEqual(REDDIT_APPS_URL, "https://www.reddit.com/prefs/apps")
        self.assertIn("support.reddithelp.com", REDDIT_DATA_ACCESS_REQUEST_URL)
        self.assertIn("42728983564564", REDDIT_RESPONSIBLE_BUILDER_POLICY_URL)
        self.assertIn("/settings/secrets/actions", GITHUB_SECRETS_URL)
        self.assertEqual(reddit_oauth_secret_label(), "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET")

    def test_reddit_app_field_guide_includes_required_setup_values(self) -> None:
        guide = reddit_app_field_guide("Easy PC Fix Guide Automation", "easy-pc-fix-guide/0.1 by user")

        self.assertIn("앱 타입: script", guide)
        self.assertIn("redirect uri: http://localhost:8080", guide)
        self.assertIn("client id: Reddit 앱 이름 아래에 표시되는 짧은 문자열을 REDDIT_CLIENT_ID에 저장하세요.", guide)
        self.assertIn("User-Agent: easy-pc-fix-guide/0.1 by user", guide)

    def test_github_secret_mapping_names_values_to_copy(self) -> None:
        mapping = github_secret_mapping()

        self.assertIn("REDDIT_CLIENT_ID = Reddit 앱 이름 아래에 표시되는 client id", mapping)
        self.assertIn("REDDIT_CLIENT_SECRET = Reddit 앱 상세 화면의 secret", mapping)
        self.assertIn("EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT = 권장 User-Agent 문자열", mapping)

    def test_user_action_checklist_is_copy_ready(self) -> None:
        checklist = user_action_checklist(
            "Easy PC Fix Guide Automation",
            "easy-pc-fix-guide/0.1 by posting-automation-alert-bot",
        )

        joined = "\n".join(checklist)
        self.assertIn("Easy PC Fix Guide Automation", joined)
        self.assertIn("script", joined)
        self.assertIn("http://localhost:8080", joined)
        self.assertIn("REDDIT_CLIENT_ID", joined)
        self.assertIn("REDDIT_CLIENT_SECRET", joined)
        self.assertIn("Data Access Request", joined)
        self.assertIn("reCAPTCHA", joined)
        self.assertIn("Incorrect response", joined)
        self.assertIn("Easy PC Fix Reddit OAuth Health", joined)

    def test_reddit_data_access_request_guide_matches_project(self) -> None:
        guide = reddit_data_access_request_guide()
        joined = "\n".join(guide)

        self.assertIn("Primary-Tax3188", joined)
        self.assertIn("read-only topic research", joined)
        self.assertIn("https://github.com/genesishjh-sketch/korea-easy-guide-automation", joined)
        self.assertIn("r/WindowsHelp", joined)


if __name__ == "__main__":
    unittest.main()
