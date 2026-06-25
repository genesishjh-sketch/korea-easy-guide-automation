from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.content.topic_scoring import infer_category
from src.content.windows_generator import _fixes
from src.content.windows_generator import _meaning
from src.content.windows_generator import _quick_summary
from src.content.windows_generator import _error_title
from src.content.windows_generator import _related_guides
from src.content.windows_generator import _sources_for_topic
from src.content.windows_generator import _symptoms


ROOT_DIR = Path(__file__).resolve().parents[1]


class WindowsGeneratorSourceTests(unittest.TestCase):
    def test_wifi_topics_include_network_specific_microsoft_sources(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("wifi button missing windows 11")]

        self.assertTrue(any("wi-fi" in url.lower() or "network" in url.lower() for url in urls))
        self.assertTrue(all("microsoft.com" in url or "learn.microsoft.com" in url for url in urls))

    def test_update_error_topics_include_update_specific_microsoft_sources(self) -> None:
        names = [source["name"] for source in _sources_for_topic("windows update error 0x800f0922")]

        self.assertTrue(any("Windows Update" in name for name in names))
        self.assertTrue(any("release health" in name.lower() for name in names))

    def test_onedrive_error_topics_keep_onedrive_title_and_sources(self) -> None:
        title = _error_title("onedrive error 0x8004de40", "0X8004DE40")
        names = [source["name"] for source in _sources_for_topic("onedrive error 0x8004de40")]

        self.assertEqual(title, "OneDrive Error 0X8004DE40: What It Means and How to Fix It")
        self.assertTrue(any("OneDrive" in name for name in names))
        self.assertFalse(title.startswith("Windows Update Error"))

    def test_onedrive_error_body_sections_do_not_use_windows_update_fix_copy(self) -> None:
        text = "onedrive error 0x8004de40"
        combined = "\n".join(
            [
                *_quick_summary(text, "0X8004DE40"),
                *_symptoms(text, "0X8004DE40"),
                *_meaning(text, "0X8004DE40"),
                *_fixes(text, "0X8004DE40"),
            ]
        )

        self.assertIn("OneDrive", combined)
        self.assertIn("Microsoft account", combined)
        self.assertNotIn("Windows Update troubleshooter", combined)
        self.assertNotIn("Windows Update shows 0X8004DE40", combined)

    def test_app_topics_include_store_or_apps_sources(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("microsoft store not opening windows 11")]

        self.assertTrue(any("Microsoft%20Store" in url for url in urls))

    def test_related_guides_use_internal_blog_search_links(self) -> None:
        guides = _related_guides("Apps & Settings", "https://easypcfixguide.blogspot.com")

        self.assertGreaterEqual(len(guides), 3)
        self.assertTrue(all(guide["title"] for guide in guides))
        self.assertTrue(all(guide["url"].startswith("https://easypcfixguide.blogspot.com/search?q=") for guide in guides))

    def test_sources_are_unique(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("windows update error 0x800f0922")]

        self.assertEqual(len(urls), len(set(urls)))

    def test_launch_queue_topics_have_enough_microsoft_sources_for_hades(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_launch_queue.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                sources = _sources_for_topic(seed)

                self.assertGreaterEqual(len(sources), 6)
                self.assertTrue(
                    all("microsoft.com" in source["url"] or "learn.microsoft.com" in source["url"] for source in sources)
                )

    def test_launch_queue_topics_do_not_fall_back_to_generic_computer_help(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_launch_queue.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                self.assertNotEqual(infer_category(seed, "windows_help"), "Computer Help")


if __name__ == "__main__":
    unittest.main()
