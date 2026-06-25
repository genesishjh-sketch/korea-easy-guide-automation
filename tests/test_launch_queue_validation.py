from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline import stage0_launch_queue_validate


class LaunchQueueValidationTests(unittest.TestCase):
    def test_static_validation_accepts_current_launch_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            stage0_launch_queue_validate, "ROOT_DIR", Path(tmpdir)
        ), patch.object(stage0_launch_queue_validate, "used_keywords", return_value=set()):
            path = stage0_launch_queue_validate.run("easy_pc_fix_guide")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["mode"], "static")
        self.assertEqual(payload["seed_count"], 14)
        self.assertEqual(payload["passed_seed_count"], 14)
        self.assertTrue(all(item["status"] == "pass" for item in payload["items"]))

    def test_static_validation_rejects_used_or_generic_seed(self) -> None:
        main_seeds = {"windows problem", "wifi button missing windows 11"}
        used = {"wifi button missing windows 11"}

        generic = stage0_launch_queue_validate.validate_seed("windows problem", main_seeds, used)
        used_seed = stage0_launch_queue_validate.validate_seed("wifi button missing windows 11", main_seeds, used)

        self.assertIn("generic_computer_help_category", generic.issues)
        self.assertIn("weak_microsoft_sources", generic.issues)
        self.assertIn("already_used", used_seed.issues)

    def test_global_validation_rejects_short_duplicate_or_missing_queue(self) -> None:
        issues = stage0_launch_queue_validate.global_launch_queue_issues(
            ["topic one", "topic one"],
            {"topic one"},
        )

        joined = " ".join(issues)
        self.assertIn("launch_queue_too_short", joined)
        self.assertIn("duplicate_launch_topics", joined)
        self.assertNotIn("launch_topics_missing_from_main_seed_file", joined)

    def test_generate_mode_records_article_dir_and_score(self) -> None:
        launch_seeds = [
            "wifi keeps disconnecting windows 11",
            "dns server not responding windows 11",
            "network adapter missing windows 11",
            "windows cannot connect to this network",
            "no internet secured windows 11",
            "ethernet connected but no internet windows 11",
            "microsoft store download stuck",
        ]
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(stage0_launch_queue_validate, "ROOT_DIR", Path(tmpdir)), patch.object(
            stage0_launch_queue_validate, "load_launch_seed_list", return_value=launch_seeds
        ), patch.object(
            stage0_launch_queue_validate, "load_seed_list", return_value=launch_seeds
        ), patch.object(
            stage0_launch_queue_validate, "used_keywords", return_value=set()
        ), patch.object(
            stage0_launch_queue_validate, "run_stage1"
        ) as stage1, patch.object(
            stage0_launch_queue_validate, "run_validation"
        ) as validate:
            article_dir = Path(tmpdir) / "article"
            article_dir.mkdir()
            result_path = article_dir / "validation_result.json"
            result_path.write_text(json.dumps({"passed": True, "score": 100}), encoding="utf-8")
            stage1.return_value = article_dir
            validate.return_value = result_path

            path = stage0_launch_queue_validate.run("easy_pc_fix_guide", generate=True, limit=1)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["mode"], "generate")
        self.assertEqual(payload["items"][0]["article_dir"], str(article_dir))
        self.assertEqual(payload["items"][0]["quality_score"], 100)


if __name__ == "__main__":
    unittest.main()
