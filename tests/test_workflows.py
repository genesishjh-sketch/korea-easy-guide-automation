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

    def test_legacy_korea_daily_is_manual_only_while_easy_pc_is_scheduled(self) -> None:
        korea_workflow = (ROOT_DIR / ".github" / "workflows" / "daily-draft.yml").read_text(encoding="utf-8")
        easy_pc_workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_dispatch:", korea_workflow)
        self.assertNotIn("schedule:", korea_workflow)
        self.assertIn('cron: "10 0 * * *"', easy_pc_workflow)
        self.assertIn('cron: "25 0 * * *"', easy_pc_workflow)

    def test_legacy_korea_cadence_alert_is_manual_only_while_easy_pc_is_scheduled(self) -> None:
        korea_workflow = (ROOT_DIR / ".github" / "workflows" / "cadence-alert.yml").read_text(encoding="utf-8")
        easy_pc_workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-cadence-alert.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_dispatch:", korea_workflow)
        self.assertNotIn("schedule:", korea_workflow)
        self.assertIn('cron: "30 0 22 7 *"', easy_pc_workflow)
        self.assertIn('cron: "30 0 19 8 *"', easy_pc_workflow)

    def test_easy_pc_daily_runs_safety_tests_before_publish(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        install_index = workflow.index("- name: Install dependencies")
        test_index = workflow.index("- name: Run safety regression tests")
        preflight_index = workflow.index("- name: Run automation preflight")
        seed_plan_index = workflow.index("- name: Write daily seed plan")
        oauth_index = workflow.index("- name: Write Google OAuth files")
        publish_index = workflow.index("- name: Run Easy PC Fix daily pipeline")

        self.assertLess(install_index, test_index)
        self.assertLess(test_index, preflight_index)
        self.assertLess(preflight_index, seed_plan_index)
        self.assertLess(seed_plan_index, oauth_index)
        self.assertLess(oauth_index, publish_index)
        self.assertIn("python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide", workflow)
        self.assertIn("python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode plan", workflow)
        self.assertIn("--no-notify", workflow)
        self.assertIn("EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT", workflow)
        self.assertIn("easy-pc-fix-guide/0.1 by posting-automation-alert-bot", workflow)

    def test_easy_pc_daily_submits_sitemap_only_for_publish_mode(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        self.assertIn("- name: Submit sitemap", workflow)
        self.assertIn("success() && env.BLOGGER_PUBLISH_MODE == 'publish'", workflow)
        self.assertNotIn("always() && env.BLOGGER_PUBLISH_MODE == 'publish'", workflow)

    def test_easy_pc_daily_has_backup_schedule_after_primary_publish(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-daily.yml").read_text(encoding="utf-8")

        self.assertIn('cron: "10 0 * * *"', workflow)
        self.assertIn('cron: "25 0 * * *"', workflow)
        self.assertIn("daily limit guard prevents duplicate publishing", workflow)
        self.assertIn("group: easy-pc-fix-daily-publish", workflow)
        self.assertIn("cancel-in-progress: false", workflow)

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
        self.assertIn("REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}", workflow)
        self.assertIn("REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}", workflow)
        self.assertIn("EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT", workflow)
        self.assertIn("easy-pc-fix-guide/0.1 by posting-automation-alert-bot", workflow)

    def test_easy_pc_validate_runs_when_any_easy_pc_workflow_changes(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-validate-smoke.yml").read_text(encoding="utf-8")

        for workflow_path in [
            ".github/workflows/easy-pc-daily.yml",
            ".github/workflows/easy-pc-publication-check.yml",
            ".github/workflows/easy-pc-weekly-report.yml",
            ".github/workflows/easy-pc-cadence-alert.yml",
            ".github/workflows/easy-pc-reddit-health.yml",
            ".github/workflows/easy-pc-validate-smoke.yml",
        ]:
            self.assertIn(f'"{workflow_path}"', workflow)

    def test_easy_pc_publication_check_uploads_report(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-publication-check.yml").read_text(encoding="utf-8")

        self.assertIn("python -m src.pipeline.stage4_publication_check --site easy_pc_fix_guide --after-hour 9", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("reports/easy_pc_fix_guide-publication-check.json", workflow)
        self.assertIn("reports/easy_pc_fix_guide-publication-check.md", workflow)

    def test_easy_pc_weekly_report_has_search_console_analytics_and_artifact(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-weekly-report.yml").read_text(encoding="utf-8")

        self.assertIn("GOOGLE_OAUTH_TOKEN_SEARCH_CONSOLE_JSON", workflow)
        self.assertIn("GOOGLE_OAUTH_TOKEN_ANALYTICS_JSON", workflow)
        self.assertIn("REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}", workflow)
        self.assertIn("REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}", workflow)
        self.assertIn("EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT", workflow)
        self.assertIn("- name: Run Reddit OAuth health check for weekly context", workflow)
        self.assertIn("python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide", workflow)
        self.assertIn("python -m src.pipeline.stage3_weekly_report --site easy_pc_fix_guide", workflow)
        health_index = workflow.index("- name: Run Reddit OAuth health check for weekly context")
        report_index = workflow.index("- name: Generate and send weekly report")
        self.assertLess(health_index, report_index)
        upload_index = workflow.index("- name: Upload weekly report")
        upload_block = workflow[upload_index : upload_index + 260]
        self.assertIn("if: ${{ always() }}", upload_block)
        self.assertIn("reports/easy_pc_fix_guide-reddit-health.json", workflow)
        self.assertIn("reports/easy_pc_fix_guide-reddit-health.md", workflow)
        self.assertIn("reports/easy_pc_fix_guide-weekly-*", workflow)
        self.assertIn("reports/easy_pc_fix_guide-weekly-failure.json", workflow)

    def test_easy_pc_reddit_health_uses_oauth_secrets_and_artifact(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "easy-pc-reddit-health.yml").read_text(encoding="utf-8")

        self.assertIn("20 0 * * *", workflow)
        self.assertIn("REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}", workflow)
        self.assertIn("REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}", workflow)
        self.assertIn("EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT", workflow)
        self.assertIn("python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide", workflow)
        self.assertIn('EVENT_NAME="${{ github.event_name }}"', workflow)
        self.assertIn('"workflow_dispatch"', workflow)
        self.assertIn("--notify", workflow)
        self.assertIn("actions/upload-artifact@v6", workflow)
        self.assertIn("reports/easy_pc_fix_guide-reddit-health.json", workflow)
        self.assertIn("reports/easy_pc_fix_guide-reddit-health.md", workflow)


if __name__ == "__main__":
    unittest.main()
