from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.content.static_pages import required_pages


ROOT_DIR = Path(__file__).resolve().parents[1]


class StaticPagesDesignTests(unittest.TestCase):
    def test_korea_required_pages_include_terms_and_no_placeholder_email(self) -> None:
        pages = required_pages("Korea Easy Guide", "korea_travel")
        titles = [page.title for page in pages]

        self.assertEqual(titles, ["About", "Contact", "Privacy Policy", "Disclaimer", "Terms"])
        self.assertTrue(all("contact@example.com" not in page.html for page in pages))

    def test_windows_required_pages_include_terms_and_no_placeholder_email(self) -> None:
        pages = required_pages("Easy PC Fix Guide", "windows_help")
        titles = [page.title for page in pages]

        self.assertEqual(titles, ["About", "Contact", "Privacy Policy", "Disclaimer", "Terms"])
        self.assertTrue(all("contact@example.com" not in page.html for page in pages))

    def test_blogger_theme_xml_files_are_well_formed(self) -> None:
        theme_paths = [
            ROOT_DIR / "blogger_themes" / "korea_easy_guide" / "Korea-Easy-Guide-theme.xml",
            ROOT_DIR / "blogger_themes" / "easy_pc_fix_guide" / "Easy-PC-Fix-Guide-theme.xml",
        ]

        for path in theme_paths:
            with self.subTest(path=path):
                ET.parse(path)

    def test_korea_popular_guide_numbers_do_not_wrap(self) -> None:
        theme_path = ROOT_DIR / "blogger_themes" / "korea_easy_guide" / "Korea-Easy-Guide-theme.xml"
        theme = theme_path.read_text(encoding="utf-8")

        self.assertIn(".popular .n", theme)
        self.assertIn("white-space:nowrap", theme)
        self.assertIn("min-width:30px", theme)
        self.assertIn("font-variant-numeric:tabular-nums", theme)

    def test_korea_sidebar_uses_curated_categories_not_all_tags(self) -> None:
        theme_path = ROOT_DIR / "blogger_themes" / "korea_easy_guide" / "Korea-Easy-Guide-theme.xml"
        theme = theme_path.read_text(encoding="utf-8")

        self.assertIn("Main Categories", theme)
        self.assertIn("Travel Basics", theme)
        self.assertIn("Transportation", theme)
        self.assertIn("Korean Apps", theme)
        self.assertNotIn("values='data:labels'", theme)
        self.assertNotIn("class='widget cats'", theme)
        self.assertNotIn("class='widget w-about'", theme)


if __name__ == "__main__":
    unittest.main()
