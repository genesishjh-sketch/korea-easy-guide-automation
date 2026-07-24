from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import requests

from src.pipeline.publication_gate import new_publication_created
from src.pipeline.publication_gate import verify_new_publication
from src.pipeline.publication_gate import write_github_publication_output


class PublicationGateTests(unittest.TestCase):
    def live_response(
        self,
        url: str = "https://example.com/new.html",
        *,
        status_code: int = 200,
        canonical: str | None = None,
        robots: str = "",
        history: list | None = None,
    ) -> Mock:
        canonical_url = canonical if canonical is not None else url
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.history = history or []
        response.headers = {"Content-Type": "text/html; charset=UTF-8"}
        response.text = (
            "<html><head>"
            f'<link rel="canonical" href="{canonical_url}">'
            f'<meta name="robots" content="{robots}">'
            "</head><body>Published article</body></html>"
        )
        return response

    def test_batch_requires_live_status_and_a_verified_public_url(self) -> None:
        published = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                    "draft": False,
                    "skipped": False,
                }
            ]
        }
        with patch(
            "src.pipeline.publication_gate.requests.get",
            return_value=self.live_response(),
        ):
            self.assertTrue(new_publication_created(published))

    def test_batch_url_without_live_status_is_not_enough(self) -> None:
        with patch("src.pipeline.publication_gate.requests.get") as get:
            self.assertFalse(
                new_publication_created(
                    {"published": [{"url": "https://example.com/new.html"}]}
                )
            )
        get.assert_not_called()

    def test_empty_batch_is_not_a_new_publication(self) -> None:
        self.assertFalse(new_publication_created({"published": []}))

    def test_daily_limit_skip_is_not_a_new_publication(self) -> None:
        self.assertFalse(
            new_publication_created(
                {"mode": "publish", "daily_limit_skipped": True, "publish_result": "missing.json"}
            )
        )

    def test_missing_publish_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = {
                "mode": "publish",
                "publish_result": str(Path(tmpdir) / "missing-publish-result.json"),
            }
            output = Path(tmpdir) / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "publish_result_missing",
                ):
                    write_github_publication_output(result)

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "new_publication=false\n"
                "publication_verification=verification_failed\n",
            )

    def test_unreadable_publish_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = Path(tmpdir) / "result.json"
            result_path.write_text("{not-json", encoding="utf-8")
            verification = verify_new_publication(
                {
                    "mode": "publish",
                    "publish_result": str(result_path),
                }
            )

        self.assertFalse(verification["verified"])
        self.assertEqual(
            verification["candidates"][0]["reason"],
            "publish_result_unreadable",
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
            with patch(
                "src.pipeline.publication_gate.requests.get",
                return_value=self.live_response(),
            ):
                self.assertTrue(
                    new_publication_created(
                        {"mode": "publish", "publish_result": str(result_path)}
                    )
                )

    def test_http_error_is_not_a_verified_publication(self) -> None:
        result = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                }
            ]
        }
        with patch(
            "src.pipeline.publication_gate.requests.get",
            return_value=self.live_response(status_code=404),
        ), patch("src.pipeline.publication_gate.time.sleep"):
            verification = verify_new_publication(result)

        self.assertFalse(verification["verified"])
        self.assertEqual(verification["candidates"][0]["reason"], "http_404")

    def test_transient_live_fetch_failure_is_retried(self) -> None:
        result = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                }
            ]
        }
        with patch(
            "src.pipeline.publication_gate.requests.get",
            side_effect=[
                requests.RequestException("not propagated yet"),
                self.live_response(),
            ],
        ) as get, patch("src.pipeline.publication_gate.time.sleep") as sleep:
            verification = verify_new_publication(result)

        self.assertTrue(verification["verified"])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()

    def test_redirected_or_noncanonical_url_is_not_verified(self) -> None:
        result = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                }
            ]
        }
        redirected = self.live_response(
            url="https://example.com/other.html",
            history=[Mock(status_code=301)],
        )
        with patch(
            "src.pipeline.publication_gate.requests.get",
            return_value=redirected,
        ):
            self.assertFalse(new_publication_created(result))

        mismatch = self.live_response(canonical="https://example.com/other.html")
        with patch(
            "src.pipeline.publication_gate.requests.get",
            return_value=mismatch,
        ):
            verification = verify_new_publication(result)
        self.assertEqual(
            verification["candidates"][0]["reason"],
            "canonical_mismatch",
        )

    def test_noindex_url_is_not_verified(self) -> None:
        result = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                }
            ]
        }
        with patch(
            "src.pipeline.publication_gate.requests.get",
            return_value=self.live_response(robots="noindex,follow"),
        ):
            verification = verify_new_publication(result)

        self.assertFalse(verification["verified"])
        self.assertEqual(verification["candidates"][0]["reason"], "noindex")

    def test_github_output_is_written_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                result = {"published": []}
                write_github_publication_output(result)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "new_publication=false\n"
                "publication_verification=no_new_publication\n",
            )
            self.assertEqual(
                result["publication_verification"]["status"],
                "no_new_publication",
            )

    def test_failed_live_verification_writes_output_and_fails_pipeline(self) -> None:
        result = {
            "published": [
                {
                    "url": "https://example.com/new.html",
                    "blogger_status": "LIVE",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "github-output"
            with patch.dict(
                os.environ,
                {"GITHUB_OUTPUT": str(output)},
            ), patch(
                "src.pipeline.publication_gate.requests.get",
                return_value=self.live_response(status_code=404),
            ), patch(
                "src.pipeline.publication_gate.time.sleep",
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "failed live indexability verification",
                ):
                    write_github_publication_output(result)

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "new_publication=false\n"
                "publication_verification=verification_failed\n",
            )
