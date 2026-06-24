from __future__ import annotations

import unittest

from src.content.windows_generator import _sources_for_topic


class WindowsGeneratorSourceTests(unittest.TestCase):
    def test_wifi_topics_include_network_specific_microsoft_sources(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("wifi button missing windows 11")]

        self.assertTrue(any("wi-fi" in url.lower() or "network" in url.lower() for url in urls))
        self.assertTrue(all("microsoft.com" in url or "learn.microsoft.com" in url for url in urls))

    def test_update_error_topics_include_update_specific_microsoft_sources(self) -> None:
        names = [source["name"] for source in _sources_for_topic("windows update error 0x800f0922")]

        self.assertTrue(any("Windows Update" in name for name in names))
        self.assertTrue(any("release health" in name.lower() for name in names))

    def test_app_topics_include_store_or_apps_sources(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("microsoft store not opening windows 11")]

        self.assertTrue(any("Microsoft%20Store" in url for url in urls))

    def test_sources_are_unique(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("windows update error 0x800f0922")]

        self.assertEqual(len(urls), len(set(urls)))


if __name__ == "__main__":
    unittest.main()
