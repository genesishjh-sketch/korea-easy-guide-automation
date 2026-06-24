from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]


class WorkflowSafetyTests(unittest.TestCase):
    def test_easy_pc_daily_runs_safety_tests_before_publish(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        install_index = workflow.index("- name: Install dependencies")
        test_index = workflow.index("- name: Run safety regression tests")
        oauth_index = workflow.index("- name: Write Google OAuth files")
        publish_index = workflow.index("- name: Run Easy PC Fix daily pipeline")

        self.assertLess(install_index, test_index)
        self.assertLess(test_index, oauth_index)
        self.assertLess(oauth_index, publish_index)

    def test_easy_pc_daily_submits_sitemap_only_for_publish_mode(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        self.assertIn("- name: Submit sitemap", workflow)
        self.assertIn("env.BLOGGER_PUBLISH_MODE == 'publish'", workflow)
        self.assertNotIn("- name: Submit sitemap\n        if: always()", workflow)

    def test_easy_pc_validate_runs_preflight(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-validate-smoke.yml").read_text(encoding="utf-8")

        self.assertIn("- name: Run automation preflight", workflow)
        self.assertIn("python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide", workflow)
        self.assertIn("reports/easy_pc_fix_guide-preflight.json", workflow)

    def test_easy_pc_publication_check_uploads_report(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-publication-check.yml").read_text(encoding="utf-8")

        self.assertIn("python -m src.pipeline.stage4_publication_check --site easy_pc_fix_guide --after-hour 9", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("reports/easy_pc_fix_guide-publication-check.json", workflow)


if __name__ == "__main__":
    unittest.main()
