from __future__ import annotations

from datetime import date
from datetime import datetime
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from src.pipeline import daily_batch
from src.pipeline import weekly_queue


class WeeklyQueueTests(unittest.TestCase):
    def test_default_start_date_uses_current_monday_after_delayed_sunday_run(self) -> None:
        kst = ZoneInfo("Asia/Seoul")

        self.assertEqual(
            weekly_queue.default_start_date(datetime(2026, 7, 5, 22, 0, tzinfo=kst)),
            date(2026, 7, 6),
        )
        self.assertEqual(
            weekly_queue.default_start_date(datetime(2026, 7, 6, 0, 25, tzinfo=kst)),
            date(2026, 7, 6),
        )
        self.assertEqual(
            weekly_queue.default_start_date(datetime(2026, 7, 7, 9, 0, tzinfo=kst)),
            date(2026, 7, 13),
        )

    def test_rollout_keeps_first_two_runs_shadow_then_enables_registry(self) -> None:
        class FakeStore:
            def __init__(self, qualifying_runs: int):
                self.qualifying_runs = qualifying_runs

            def get_rollout_state(self, site):
                return {
                    "mode": "REGISTRY" if self.qualifying_runs >= 2 else "SHADOW",
                    "qualifying_runs": self.qualifying_runs,
                    "required_qualifying_runs": 2,
                }

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                weekly_queue.topic_board_mode("korea_easy_guide", FakeStore(0)),
                "shadow",
            )
            self.assertEqual(
                weekly_queue.topic_board_mode("korea_easy_guide", FakeStore(1)),
                "shadow",
            )
            self.assertEqual(
                weekly_queue.topic_board_mode("korea_easy_guide", FakeStore(2)),
                "ready_first",
            )

    def test_environment_cannot_force_unpromoted_or_degraded_registry_mode(self) -> None:
        class FakeStore:
            def __init__(self, state):
                self.state = state

            def get_rollout_state(self, site):
                return self.state

        with patch.dict(
            "os.environ",
            {"TOPIC_BOARD_MODE": "registry_only"},
            clear=True,
        ):
            self.assertEqual(
                weekly_queue.topic_board_mode(
                    "korea_easy_guide",
                    FakeStore({"mode": "SHADOW", "promoted": False}),
                ),
                "shadow",
            )
            self.assertEqual(
                weekly_queue.topic_board_mode(
                    "korea_easy_guide",
                    FakeStore({"mode": "DEGRADED", "promoted": True}),
                ),
                "shadow",
            )

        with patch.dict(
            "os.environ",
            {"TOPIC_BOARD_MODE": "legacy"},
            clear=True,
        ):
            self.assertEqual(
                weekly_queue.topic_board_mode(
                    "korea_easy_guide",
                    FakeStore({"mode": "READY_FIRST", "promoted": True}),
                ),
                "legacy",
            )

    def test_degraded_default_keeps_ready_backlog_but_holds_maintenance(self) -> None:
        class FakeStore:
            def __init__(self):
                self.list_calls = 0

            def get_rollout_state(self, site):
                return {
                    "mode": "DEGRADED",
                    "promoted": True,
                    "degraded_policy": "backlog",
                }

            def list_maintenance_topics(self, *args, **kwargs):
                self.list_calls += 1
                return [SimpleNamespace(topic_id="must-not-be-read")]

        store = FakeStore()
        with patch.dict("os.environ", {}, clear=True), tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue,
            "QUEUE_DIR",
            Path(temp_dir),
        ):
            self.assertEqual(
                weekly_queue.topic_board_mode(
                    "easy_pc_fix_guide",
                    store,
                ),
                "ready_first",
            )
            enabled, reason = weekly_queue.maintenance_rollout_gate(
                store,
                "easy_pc_fix_guide",
                selection_mode="ready_first",
            )
            queue = weekly_queue.generate_maintenance_queue(
                "easy_pc_fix_guide",
                date(2026, 7, 6),
                store=store,
                enabled=enabled,
                hold_reason=reason,
            )

        self.assertFalse(enabled)
        self.assertEqual(reason, "rollout_degraded_reconciliation_hold")
        self.assertEqual(queue["status"], "HOLD")
        self.assertEqual(queue["items"], [])
        self.assertEqual(store.list_calls, 0)

    def test_topic_lifecycle_reaches_published_only_after_live_verification(self) -> None:
        from src.topics.models import CategoryRecord
        from src.topics.models import PublicationRef
        from src.topics.models import TopicStatus
        from src.topics.store import TopicStore

        site = "easy_pc_fix_guide"
        run_id = "batch-2026-07-06"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TopicStore(Path(temp_dir) / "topics")
            store.upsert_category(
                site,
                CategoryRecord(
                    category_id="cat-apps",
                    site=site,
                    name="Apps & Settings",
                    blogger_label="Apps & Settings",
                ),
            )
            ready = store.create_topic(
                site,
                "windows settings app will not open",
                "cat-apps",
                topic_id="topic-lifecycle",
                status=TopicStatus.READY,
                action="NEW_POST",
            )
            store.record_rollout_run(
                site,
                "completed-backfill",
                "SUCCESS",
                run_at="2026-06-27T10:00:00+09:00",
                details={
                    "run_type": "BACKFILL_RESEARCH",
                    "complete": True,
                    "schema_valid": True,
                    "coverage_hash": "coverage-v1",
                    "logic_version": "test-v1",
                    "unexplored_scope": [],
                },
            )
            store.record_rollout_run(
                site,
                "sunday-1",
                "SUCCESS",
                run_at="2026-06-28T20:00:00+09:00",
                details={
                    "run_type": "WEEKLY_RESEARCH",
                    "complete": True,
                    "schema_valid": True,
                    "ready_evidence_url_coverage": 1.0,
                    "synthetic_influence_count": 0,
                    "blogger_duplicate_count": 0,
                    "auditor_passed": True,
                    "source_count": 1,
                },
            )
            store.record_rollout_run(
                site,
                "sunday-2",
                "SUCCESS",
                run_at="2026-07-05T20:00:00+09:00",
                details={
                    "run_type": "WEEKLY_RESEARCH",
                    "complete": True,
                    "schema_valid": True,
                    "ready_evidence_url_coverage": 1.0,
                    "synthetic_influence_count": 0,
                    "blogger_duplicate_count": 0,
                    "auditor_passed": True,
                    "source_count": 1,
                },
            )

            scheduled = weekly_queue.mark_topic_scheduled(
                store,
                site,
                {
                    "topic_id": ready.topic_id,
                    "date": "2026-07-06",
                    "revision": ready.revision,
                    "schedule_expires_at": "2099-01-01T00:00:00+09:00",
                },
            )
            candidate = {
                **scheduled,
                "category": "Apps & Settings",
                "article_type": "symptom_fix",
            }
            with patch.object(daily_batch, "load_topic_store", return_value=store):
                claimed, candidate, _ = daily_batch.claim_topic_candidate(
                    site,
                    candidate,
                    run_id,
                )
                article_dir = Path(temp_dir) / "article"
                article_dir.mkdir()
                (article_dir / "metadata.json").write_text(
                    weekly_queue.json.dumps(
                        {
                            "candidate": candidate,
                            "article": {"title": "Settings app repair"},
                        }
                    ),
                    encoding="utf-8",
                )
                generated = daily_batch.mark_topic_generated(
                    site,
                    candidate,
                    run_id,
                    article_dir=article_dir,
                )
            live_unverified = store.record_publication(
                site,
                ready.topic_id,
                PublicationRef(
                    blogger_post_id="post-lifecycle",
                    url="https://example.com/settings-app.html",
                    title="Settings app repair",
                    status="LIVE",
                ),
                expected_revision=generated["revision"],
                run_id=run_id,
            )
            published = store.verify_publication(
                site,
                ready.topic_id,
                blogger_post_id="post-lifecycle",
                url="https://example.com/settings-app.html",
                status="LIVE",
            )

        self.assertTrue(claimed)
        self.assertEqual(scheduled["registry_status"], "SCHEDULED")
        self.assertEqual(candidate["registry_status"], "CLAIMED")
        self.assertEqual(generated["registry_status"], "GENERATED")
        self.assertEqual(live_unverified.status, TopicStatus.LIVE_UNVERIFIED)
        self.assertEqual(published.status, TopicStatus.PUBLISHED)

    def test_generate_weekly_queue_skips_existing_public_title_and_schedules_distinct_days(self) -> None:
        seeds = [
            "how to buy ktx tickets in korea",
            "korea tax refund for tourists",
            "wowpass korea for tourists",
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(weekly_queue, "QUEUE_DIR", Path(temp_dir)), patch(
            "src.pipeline.weekly_queue.choose_publish_seed_candidates", return_value=seeds
        ), patch("src.pipeline.weekly_queue.used_keywords", return_value=set()), patch(
            "src.pipeline.weekly_queue.public_post_titles",
            return_value=["How to Buy KTX Tickets in Korea as a Foreigner"],
        ), patch("src.pipeline.weekly_queue.seed_quality_precheck", return_value={"status": "ready"}):
            queue = weekly_queue.generate_weekly_queue(
                site="korea_easy_guide",
                start_date=date(2026, 7, 6),
                days=2,
                posts_per_day=1,
                notify=False,
            )

        seeds_in_queue = [item["seed"] for item in queue["items"]]
        self.assertNotIn("how to buy ktx tickets in korea", seeds_in_queue)
        self.assertEqual(seeds_in_queue, ["korea tax refund for tourists", "wowpass korea for tourists"])
        self.assertEqual([item["date"] for item in queue["items"]], ["2026-07-06", "2026-07-07"])

    def test_today_queue_candidates_loads_matching_week_file(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "research_run_id": "weekly-current",
            "research_run_at": "2026-07-05T20:15:00+09:00",
            "registry_revision": 1,
            "rollout_mode": "READY_FIRST",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "date": "2026-07-06",
                    "seed": "windows update error 0x80070005",
                    "category": "Windows Update",
                    "article_type": "error_code_fix",
                    "quality_precheck": {"status": "ready"},
                    "difference_from_existing": "Different error code.",
                    "image_direction": "Use a distinct update error visual.",
                    "status": "scheduled",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(weekly_queue, "QUEUE_DIR", Path(temp_dir)):
            path = weekly_queue.weekly_queue_path("easy_pc_fix_guide", date(2026, 7, 6))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(weekly_queue.json.dumps(queue, ensure_ascii=False), encoding="utf-8")

            candidates = weekly_queue.today_queue_candidates(
                "easy_pc_fix_guide",
                selected_date=date(2026, 7, 6),
                max_posts=3,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["seed"], "windows update error 0x80070005")
        self.assertEqual(candidates[0]["weekly_queue"]["week"], "2026-W28")

    def test_daily_batch_prefers_weekly_queue_over_fallback_selection(self) -> None:
        queued_candidate = {
            "seed": "korea tax refund for tourists",
            "category": "Shopping",
            "article_type": "checklist",
            "quality_precheck": {"status": "ready"},
            "recent_category": False,
            "weekly_queue": {"week": "2026-W28"},
        }
        with patch("src.pipeline.daily_batch.today_queue_candidates", return_value=[queued_candidate]), patch(
            "src.pipeline.daily_batch.choose_publish_seed_candidates",
            return_value=["korea esim for tourists"],
        ), patch("src.pipeline.daily_batch.used_keywords", return_value=set()), patch(
            "src.pipeline.daily_batch.public_post_titles", return_value=[]
        ), patch("src.pipeline.daily_batch.public_recent_categories", return_value=[]), patch(
            "src.pipeline.daily_batch.list_registry_ready_candidates", return_value=[]
        ), patch("src.pipeline.daily_batch.locally_published_topic_ids", return_value=set()), patch(
            "src.pipeline.daily_batch.seed_quality_precheck", return_value={"status": "ready"}
        ):
            selected = daily_batch.select_seed_candidates("korea_easy_guide", "korea_travel", 3)

        self.assertEqual(selected[0], queued_candidate)
        self.assertEqual(selected[1]["seed"], "korea esim for tourists")

    def test_registry_ready_topics_are_prioritized_and_context_reaches_queue(self) -> None:
        ready = SimpleNamespace(
            topic_id="topic_ready",
            cluster_id="cluster_airport",
            canonical_title="late night transport from incheon airport",
            category_id="cat_transport",
            canonical_intent="how_to",
            action="NEW_POST",
            status="READY",
            revision=3,
            publications=[],
            editor_brief="Compare the safe late-night choices.",
            reader_questions=["What still runs after midnight?"],
            difference_from_existing="Focus on post-midnight arrivals.",
            updated_at="2026-07-05T10:00:00Z",
        )

        class FakeStore:
            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def list_ready_topics(self, site, limit=None):
                return [ready]

            def list_maintenance_topics(self, site, actions=(), statuses=()):
                return []

            def get_category(self, site, category_id):
                return {"category_id": category_id, "blogger_label": "Transportation"}

            def mark_topic_status(self, site, topic_id, status, reason=""):
                return True

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue, "QUEUE_DIR", Path(temp_dir)
        ), patch.dict("os.environ", {"TOPIC_BOARD_MODE": "ready_first"}), patch.object(
            weekly_queue, "load_topic_store", return_value=FakeStore()
        ), patch.object(
            weekly_queue, "locally_published_topic_ids", return_value=set()
        ), patch.object(
            weekly_queue, "choose_publish_seed_candidates", return_value=["legacy fallback topic"]
        ), patch.object(weekly_queue, "used_keywords", return_value=set()), patch.object(
            weekly_queue, "public_post_titles", return_value=[]
        ), patch.object(
            weekly_queue, "seed_quality_precheck", return_value={"status": "ready"}
        ):
            queue = weekly_queue.generate_weekly_queue(
                site="korea_easy_guide",
                start_date=date(2026, 7, 6),
                days=1,
                posts_per_day=1,
                notify=False,
            )

        item = queue["items"][0]
        self.assertEqual(item["topic_id"], "topic_ready")
        self.assertEqual(item["cluster_id"], "cluster_airport")
        self.assertEqual(item["category_id"], "cat_transport")
        self.assertEqual(item["category"], "Transportation")
        self.assertEqual(item["revision"], 3)
        self.assertEqual(item["reader_questions"], ["What still runs after midnight?"])
        self.assertEqual(item["difference_from_existing"], "Focus on post-midnight arrivals.")
        self.assertEqual(queue["topic_selection"]["registry_selected_count"], 1)

    def test_empty_ready_registry_marks_queue_degraded_and_uses_legacy(self) -> None:
        class EmptyStore:
            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def list_ready_topics(self, site, limit=None):
                return []

            def list_maintenance_topics(self, site, actions=(), statuses=()):
                return []

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue, "QUEUE_DIR", Path(temp_dir)
        ), patch.dict("os.environ", {"TOPIC_BOARD_MODE": "ready_first"}), patch.object(
            weekly_queue, "load_topic_store", return_value=EmptyStore()
        ), patch.object(
            weekly_queue, "locally_published_topic_ids", return_value=set()
        ), patch.object(
            weekly_queue, "choose_publish_seed_candidates",
            return_value=["legacy fallback topic"],
        ), patch.object(weekly_queue, "used_keywords", return_value=set()), patch.object(
            weekly_queue, "public_post_titles", return_value=[]
        ), patch.object(
            weekly_queue, "seed_quality_precheck", return_value={"status": "ready"}
        ):
            queue = weekly_queue.generate_weekly_queue(
                site="korea_easy_guide",
                start_date=date(2026, 7, 6),
                days=1,
                posts_per_day=1,
                notify=False,
            )

        self.assertEqual(queue["status"], "DEGRADED")
        self.assertEqual(queue["fallback_reason"], "registry_ready_empty")
        self.assertEqual(queue["topic_selection"]["fallback_source"], "legacy")
        self.assertEqual(queue["items"][0]["topic_source"], "legacy")

    def test_maintenance_actions_are_separate_and_capped_at_two(self) -> None:
        def maintenance_record(index: int, action: str):
            return SimpleNamespace(
                topic_id=f"topic_{index}",
                cluster_id=f"cluster_{index}",
                canonical_title=f"maintenance topic {index}",
                category_id="cat_apps",
                action=action,
                status="UPDATE_DUE",
                revision=index,
                publications=[
                    {
                        "blogger_post_id": f"post_{index}",
                        "url": f"https://example.com/post-{index}.html",
                        "title": f"Existing {index}",
                        "status": "LIVE",
                        "primary": True,
                    }
                ],
                editor_brief="Refresh changed steps.",
                reader_questions=[],
                difference_from_existing="",
            )

        class FakeStore:
            def list_maintenance_topics(self, site, actions=(), statuses=()):
                return [
                    maintenance_record(1, "UPDATE_EXISTING"),
                    maintenance_record(2, "FAQ_ADD"),
                    maintenance_record(3, "UPDATE_EXISTING"),
                ]

            def get_category(self, site, category_id):
                return {"category_id": category_id, "blogger_label": "Apps & Settings"}

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue, "QUEUE_DIR", Path(temp_dir)
        ):
            queue = weekly_queue.generate_maintenance_queue(
                "easy_pc_fix_guide",
                date(2026, 7, 6),
                store=FakeStore(),
                max_items=99,
            )

        self.assertEqual(len(queue["items"]), 2)
        self.assertEqual(
            [item["action"] for item in queue["items"]],
            ["UPDATE_EXISTING", "FAQ_ADD"],
        )
        self.assertTrue(all(item["status"] == "maintenance_review" for item in queue["items"]))

    def test_label_change_requires_applied_snapshot_and_exact_mapping(self) -> None:
        class FakeStore:
            def __init__(self, proposal):
                self.proposal = proposal

            def get_monthly_proposal(self, site, proposal_id):
                return self.proposal

        unsafe = SimpleNamespace(
            kind="LABEL_CHANGE",
            status="APPROVED",
            payload={
                "category_id": "cat-apps",
                "labels": ["Generated", "Unreviewed"],
            },
            approved_by="editor@example.com",
            approved_at="2026-07-01T00:00:00Z",
            applied_at="2026-07-01T00:01:00Z",
            publication_sync_pending=True,
            label_snapshot={},
            snapshot_path="",
        )
        with self.assertRaisesRegex(ValueError, "does not authorize"):
            weekly_queue.maintenance_update_labels(
                FakeStore(unsafe),
                "easy_pc_fix_guide",
                {
                    "category_id": "cat-apps",
                    "approved_label_proposal_id": "proposal-unsafe",
                },
                {
                    "id": "post-existing",
                    "labels": ["Original"],
                },
                ["Generated", "Unreviewed"],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "before.json"
            snapshot_path.write_text("{}", encoding="utf-8")
            approved = SimpleNamespace(
                kind="LABEL_CHANGE",
                status="APPROVED",
                payload={
                    "category_id": "cat-apps",
                    "blogger_label": "Approved Label",
                    "blogger_post_id": "post-existing",
                },
                approved_by="editor@example.com",
                approved_at="2026-07-01T00:00:00Z",
                applied_at="2026-07-01T00:01:00Z",
                publication_sync_pending=True,
                label_snapshot={
                    "categories": {
                        "categories": {
                            "cat-apps": {
                                "blogger_label": "Original",
                            }
                        }
                    }
                },
                snapshot_path=str(snapshot_path),
            )
            labels = weekly_queue.maintenance_update_labels(
                FakeStore(approved),
                "easy_pc_fix_guide",
                {
                    "category_id": "cat-apps",
                    "approved_label_proposal_id": "proposal-approved",
                },
                {
                    "id": "post-existing",
                    "labels": ["Original", "Keep Me"],
                },
                ["Generated"],
            )

        self.assertEqual(labels, ["Approved Label", "Keep Me"])

    def test_maintenance_queue_holds_ambiguous_primary_targets(self) -> None:
        record = SimpleNamespace(
            topic_id="topic-ambiguous",
            cluster_id="cluster-ambiguous",
            canonical_title="ambiguous maintenance target",
            category_id="cat-apps",
            action="UPDATE_EXISTING",
            status="UPDATE_DUE",
            revision=4,
            publications=[
                {
                    "blogger_post_id": "post-one",
                    "url": "https://example.com/one.html",
                    "status": "LIVE",
                    "primary": True,
                },
                {
                    "blogger_post_id": "post-two",
                    "url": "https://example.com/two.html",
                    "status": "LIVE",
                    "primary": True,
                },
            ],
        )

        class FakeStore:
            def list_maintenance_topics(self, *args, **kwargs):
                return [record]

            def get_category(self, *args, **kwargs):
                return {"blogger_label": "Apps"}

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue,
            "QUEUE_DIR",
            Path(temp_dir),
        ):
            queue = weekly_queue.generate_maintenance_queue(
                "easy_pc_fix_guide",
                date(2026, 7, 6),
                store=FakeStore(),
            )

        self.assertEqual(queue["items"], [])

    def test_maintenance_interface_requires_existing_post_and_uses_update_only(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "topic_id": "topic-maintenance",
                    "cluster_id": "cluster-maintenance",
                    "category_id": "cat-apps",
                    "action": "UPDATE_EXISTING",
                    "revision": 4,
                    "existing_post_refs": [
                        {
                            "blogger_post_id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                    "maintenance_target": {
                        "blogger_post_id": "post-existing",
                        "url": "https://example.com/existing.html",
                        "status": "LIVE",
                        "primary": True,
                    },
                    "status": "maintenance_review",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                weekly_queue.json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-maintenance",
                            "topic_action": "UPDATE_EXISTING",
                            "topic_revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(weekly_queue, "QUEUE_DIR", root):
                path = weekly_queue.maintenance_queue_path(
                    "easy_pc_fix_guide",
                    date(2026, 7, 6),
                )
                path.write_text(weekly_queue.json.dumps(queue), encoding="utf-8")
                result = weekly_queue.execute_maintenance_item(
                    "easy_pc_fix_guide",
                    "topic-maintenance",
                    article_dir,
                    selected_date=date(2026, 7, 7),
                    apply=False,
                )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["blogger_post_id"], "post-existing")
        self.assertEqual(result["operation"], "BloggerPublisher.update_post")

    def test_maintenance_apply_updates_existing_post_without_insert(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "topic_id": "topic-maintenance",
                    "cluster_id": "cluster-maintenance",
                    "category_id": "cat-apps",
                    "action": "UPDATE_EXISTING",
                    "revision": 4,
                    "existing_post_refs": [
                        {
                            "blogger_post_id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                    "maintenance_target": {
                        "blogger_post_id": "post-existing",
                        "url": "https://example.com/existing.html",
                        "status": "LIVE",
                        "primary": True,
                    },
                    "status": "maintenance_review",
                }
            ],
        }

        class FakeStore:
            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def claim_topic(
                self,
                site,
                topic_id,
                run_id,
                expected_revision=None,
            ):
                self.run_ids.add(run_id)
                return SimpleNamespace(
                    topic_id=topic_id,
                    cluster_id="cluster-maintenance",
                    canonical_title="Updated existing post",
                    category_id="cat-apps",
                    action="UPDATE_EXISTING",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=run_id,
                    publications=[],
                )

            def verify_publication(self, *args, **kwargs):
                return True

            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    cluster_id="cluster-maintenance",
                    canonical_title="Updated existing post",
                    category_id="cat-apps",
                    action="UPDATE_EXISTING",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=next(iter(self.run_ids), ""),
                    publications=[
                        {
                            "blogger_post_id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                )

            def publication_owner(self, site, blogger_post_id="", url=""):
                return "topic-maintenance"

            def begin_update_attempt(self, *args, **kwargs):
                return {
                    "attempt_id": "update-attempt-maintenance",
                    "action": "UPDATE_EXISTING",
                    "target_primary": True,
                    "acquired": True,
                }

            def mark_update_started(self, *args, **kwargs):
                return {
                    "attempt_id": "update-attempt-maintenance",
                    "action": "UPDATE_EXISTING",
                    "target_primary": True,
                    "status": "UPDATE_STARTED",
                    "started": True,
                }

            def record_update_receipt(self, *args, **kwargs):
                return True

            def __init__(self):
                self.run_ids = set()

        publisher = MagicMock()
        publisher.update_post.return_value = {
            "id": "post-existing",
            "url": "https://example.com/existing.html",
            "status": "LIVE",
            "updated": "2026-07-07T01:00:00Z",
        }
        publisher.list_live_posts.return_value = [
            {
                "id": "post-existing",
                "url": "https://example.com/existing.html",
                "title": "Updated existing post",
                "status": "LIVE",
                "labels": ["Existing Label"],
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                weekly_queue.json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-maintenance",
                            "topic_action": "UPDATE_EXISTING",
                            "topic_revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(weekly_queue, "QUEUE_DIR", root), patch.object(
                weekly_queue,
                "load_topic_store",
                return_value=FakeStore(),
            ), patch.object(
                weekly_queue,
                "BloggerPublisher",
                return_value=publisher,
            ), patch(
                "src.pipeline.stage2_publish.load_article",
                return_value=("Updated existing post", "<article>updated</article>", ["Apps"]),
            ), patch(
                "src.pipeline.stage2_publish.record_topic_publication",
                return_value={
                    "status": "recorded_live_unverified",
                    "durable": True,
                },
            ), patch(
                "src.pipeline.stage2_publish.attach_topic_registry_sync"
            ):
                path = weekly_queue.maintenance_queue_path(
                    "easy_pc_fix_guide",
                    date(2026, 7, 6),
                )
                path.write_text(weekly_queue.json.dumps(queue), encoding="utf-8")
                result = weekly_queue.execute_maintenance_item(
                    "easy_pc_fix_guide",
                    "topic-maintenance",
                    article_dir,
                    selected_date=date(2026, 7, 7),
                    apply=True,
                )

        publisher.update_post.assert_called_once()
        publisher.publish.assert_not_called()
        self.assertEqual(
            publisher.update_post.call_args.kwargs["post_id"],
            "post-existing",
        )
        self.assertEqual(
            publisher.update_post.call_args.kwargs["labels"],
            ["Existing Label"],
        )
        updated_html = publisher.update_post.call_args.kwargs["html"]
        markers = BeautifulSoup(
            updated_html,
            "html.parser",
        ).select("[data-topic-id]")
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["data-topic-id"], "topic-maintenance")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["revision"], 5)
        self.assertEqual(
            result["topic_publication_verification"]["status"],
            "PUBLISHED",
        )

    def test_maintenance_rejects_action_change_after_claim(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "topic_id": "topic-action-change",
                    "cluster_id": "cluster-maintenance",
                    "category_id": "cat-apps",
                    "action": "UPDATE_EXISTING",
                    "revision": 4,
                    "existing_post_refs": [
                        {
                            "blogger_post_id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                    "maintenance_target": {
                        "blogger_post_id": "post-existing",
                        "url": "https://example.com/existing.html",
                        "status": "LIVE",
                        "primary": True,
                    },
                    "status": "maintenance_review",
                }
            ],
        }

        class FakeStore:
            def __init__(self):
                self.release_claim = MagicMock()
                self.run_id = ""

            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def claim_topic(self, site, topic_id, run_id, expected_revision):
                self.run_id = run_id
                return SimpleNamespace(
                    topic_id=topic_id,
                    action="UPDATE_EXISTING",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=run_id,
                )

            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    action="NEW_POST",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=self.run_id,
                    publications=[
                        {
                            "blogger_post_id": "post-existing",
                            "url": "https://example.com/existing.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                )

        store = FakeStore()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                weekly_queue.json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-action-change",
                            "topic_action": "UPDATE_EXISTING",
                            "topic_revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                weekly_queue,
                "QUEUE_DIR",
                root,
            ), patch.object(
                weekly_queue,
                "load_topic_store",
                return_value=store,
            ):
                weekly_queue.save_maintenance_queue(queue)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "action changed",
                ):
                    weekly_queue.execute_maintenance_item(
                        "easy_pc_fix_guide",
                        "topic-action-change",
                        article_dir,
                        selected_date=date(2026, 7, 7),
                        apply=True,
                    )

        self.assertEqual(
            store.release_claim.call_args.kwargs["status"],
            "HOLD",
        )

    def test_maintenance_update_timeout_is_reconciliation_only(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "topic_id": "topic-update-timeout",
                    "cluster_id": "cluster-maintenance",
                    "category_id": "cat-apps",
                    "action": "UPDATE_EXISTING",
                    "revision": 4,
                    "existing_post_refs": [
                        {
                            "blogger_post_id": "post-timeout",
                            "url": "https://example.com/timeout.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                    "maintenance_target": {
                        "blogger_post_id": "post-timeout",
                        "url": "https://example.com/timeout.html",
                        "status": "LIVE",
                        "primary": True,
                    },
                    "status": "maintenance_review",
                }
            ],
        }

        class FakeStore:
            def __init__(self):
                self.run_id = ""
                self.mark_update_unknown = MagicMock()
                self.release_claim = MagicMock()

            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def claim_topic(self, site, topic_id, run_id, expected_revision):
                self.run_id = run_id
                return SimpleNamespace(
                    topic_id=topic_id,
                    action="UPDATE_EXISTING",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=run_id,
                )

            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    cluster_id="cluster-maintenance",
                    category_id="cat-apps",
                    action="UPDATE_EXISTING",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=self.run_id,
                    publications=[
                        {
                            "blogger_post_id": "post-timeout",
                            "url": "https://example.com/timeout.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                )

            def publication_owner(self, *args, **kwargs):
                return "topic-update-timeout"

            def begin_update_attempt(self, *args, **kwargs):
                return {
                    "attempt_id": "attempt-update-timeout",
                    "action": "UPDATE_EXISTING",
                    "target_primary": True,
                    "acquired": True,
                }

            def mark_update_started(self, *args, **kwargs):
                return {
                    "attempt_id": "attempt-update-timeout",
                    "action": "UPDATE_EXISTING",
                    "target_primary": True,
                    "status": "UPDATE_STARTED",
                    "started": True,
                }

        store = FakeStore()
        publisher = MagicMock()
        publisher.list_live_posts.return_value = [
            {
                "id": "post-timeout",
                "url": "https://example.com/timeout.html",
                "status": "LIVE",
                "labels": ["Existing"],
            }
        ]
        publisher.update_post.side_effect = TimeoutError("response lost")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                weekly_queue.json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-update-timeout",
                            "topic_action": "UPDATE_EXISTING",
                            "topic_revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                weekly_queue,
                "QUEUE_DIR",
                root,
            ), patch.object(
                weekly_queue,
                "load_topic_store",
                return_value=store,
            ), patch.object(
                weekly_queue,
                "BloggerPublisher",
                return_value=publisher,
            ), patch(
                "src.pipeline.stage2_publish.load_article",
                return_value=("Updated", "<article>updated</article>", ["New"]),
            ):
                weekly_queue.save_maintenance_queue(queue)
                with self.assertRaises(
                    weekly_queue.MaintenanceReconciliationRequired
                ):
                    weekly_queue.execute_maintenance_item(
                        "easy_pc_fix_guide",
                        "topic-update-timeout",
                        article_dir,
                        selected_date=date(2026, 7, 7),
                        apply=True,
                    )

        publisher.update_post.assert_called_once()
        store.mark_update_unknown.assert_called_once()
        store.release_claim.assert_not_called()

    def test_maintenance_rejects_target_owned_by_another_topic(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "topic_id": "topic-wrong-owner",
                    "cluster_id": "cluster-maintenance",
                    "category_id": "cat-apps",
                    "action": "FAQ_ADD",
                    "revision": 4,
                    "existing_post_refs": [
                        {
                            "blogger_post_id": "post-other",
                            "url": "https://example.com/other.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                    "maintenance_target": {
                        "blogger_post_id": "post-other",
                        "url": "https://example.com/other.html",
                        "status": "LIVE",
                        "primary": True,
                    },
                    "status": "maintenance_review",
                }
            ],
        }

        class FakeStore:
            def __init__(self):
                self.release_claim = MagicMock()
                self.run_id = ""

            def get_rollout_state(self, site):
                return {"mode": "READY_FIRST", "promoted": True}

            def claim_topic(self, site, topic_id, run_id, expected_revision):
                self.run_id = run_id
                return SimpleNamespace(
                    topic_id=topic_id,
                    action="FAQ_ADD",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=run_id,
                )

            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    action="FAQ_ADD",
                    status="CLAIMED",
                    revision=5,
                    claim_run_id=self.run_id,
                    publications=[
                        {
                            "blogger_post_id": "post-other",
                            "url": "https://example.com/other.html",
                            "status": "LIVE",
                            "primary": True,
                        }
                    ],
                )

            def publication_owner(self, *args, **kwargs):
                return "topic-actual-owner"

        store = FakeStore()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            article_dir = root / "article"
            article_dir.mkdir()
            (article_dir / "metadata.json").write_text(
                weekly_queue.json.dumps(
                    {
                        "candidate": {
                            "topic_id": "topic-wrong-owner",
                            "topic_action": "FAQ_ADD",
                            "topic_revision": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                weekly_queue,
                "QUEUE_DIR",
                root,
            ), patch.object(
                weekly_queue,
                "load_topic_store",
                return_value=store,
            ):
                weekly_queue.save_maintenance_queue(queue)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "belongs to another topic",
                ):
                    weekly_queue.execute_maintenance_item(
                        "easy_pc_fix_guide",
                        "topic-wrong-owner",
                        article_dir,
                        selected_date=date(2026, 7, 7),
                        apply=True,
                    )

        self.assertEqual(
            store.release_claim.call_args.kwargs["status"],
            "HOLD",
        )

    def test_today_queue_revalidates_registry_status_and_revision(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "research_run_id": "weekly-current",
            "research_run_at": "2026-07-05T20:15:00+09:00",
            "registry_revision": 1,
            "rollout_mode": "READY_FIRST",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "date": "2026-07-06",
                    "seed": "old queued title",
                    "topic_id": "topic_ready",
                    "category": "Windows Update",
                    "article_type": "error_code_fix",
                    "action": "NEW_POST",
                    "revision": 1,
                    "status": "scheduled",
                }
            ],
        }
        current = SimpleNamespace(
            topic_id="topic_ready",
            cluster_id="cluster_update",
            canonical_title="current registry title",
            category_id="cat_update",
            action="NEW_POST",
            status="READY",
            revision=2,
            publications=[],
            editor_brief="Use current evidence.",
            reader_questions=[],
            difference_from_existing="",
        )

        class FakeStore:
            def get_rollout_state(self, site):
                return {
                    "mode": "READY_FIRST",
                    "last_status": "SUCCESS",
                    "last_run_id": "weekly-current",
                    "backfill": {"complete": True},
                }

            def _load_registry(self, site):
                return {"revision": 2}

            def get_topic(self, site, topic_id):
                return current

            def get_category(self, site, category_id):
                return {"blogger_label": "Windows Update"}

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue, "QUEUE_DIR", Path(temp_dir)
        ), patch.object(weekly_queue, "load_topic_store", return_value=FakeStore()):
            path = weekly_queue.weekly_queue_path("easy_pc_fix_guide", date(2026, 7, 6))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(weekly_queue.json.dumps(queue), encoding="utf-8")
            candidates = weekly_queue.today_queue_candidates(
                "easy_pc_fix_guide",
                selected_date=date(2026, 7, 6),
                max_posts=1,
            )

        self.assertEqual(candidates[0]["seed"], "current registry title")
        self.assertEqual(candidates[0]["revision"], 2)
        self.assertEqual(candidates[0]["registry_revalidation"]["status"], "passed")

    def test_invalid_queued_registry_topic_is_replaced_by_legacy_candidate(self) -> None:
        queue = {
            "site": "easy_pc_fix_guide",
            "week": "2026-W28",
            "start_date": "2026-07-06",
            "end_date": "2026-07-12",
            "items": [
                {
                    "date": "2026-07-06",
                    "seed": "stale scheduled topic",
                    "topic_id": "topic-stale",
                    "category": "Windows Update",
                    "article_type": "error_code_fix",
                    "action": "NEW_POST",
                    "revision": 4,
                    "status": "scheduled",
                }
            ],
        }

        class FakeStore:
            def get_topic(self, site, topic_id):
                return SimpleNamespace(
                    topic_id=topic_id,
                    canonical_title="stale scheduled topic",
                    category_id="cat-update",
                    action="NEW_POST",
                    status="REVIEW",
                    revision=5,
                    publications=[],
                )

            def get_category(self, site, category_id):
                return {"blogger_label": "Windows Update"}

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            weekly_queue,
            "QUEUE_DIR",
            Path(temp_dir),
        ), patch.object(
            weekly_queue,
            "load_topic_store",
            return_value=FakeStore(),
        ), patch.object(
            daily_batch,
            "today_queue_candidates",
            side_effect=lambda site, max_posts: weekly_queue.today_queue_candidates(
                site,
                selected_date=date(2026, 7, 6),
                max_posts=max_posts,
            ),
        ), patch.object(
            daily_batch,
            "list_registry_ready_candidates",
            return_value=[],
        ), patch.object(
            daily_batch,
            "choose_publish_seed_candidates",
            return_value=["fresh legacy replacement"],
        ), patch.object(
            daily_batch,
            "used_keywords",
            return_value=set(),
        ), patch.object(
            daily_batch,
            "public_post_titles",
            return_value=[],
        ), patch.object(
            daily_batch,
            "public_recent_categories",
            return_value=[],
        ), patch.object(
            daily_batch,
            "locally_published_topic_ids",
            return_value=set(),
        ), patch.object(
            daily_batch,
            "seed_quality_precheck",
            return_value={"status": "ready"},
        ), patch.object(
            daily_batch,
            "topic_board_mode",
            return_value="ready_first",
        ):
            path = weekly_queue.weekly_queue_path(
                "easy_pc_fix_guide",
                date(2026, 7, 6),
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(weekly_queue.json.dumps(queue), encoding="utf-8")
            selected = daily_batch.select_seed_candidates(
                "easy_pc_fix_guide",
                "windows_help",
                1,
            )

        self.assertEqual([item["seed"] for item in selected], ["fresh legacy replacement"])
        self.assertEqual(selected[0]["topic_source"], "legacy")

    def test_three_post_days_use_two_evergreen_and_one_trend_slot(self) -> None:
        candidates = [
            {
                "seed": "how to use naver map in korea",
                "category": "Apps in Korea",
                "article_type": "how_to",
                "slot_strategy": weekly_queue.EVERGREEN_SLOT,
                "strategy_reason": "evergreen",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
            {
                "seed": "korea esim guide for tourists",
                "category": "Mobile & Internet",
                "article_type": "checklist",
                "slot_strategy": weekly_queue.EVERGREEN_SLOT,
                "strategy_reason": "evergreen",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
            {
                "seed": "korea rainy season travel tips",
                "category": "Travel Basics",
                "article_type": "checklist",
                "slot_strategy": weekly_queue.TREND_SLOT,
                "strategy_reason": "seasonal",
                "quality_precheck": {"status": "ready"},
                "difference_from_existing": "",
                "avoid_overlap_with": [],
                "image_direction": "",
            },
        ]

        items = weekly_queue.assign_candidates_to_week(
            candidates,
            start_date=date(2026, 7, 6),
            days=1,
            posts_per_day=3,
            site="korea_easy_guide",
        )

        self.assertEqual([item["slot_strategy"] for item in items], [
            weekly_queue.EVERGREEN_SLOT,
            weekly_queue.EVERGREEN_SLOT,
            weekly_queue.TREND_SLOT,
        ])
        self.assertEqual(items[2]["seed"], "korea rainy season travel tips")
        self.assertFalse(items[2]["strategy_fallback"])

    def test_candidate_from_queue_exposes_strategy_metadata(self) -> None:
        queue = {"week": "2026-W28", "_path": "/tmp/queue.json"}
        item = {
            "date": "2026-07-06",
            "seed": "windows 11 slow after update",
            "category": "Beginner PC Tips",
            "article_type": "beginner_guide",
            "slot_strategy": weekly_queue.TREND_SLOT,
            "strategy_reason": "Windows update or recent-issue demand",
        }

        candidate = weekly_queue.candidate_from_queue_item(queue, item)

        self.assertEqual(candidate["weekly_queue"]["slot_strategy"], weekly_queue.TREND_SLOT)
        self.assertIn("recent-issue", candidate["weekly_queue"]["strategy_reason"])


if __name__ == "__main__":
    unittest.main()
