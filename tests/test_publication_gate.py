from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline.publication_gate import new_publication_created
from src.pipeline.publication_gate import write_github_publication_output


class PublicationGateTests(unittest.TestCase):
    def test_batch_requires_a_new_published_item(self) -> None:
        self.assertTrue(new_publication_created({"published": [{"url": "https://example.com/new.html"}]}))
        self.assertFalse(new_publication_created({"published": []}))

    def test_daily_limit_skip_is_not_a_new_publication(self) -> None:
        self.assertFalse(
            new_publication_created(
                {"mode": "publish", "daily_limit_skipped": True, "publish_result": "missing.json"}
            )
        )

    def test_live_blogger_result_is_a_new_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = Path(tmpdir) / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "draft": False,
                        "skipped": False,
                        "blogger": {"status": "LIVE", "url": "https://example.com/new.html"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                new_publication_created({"mode": "publish", "publish_result": str(result_path)})
            )

    def test_github_output_is_written_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                write_github_publication_output({"published": []})
            self.assertEqual(output.read_text(encoding="utf-8"), "new_publication=false\n")
