from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.content.topic_scoring import infer_category
from src.content.windows_generator import _fixes
from src.content.windows_generator import _meaning
from src.content.windows_generator import _after_each_step
from src.content.windows_generator import _quick_summary
from src.content.windows_generator import _error_title
from src.content.windows_generator import _related_guides
from src.content.windows_generator import _sources_for_topic
from src.content.windows_generator import _symptoms
from src.content.windows_generator import _topic_profile


ROOT_DIR = Path(__file__).resolve().parents[1]


def _direct_microsoft_document_count(urls: list[str]) -> int:
    return sum(
        1
        for url in urls
        if (
            url.startswith("https://support.microsoft.com/en-us/windows/")
            or url.startswith("https://learn.microsoft.com/windows/release-health/")
        )
        and "/search/results" not in url
    )


class WindowsGeneratorSourceTests(unittest.TestCase):
    def test_wifi_topics_include_network_specific_microsoft_sources(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("wifi button missing windows 11")]

        self.assertTrue(any("wi-fi" in url.lower() or "network" in url.lower() for url in urls))
        self.assertTrue(all("microsoft.com" in url or "learn.microsoft.com" in url for url in urls))
        self.assertGreaterEqual(_direct_microsoft_document_count(urls), 2)

    def test_update_error_topics_include_update_specific_microsoft_sources(self) -> None:
        sources = _sources_for_topic("windows update error 0x800f0922")
        names = [source["name"] for source in sources]
        urls = [source["url"] for source in sources]

        self.assertTrue(any("Windows Update" in name for name in names))
        self.assertTrue(any("release health" in name.lower() for name in names))
        self.assertGreaterEqual(_direct_microsoft_document_count(urls), 3)

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

    def test_app_topics_use_specific_app_troubleshooting_copy(self) -> None:
        text = "snipping tool not working windows 11"
        combined = "\n".join(
            [
                *_quick_summary(text, None),
                *_symptoms(text, None),
                *_meaning(text, None),
                *_fixes(text, None),
                *_after_each_step(text),
            ]
        )

        self.assertIn("Snipping Tool", combined)
        self.assertIn("Microsoft Store > Library", combined)
        self.assertIn("Repair", combined)
        self.assertIn("Windows logo key + Shift + S", combined)
        self.assertNotIn("The Windows feature does not respond normally.", combined)
        self.assertNotIn("Wi-Fi button returned", combined)
        self.assertNotIn("printer prints one page", combined)

    def test_windows_version_topic_uses_information_guide_copy(self) -> None:
        text = "how to check windows version"
        profile = _topic_profile(text, "Beginner PC Tips", "https://easypcfixguide.blogspot.com")
        combined = "\n".join(
            [
                profile["title"],
                *profile["quick_summary"],
                *profile["symptoms"],
                *profile["meaning"],
                *profile["try_first"],
                *profile["fixes"],
                *profile["after_each_step"],
                *[item["question"] + " " + item["answer"] for item in profile["faq"]],
            ]
        )

        self.assertEqual(profile["title"], "How to Check Your Windows Version: Simple Steps for Beginners")
        self.assertIn("Settings > System > About", combined)
        self.assertIn("Windows specifications", combined)
        self.assertIn("OS build", combined)
        self.assertIn("System type", combined)
        self.assertIn("winver", combined)
        self.assertNotIn("The Windows feature does not respond normally.", combined)
        self.assertNotIn("Run the relevant Windows troubleshooter.", combined)
        self.assertNotIn("The problem is usually fixable", combined)

    def test_windows_update_pending_restart_topic_uses_specific_copy(self) -> None:
        text = "windows update pending restart stuck"
        profile = _topic_profile(text, "Windows Update", "https://easypcfixguide.blogspot.com")
        combined = "\n".join(
            [
                profile["title"],
                *profile["quick_summary"],
                *profile["before_start"],
                *profile["symptoms"],
                *profile["meaning"],
                *profile["try_first"],
                *profile["fixes"],
                *profile["after_each_step"],
            ]
        )

        self.assertEqual(profile["title"], "Windows Update Pending Restart Stuck: Safe Fixes for Beginners")
        self.assertIn("Pending restart", combined)
        self.assertIn("Restart now", combined)
        self.assertIn("Windows Update troubleshooter", combined)
        self.assertIn("Windows release health", combined)
        self.assertIn("free space", combined)
        self.assertNotIn("The Windows feature does not respond normally.", combined)
        self.assertNotIn("Open the related Windows Settings page", combined)
        self.assertNotIn("printer prints one page", combined)

    def test_printer_queue_topic_uses_queue_specific_title_and_copy(self) -> None:
        text = "how to clear printer queue"
        profile = _topic_profile(text, "Printer & Scanner", "https://easypcfixguide.blogspot.com")
        combined = "\n".join(
            [
                *profile["quick_summary"],
                *profile["symptoms"],
                *profile["meaning"],
                *profile["try_first"],
                *profile["fixes"],
            ]
        )

        self.assertEqual(profile["title"], "How to Clear the Printer Queue on Windows: Safe Steps for Beginners")
        self.assertEqual(profile["slug"], "how-to-clear-the-printer-queue-on-windows-safe-steps-for-beginners")
        self.assertIn("stuck printer queue", combined)
        self.assertIn("cancel", combined.lower())
        self.assertIn("one test page", combined)
        self.assertNotIn("Windows says the printer is offline.", combined)
        self.assertNotIn("A printer can also appear offline", combined)

    def test_specific_printer_topics_preserve_distinctive_seed_intent(self) -> None:
        cases = {
            "printer driver unavailable windows 11": "Printer Driver Unavailable on Windows 11: Safe Fixes for Beginners",
            "printer stuck deleting windows 11": "Printer Job Stuck Deleting on Windows 11: Safe Fixes for Beginners",
            "default printer keeps changing windows": "Default Printer Keeps Changing on Windows: Safe Fixes for Beginners",
        }

        slugs = set()
        for seed, expected_title in cases.items():
            with self.subTest(seed=seed):
                profile = _topic_profile(seed, "Printer & Scanner", "https://easypcfixguide.blogspot.com")
                combined = "\n".join(
                    [
                        profile["title"],
                        *profile["quick_summary"],
                        *profile["symptoms"],
                        *profile["meaning"],
                        *profile["try_first"],
                        *profile["fixes"],
                    ]
                ).lower()

                self.assertEqual(profile["title"], expected_title)
                self.assertNotEqual(profile["title"], "Printer Says Offline on Windows 11? Simple Fixes for Beginners")
                self.assertNotEqual(profile["title"], "How to Clear the Printer Queue on Windows: Safe Steps for Beginners")
                for word in [part for part in seed.split() if len(part) > 3]:
                    self.assertIn(word.lower(), combined)
                slugs.add(profile["slug"])

        self.assertEqual(len(slugs), len(cases))

    def test_network_connection_topics_preserve_distinctive_seed_intent(self) -> None:
        cases = {
            "wifi keeps disconnecting windows 11": "Wi-Fi Keeps Disconnecting on Windows 11: Safe Fixes for Beginners",
            "network adapter missing windows 11": "Network Adapter Missing on Windows 11: Safe Fixes for Beginners",
            "windows cannot connect to this network": "Windows Cannot Connect to This Network: Safe Fixes for Beginners",
            "no internet secured windows 11": "No Internet, Secured on Windows 11: Safe Fixes for Beginners",
            "dns server not responding windows 11": "DNS Server Not Responding on Windows 11: Safe Fixes for Beginners",
            "ethernet connected but no internet windows 11": "Ethernet Connected but No Internet on Windows 11: Safe Fixes for Beginners",
        }

        for seed, expected_title in cases.items():
            with self.subTest(seed=seed):
                profile = _topic_profile(seed, "Wi-Fi & Internet", "https://easypcfixguide.blogspot.com")
                combined = "\n".join(
                    [
                        profile["title"],
                        *profile["quick_summary"],
                        *profile["symptoms"],
                        *profile["meaning"],
                        *profile["try_first"],
                        *profile["fixes"],
                    ]
                ).lower()

                self.assertEqual(profile["title"], expected_title)
                normalized_combined = combined.replace("wi-fi", "wifi")
                for word in [part for part in seed.replace(",", "").split() if len(part) > 3]:
                    self.assertIn(word.lower(), normalized_combined)
                self.assertNotEqual(profile["title"], "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners")

    def test_related_guides_use_internal_blog_search_links(self) -> None:
        guides = _related_guides("Apps & Settings", "https://easypcfixguide.blogspot.com")

        self.assertGreaterEqual(len(guides), 3)
        self.assertTrue(all(guide["title"] for guide in guides))
        self.assertTrue(all(guide["url"].startswith("https://easypcfixguide.blogspot.com/search?q=") for guide in guides))

    def test_related_guides_follow_topic_intent_inside_category(self) -> None:
        cases = {
            ("Wi-Fi & Internet", "wifi keeps disconnecting windows 11"): "Wi-Fi keeps disconnecting on Windows",
            ("Wi-Fi & Internet", "dns server not responding windows 11"): "DNS server not responding on Windows",
            ("Printer & Scanner", "printer driver unavailable windows 11"): "Printer driver unavailable on Windows",
            ("Apps & Settings", "settings app not opening windows 11"): "Windows Settings app not opening",
            ("Bluetooth & Devices", "sound not working windows 11"): "No sound after Windows update",
            ("Recovery & Startup", "safe mode windows 11"): "How to start Windows in Safe Mode",
        }

        for (category, keyword), expected_title in cases.items():
            with self.subTest(keyword=keyword):
                guides = _related_guides(category, "https://easypcfixguide.blogspot.com", keyword)
                titles = [guide["title"] for guide in guides]

                self.assertIn(expected_title, titles)
                self.assertEqual(len(guides), 3)
                self.assertTrue(all(guide["url"].startswith("https://easypcfixguide.blogspot.com/search?q=") for guide in guides))

    def test_sources_are_unique(self) -> None:
        urls = [source["url"] for source in _sources_for_topic("windows update error 0x800f0922")]

        self.assertEqual(len(urls), len(set(urls)))

    def test_device_topics_use_direct_microsoft_documents_not_only_search(self) -> None:
        topics = [
            "bluetooth not working windows 11",
            "printer says offline windows 11",
        ]

        for topic in topics:
            with self.subTest(topic=topic):
                urls = [source["url"] for source in _sources_for_topic(topic)]

                self.assertGreaterEqual(_direct_microsoft_document_count(urls), 3)
                self.assertFalse(any(url.endswith("/windows/bluetooth") for url in urls))
                self.assertFalse(any(url.endswith("/windows/printers-scanners") for url in urls))

    def test_common_topic_groups_prioritize_direct_microsoft_documents(self) -> None:
        topics = [
            "microsoft store not opening windows 11",
            "settings app not opening windows 11",
            "camera not working windows 11",
            "sound not working windows 11",
            "file explorer keeps freezing windows 11",
            "disk space low windows 11",
            "safe mode windows 11",
            "windows hello pin not working",
        ]

        for topic in topics:
            with self.subTest(topic=topic):
                urls = [source["url"] for source in _sources_for_topic(topic)]
                search_urls = [url for url in urls if "/search/results" in url]

                self.assertGreaterEqual(_direct_microsoft_document_count(urls), 5)
                self.assertLessEqual(len(search_urls), 1)

    def test_launch_queue_topics_have_enough_microsoft_sources_for_hades(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_launch_queue.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                sources = _sources_for_topic(seed)

                self.assertGreaterEqual(len(sources), 6)
                self.assertTrue(
                    all("microsoft.com" in source["url"] or "learn.microsoft.com" in source["url"] for source in sources)
                )

    def test_all_easy_pc_topic_seeds_have_enough_microsoft_sources_for_hades(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_topic_seeds.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                sources = _sources_for_topic(seed)

                self.assertGreaterEqual(len(sources), 6)
                self.assertGreaterEqual(_direct_microsoft_document_count([source["url"] for source in sources]), 2)
                self.assertTrue(
                    all("microsoft.com" in source["url"] or "learn.microsoft.com" in source["url"] for source in sources)
                )

    def test_beginner_pc_tip_seeds_have_enough_microsoft_sources_for_hades(self) -> None:
        seeds = [
            "how to make text bigger on windows",
            "how to take a screenshot on windows",
            "how to check windows version",
        ]

        for seed in seeds:
            with self.subTest(seed=seed):
                sources = _sources_for_topic(seed)
                urls = [source["url"] for source in sources]

                self.assertGreaterEqual(len(sources), 6)
                self.assertGreaterEqual(_direct_microsoft_document_count(urls), 6)
                self.assertTrue(
                    all("microsoft.com" in source["url"] or "learn.microsoft.com" in source["url"] for source in sources)
                )

    def test_launch_queue_topics_do_not_fall_back_to_generic_computer_help(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_launch_queue.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                self.assertNotEqual(infer_category(seed, "windows_help"), "Computer Help")

    def test_all_easy_pc_topic_seeds_do_not_fall_back_to_generic_computer_help(self) -> None:
        seeds = json.loads((ROOT_DIR / "data" / "seeds" / "windows_topic_seeds.json").read_text(encoding="utf-8"))

        for seed in seeds:
            with self.subTest(seed=seed):
                self.assertNotEqual(infer_category(seed, "windows_help"), "Computer Help")


if __name__ == "__main__":
    unittest.main()
