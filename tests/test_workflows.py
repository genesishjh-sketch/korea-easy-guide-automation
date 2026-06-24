from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]


class WorkflowSafetyTests(unittest.TestCase):
    def test_workflows_use_node24_compatible_actions(self) -> None:
        workflow_dirs = [ROOT_DIR / ".github" / "workflows", ROOT_DIR / "docs" / "github-workflows"]
        workflow_text = "\n".join(
            path.read_text(encoding="utf-8")
            for workflow_dir in workflow_dirs
            for path in workflow_dir.glob("*.yml")
        )

        self.assertNotIn("actions/checkout@v4", workflow_text)
        self.assertNotIn("actions/setup-python@v5", workflow_text)
        self.assertNotIn("actions/upload-artifact@v4", workflow_text)
        self.assertIn("actions/checkout@v5", workflow_text)
        self.assertIn("actions/setup-python@v6", workflow_text)
        self.assertIn("actions/upload-artifact@v6", workflow_text)

    def test_workflows_pin_python_311(self) -> None:
        workflow_dirs = [ROOT_DIR / ".github" / "workflows", ROOT_DIR / "docs" / "github-workflows"]

        for workflow_dir in workflow_dirs:
            for path in workflow_dir.glob("*.yml"):
                workflow = path.read_text(encoding="utf-8")
                self.assertIn('python-version: "3.11"', workflow, path.name)

    def test_korea_daily_runs_safety_tests_before_oauth(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "daily-draft.yml").read_text(encoding="utf-8")

        install_index = workflow.index("- name: Install dependencies")
        test_index = workflow.index("- name: Run safety regression tests")
        oauth_index = workflow.index("- name: Write Google OAuth files")
        draft_index = workflow.index("- name: Run daily draft pipeline")

        self.assertLess(install_index, test_index)
        self.assertLess(test_index, oauth_index)
        self.assertLess(oauth_index, draft_index)

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
        self.assertIn("success() && env.BLOGGER_PUBLISH_MODE == 'publish'", workflow)
        self.assertNotIn("always() && env.BLOGGER_PUBLISH_MODE == 'publish'", workflow)

    def test_easy_pc_daily_uploads_debug_outputs_even_after_failure(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        upload_index = workflow.index("- name: Upload generated outputs")
        upload_block = workflow[upload_index : upload_index + 260]

        self.assertIn("if: ${{ always() }}", upload_block)
        self.assertIn("data/generated/easy_pc_fix_guide/", upload_block)
        self.assertIn("reports/", upload_block)

    def test_easy_pc_validate_runs_preflight(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-validate-smoke.yml").read_text(encoding="utf-8")

        self.assertIn("- name: Run automation preflight", workflow)
        self.assertIn("python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide", workflow)
        self.assertIn("reports/easy_pc_fix_guide-preflight.json", workflow)

    def test_easy_pc_validate_runs_when_any_easy_pc_workflow_changes(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-validate-smoke.yml").read_text(encoding="utf-8")

        for workflow_path in [
            ".github/workflows/easy-pc-daily.yml",
            ".github/workflows/easy-pc-publication-check.yml",
            ".github/workflows/easy-pc-weekly-report.yml",
            ".github/workflows/easy-pc-cadence-alert.yml",
            ".github/workflows/easy-pc-validate-smoke.yml",
        ]:
            self.assertIn(f'"{workflow_path}"', workflow)

    def test_easy_pc_publication_check_uploads_report(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-publication-check.yml").read_text(encoding="utf-8")

        self.assertIn("python -m src.pipeline.stage4_publication_check --site easy_pc_fix_guide --after-hour 9", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("reports/easy_pc_fix_guide-publication-check.json", workflow)

    def test_easy_pc_weekly_report_has_search_console_analytics_and_artifact(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-weekly-report.yml").read_text(encoding="utf-8")

        self.assertIn("GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON", workflow)
        self.assertIn("GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON", workflow)
        self.assertIn("python -m src.pipeline.stage3_weekly_report --site easy_pc_fix_guide", workflow)
        upload_index = workflow.index("- name: Upload weekly report")
        upload_block = workflow[upload_index : upload_index + 260]
        self.assertIn("if: ${{ always() }}", upload_block)
        self.assertIn("reports/easy_pc_fix_guide-weekly-*", workflow)
        self.assertIn("reports/easy_pc_fix_guide-weekly-failure.json", workflow)


if __name__ == "__main__":
    unittest.main()
