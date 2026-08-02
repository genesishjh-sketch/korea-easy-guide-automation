from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.pipeline.stage2_publish import existing_topic_publication
from src.pipeline.stage2_publish import enqueue_local_publication_sync
from src.pipeline.stage2_publish import record_topic_publication
from src.pipeline.stage2_publish import run
from src.pipeline.stage2_publish import save_publish_result
from src.pipeline.stage2_publish import validate_required_images
from src.pipeline.stage2_publish import rewrite_local_image_paths
from src.pipeline.stage2_publish import validate_fresh_public_images
from src.pipeline.stage2_publish import validate_library_image_is_publishable
from src.pipeline.stage2_publish import validate_public_image_urls_reachable
from src.quality.hades import HadesQualityGate


class Stage2ImageGateTests(unittest.TestCase):
    def test_local_outbox_is_not_durable_when_fsync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {
                "TOPIC_PUBLICATION_OUTBOX": str(
                    Path(tmpdir) / "pending.jsonl"
                )
            },
        ), patch(
            "src.pipeline.stage2_publish.os.fsync",
            side_effect=OSError("fsync failed"),
        ):
            result = enqueue_local_publication_sync(
                "easy_pc_fix_guide",
                "topic-fsync",
                {
                    "blogger_post_id": "post-fsync",
                    "url": "https://example.com/fsync.html",
                },
                error="registry unavailable",
            )

        self.assertFalse(result["durable"])
        self.assertEqual(result["status"], "error")
        self.assertIn("fsync failed", result["error"])

    def test_publish_result_includes_topic_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-1",
                            "cluster_id": "cluster-1",
                            "category_id": "cat-1",
                            "action": "NEW_POST",
                            "revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            path = save_publish_result(
                article_dir,
                {
                    "id": "post-1",
                    "url": "https://example.com/post-1.html",
                    "status": "LIVE",
                },
                False,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["topic_id"], "topic-1")
        self.assertEqual(payload["revision"], 4)
        self.assertEqual(payload["blogger"]["id"], "post-1")
        self.assertEqual(payload["blogger"]["url"], "https://example.com/post-1.html")

    def test_same_topic_id_is_not_republished_with_a_different_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generated_root = Path(tmpdir) / "generated"
            existing_dir = generated_root / "2026-07-01" / "existing"
            current_dir = generated_root / "2026-07-02" / "current"
            existing_dir.mkdir(parents=True)
            current_dir.mkdir(parents=True)
            (existing_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {"title": "Old public title"},
                        "candidate": {"topic_id": "topic-same"},
                    }
                ),
                encoding="utf-8",
            )
            (existing_dir / "blogger_publish_result.json").write_text(
                json.dumps(
                    {
                        "draft": False,
                        "blogger": {
                            "id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (current_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "article": {"title": "Completely different title"},
                        "candidate": {
                            "topic_id": "topic-same",
                            "action": "NEW_POST",
                            "revision": 2,
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = SimpleNamespace(
                site_key="easy_pc_fix_guide",
                generated_output_dir=str(generated_root),
                blogger_publish_mode="publish",
            )
            with patch("src.pipeline.stage2_publish.load_settings", return_value=settings):
                publication = existing_topic_publication(current_dir, "easy_pc_fix_guide")
                result_path = run(current_dir, "publish", "easy_pc_fix_guide")

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(publication["blogger_post_id"], "post-existing")
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "duplicate_topic_id")
        self.assertEqual(payload["topic_id"], "topic-same")
        self.assertEqual(payload["blogger"]["id"], "post-existing")

    def test_registry_failure_after_blogger_success_uses_durable_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox = Path(tmpdir) / "publication_sync_pending.jsonl"
            with patch.dict(
                "os.environ",
                {"TOPIC_PUBLICATION_OUTBOX": str(outbox)},
            ), patch(
                "src.topics.store.TopicStore",
                side_effect=RuntimeError("registry unavailable"),
            ):
                first = record_topic_publication(
                    "easy_pc_fix_guide",
                    {
                        "topic_id": "topic-outbox",
                        "revision": 8,
                        "claim_run_id": "batch-run",
                    },
                    "Already live on Blogger",
                    {
                        "id": "post-live",
                        "url": "https://example.com/live.html",
                        "status": "LIVE",
                    },
                    draft=False,
                )
                second = record_topic_publication(
                    "easy_pc_fix_guide",
                    {
                        "topic_id": "topic-outbox",
                        "revision": 8,
                        "claim_run_id": "batch-run",
                    },
                    "Already live on Blogger",
                    {
                        "id": "post-live",
                        "url": "https://example.com/live.html",
                        "status": "LIVE",
                    },
                    draft=False,
                )
            entries = [
                json.loads(line)
                for line in outbox.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(first["status"], "local_outbox")
        self.assertEqual(second["status"], "local_outbox")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["topic_id"], "topic-outbox")
        self.assertEqual(
            entries[0]["publication"]["blogger_post_id"],
            "post-live",
        )

    def test_required_images_need_image_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError) as raised:
                validate_required_images(Path(tmpdir))

        self.assertIn("image_plan.json is required", str(raised.exception))

    def test_required_images_need_strict_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps({"strict": False, "images": []}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                validate_required_images(article_dir)

        self.assertIn("strict=true", str(raised.exception))

    def test_required_images_need_two_required_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [{"url": "assets/ai-hero.jpg", "required": True}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                validate_required_images(article_dir)

        self.assertIn("At least two required image assets", str(raised.exception))

    def test_required_images_must_exist_as_local_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"url": "assets/ai-hero.jpg", "required": True},
                            {"url": "assets/ai-inline-1.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError) as raised:
                validate_required_images(article_dir)

        self.assertIn("ai-hero.jpg", str(raised.exception))
        self.assertIn("ai-inline-1.jpg", str(raised.exception))

    def test_required_images_accept_two_local_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"url": "assets/ai-hero.jpg", "required": True},
                            {"url": "assets/ai-inline-1.jpg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            validate_required_images(article_dir)

    def test_required_images_reject_svg_fallback_assets_for_public_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.svg").write_text("<svg></svg>", encoding="utf-8")
            (assets_dir / "ai-inline-1.svg").write_text("<svg></svg>", encoding="utf-8")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {"url": "assets/ai-hero.svg", "required": True},
                            {"url": "assets/ai-inline-1.svg", "required": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                validate_required_images(article_dir)

        self.assertIn("not SVG fallback assets", str(raised.exception))

    def test_rewrite_local_image_paths_uses_raw_github_url_not_base64(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library_dir = root / "src" / "images" / "ai_assets" / "hosted"
            library_dir.mkdir(parents=True)
            article_dir = root / "data" / "generated" / "article"
            assets_dir = article_dir / "assets"
            assets_dir.mkdir(parents=True)
            image_bytes = b"fake-jpeg"
            (library_dir / "hero.jpg").write_bytes(image_bytes)
            (assets_dir / "ai-hero.jpg").write_bytes(image_bytes)
            html = '<article><img src="assets/ai-hero.jpg" alt="Hero"></article>'

            with patch("src.pipeline.stage2_publish.ROOT_DIR", root), patch(
                "src.pipeline.stage2_publish.RAW_IMAGE_BASE_URL",
                "https://raw.githubusercontent.com/example/repo/main",
            ):
                rewritten = rewrite_local_image_paths(html, article_dir)

        self.assertIn("https://raw.githubusercontent.com/example/repo/main/src/images/ai_assets/hosted/hero.jpg", rewritten)
        self.assertNotIn("base64", rewritten)
        self.assertNotIn("data:image", rewritten)

    def test_reusable_image_library_paths_are_blocked_for_public_publish(self) -> None:
        with self.assertRaises(ValueError) as raised:
            validate_library_image_is_publishable("src/images/ai_assets/korea/general/hero.jpg")

        self.assertIn("Reusable image library assets cannot be used", str(raised.exception))

    def test_fresh_public_images_block_reused_published_urls(self) -> None:
        html = '<article><img src="https://raw.example/hosted/fresh.jpg" alt="Fresh image"></article>'
        with patch("src.pipeline.stage2_publish.public_image_urls", return_value={"https://raw.example/hosted/fresh.jpg"}):
            with self.assertRaises(ValueError) as raised:
                validate_fresh_public_images(html, "korea_easy_guide")

        self.assertIn("already used by published posts", str(raised.exception))

    def test_fresh_public_images_block_base64_data_images(self) -> None:
        html = '<article><img src="data:image/jpeg;base64,AAAA" alt="Embedded image"></article>'

        with self.assertRaises(ValueError) as raised:
            validate_fresh_public_images(html, "korea_easy_guide")

        self.assertIn("must not embed base64", str(raised.exception))

    def test_public_image_urls_must_be_reachable_before_publish(self) -> None:
        html = '<article><img src="https://raw.example/missing.jpg" alt="Missing"></article>'

        with patch("src.pipeline.stage2_publish.public_image_url_status", return_value=(404, "text/plain")):
            with self.assertRaises(ValueError) as raised:
                validate_public_image_urls_reachable(html)

        self.assertIn("reachable image URLs", str(raised.exception))
        self.assertIn("missing.jpg", str(raised.exception))

    def test_public_image_urls_accept_reachable_images(self) -> None:
        html = '<article><img src="https://raw.example/fresh.jpg" alt="Fresh"></article>'

        with patch("src.pipeline.stage2_publish.public_image_url_status", return_value=(200, "image/jpeg")):
            validate_public_image_urls_reachable(html)

    def test_hades_blocks_articles_without_image_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            html = """
            <article>
              <h2>Quick Answer</h2>
              <img src="assets/ai-hero.jpg" alt="Hero">
              <img src="assets/ai-inline-1.jpg" alt="Inline">
            </article>
            """

            report = HadesQualityGate().review_html(html, article_dir, {"article": {}})

        self.assertIn("missing_image_plan", {issue.code for issue in report.issues})

    def test_hades_blocks_weak_image_alt_and_caption_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Hero",
                                "caption": "Hero image.",
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Inline",
                                "caption": "Inline image.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Answer</h2>
              <img src="assets/ai-hero.jpg" alt="Hero">
              <img src="assets/ai-inline-1.jpg" alt="Inline">
            </article>
            """

            report = HadesQualityGate().review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("weak_image_alt_text", issue_codes)
        self.assertIn("weak_image_caption", issue_codes)

    def test_hades_blocks_windows_image_plans_that_allow_fake_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Screenshot of Windows settings screen for update repair",
                                "caption": "A Windows UI screenshot showing the exact repair screen.",
                                "prompt": "Create a realistic fake Windows UI screenshot with readable error text.",
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Windows troubleshooting flow with safe abstract repair symbols",
                                "caption": "Use the safe visual checklist before trying advanced repair steps.",
                                "prompt": "Create a simple computer help image.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Summary</h2>
              <img src="assets/ai-hero.jpg" alt="Screenshot of Windows settings screen for update repair">
              <img src="assets/ai-inline-1.jpg" alt="Windows troubleshooting flow with safe abstract repair symbols">
            </article>
            """

            report = HadesQualityGate("windows_help").review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("unsafe_windows_image_label", issue_codes)
        self.assertIn("unsafe_windows_image_prompt", issue_codes)

    def test_hades_accepts_windows_image_prompts_with_strict_fake_ui_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            guarded_prompt = (
                "Create a realistic 16:9 beginner Windows help visual. Do not show fake Windows UI, "
                "readable error codes, readable letters or numbers, command prompts, registry editors, logos, or text overlays."
            )
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Beginner friendly Windows update repair checklist visual",
                                "caption": "A calm abstract checklist visual for safe Windows troubleshooting steps.",
                                "prompt": guarded_prompt,
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Safe Windows troubleshooting flow with abstract repair symbols",
                                "caption": "Follow the simple checks first before using advanced repair steps.",
                                "prompt": guarded_prompt,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Summary</h2>
              <img src="assets/ai-hero.jpg" alt="Beginner friendly Windows update repair checklist visual">
              <img src="assets/ai-inline-1.jpg" alt="Safe Windows troubleshooting flow with abstract repair symbols">
            </article>
            """

            report = HadesQualityGate("windows_help").review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertNotIn("unsafe_windows_image_label", issue_codes)
        self.assertNotIn("unsafe_windows_image_prompt", issue_codes)

    def test_hades_blocks_template_style_image_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            assets_dir = article_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "ai-hero.jpg").write_bytes(b"hero")
            (assets_dir / "ai-inline-1.jpg").write_bytes(b"inline")
            template_prompt = (
                "Create a beginner Windows help image of a laptop on a desk. "
                "Do not show fake Windows UI, readable error codes, readable letters or numbers, "
                "command prompts, registry editors, logos, or text overlays."
            )
            (article_dir / "image_plan.json").write_text(
                json.dumps(
                    {
                        "strict": True,
                        "images": [
                            {
                                "url": "assets/ai-hero.jpg",
                                "filename": "ai-hero.jpg",
                                "required": True,
                                "alt": "Beginner friendly Windows scanner troubleshooting visual",
                                "caption": "A calm visual for checking scanner troubleshooting safely.",
                                "prompt": template_prompt,
                            },
                            {
                                "url": "assets/ai-inline-1.jpg",
                                "filename": "ai-inline-1.jpg",
                                "required": True,
                                "alt": "Safe Windows scanner troubleshooting checklist visual",
                                "caption": "Use the safe checklist before advanced Windows repair steps.",
                                "prompt": template_prompt,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            html = """
            <article>
              <h2>Quick Summary</h2>
              <img src="assets/ai-hero.jpg" alt="Beginner friendly Windows scanner troubleshooting visual">
              <img src="assets/ai-inline-1.jpg" alt="Safe Windows scanner troubleshooting checklist visual">
            </article>
            """

            report = HadesQualityGate("windows_help").review_html(html, article_dir, {"article": {}})

        issue_codes = {issue.code for issue in report.issues}
        self.assertIn("missing_fresh_image_prompt_strategy", issue_codes)
        self.assertIn("missing_image_role_strategy", issue_codes)
        self.assertIn("missing_image_repeat_avoidance", issue_codes)
        self.assertIn("generic_pc_desk_image_prompt", issue_codes)
        self.assertIn("similar_image_prompts", issue_codes)

    def test_hades_blocks_dangerous_windows_tool_recommendations(self) -> None:
        gate = HadesQualityGate("windows_help")
        text = (
            "Applies to Windows 11. Risk level Medium. Data loss risk Possible. "
            "Estimated time 20 minutes. Last checked 2026-06-26. Advanced fixes. "
            "Back up important files before advanced fixes. Download Driver Booster and use an activation bypass."
        ).casefold()

        issues = gate._review_windows_article(None, text, links=[])

        issue_codes = {issue.code for issue in issues}
        self.assertIn("dangerous_windows_recommendation", issue_codes)
        messages = " ".join(issue.message for issue in issues)
        self.assertIn("download driver booster", messages)
        self.assertIn("use an activation bypass", messages)

    def test_hades_allows_warnings_against_random_driver_tools(self) -> None:
        gate = HadesQualityGate("windows_help")
        text = (
            "Applies to Windows 11. Risk level Low. Data loss risk No. "
            "Estimated time 10 minutes. Last checked 2026-06-26. Advanced fixes. "
            "Back up important files before advanced fixes. Avoid random driver tools and do not use driver updater apps."
        ).casefold()

        issues = gate._review_windows_article(None, text, links=[])

        self.assertNotIn("dangerous_windows_recommendation", {issue.code for issue in issues})

    def test_hades_allows_faq_question_about_driver_updater_safety(self) -> None:
        gate = HadesQualityGate("windows_help")
        text = (
            "Applies to Windows 11. Risk level Low. Data loss risk No. "
            "Estimated time 10 minutes. Last checked 2026-06-26. Advanced fixes. "
            "Back up important files before advanced fixes.\n"
            "### Is it safe to use driver updater tools?\n"
            "Avoid random driver tools. Use Windows Update or the device maker's official website."
        ).casefold()

        issues = gate._review_windows_article(None, text, links=[])

        self.assertNotIn("dangerous_windows_recommendation", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
