from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR, Settings
from src.pipeline.stage4_publication_check import classify_daily_success_context
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import is_success_status
from src.pipeline.stage4_publication_check import parse_posts
from src.pipeline.stage4_publication_check import publication_status
from src.reporting.daily_reports import read_daily_success_report
from src.reporting.cadence import review_cadence
from src.reporting.analytics import GA4Client
from src.reporting.search_console import SearchConsoleClient
from src.quality.action_guidance import quality_issue_actions
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import reddit_oauth_secret_label


KST = ZoneInfo("Asia/Seoul")
MONITORING_START_DATE = datetime(2026, 6, 24, tzinfo=KST).date()
TWO_WEEK_MONITORING_DATE = datetime(2026, 7, 8, tzinfo=KST).date()
THREE_WEEK_MONITORING_DATE = datetime(2026, 7, 15, tzinfo=KST).date()


class WeeklyReporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.generated_root = Path(settings.generated_output_dir)

    def generate(self) -> Path:
        now = datetime.now(tz=KST)
        week_start = now - timedelta(days=7)
        articles = self._collect_articles(week_start)
        public_posts = self._collect_public_posts(week_start)
        static_pages = self._static_pages_result()
        signal_quality = self._signal_quality_result(articles)
        search_console_client = SearchConsoleClient(self.settings)
        search_console = search_console_client.summary(week_start.date(), now.date())
        indexed_pages = search_console_client.indexed_page_estimate(week_start.date(), now.date())
        operations = self._operations_result(now, public_posts, search_console)
        quality_issues = self._quality_issues_result(articles)
        local_published_count = sum(1 for item in articles if item.get("blogger_status") == "LIVE")
        published_count = max(local_published_count, len(public_posts.get("posts", [])))
        article_status_counts = article_status_summary(articles)
        cadence_review = review_cadence(
            today=now.date(),
            published_posts=published_count,
            indexed_pages_estimate=indexed_pages.get("page_count_with_search_data", 0),
            recent_impressions=search_console.get("totals_from_top_queries", {}).get("impressions", 0),
            quality_issue_count=len(quality_issues),
            signal_quality=signal_quality,
            reddit_health=operations.get("reddit_health", {}),
        )

        report = {
            "generated_at": now.isoformat(),
            "site_name": self.settings.site_name,
            "site_url": self.settings.site_url,
            "week_start": week_start.date().isoformat(),
            "week_end": now.date().isoformat(),
            "article_count": len(articles),
            "draft_count": sum(1 for item in articles if item.get("blogger_status") == "DRAFT"),
            "published_count": published_count,
            "local_published_count": local_published_count,
            "article_status_counts": article_status_counts,
            "articles": articles,
            "public_posts": public_posts,
            "static_pages": static_pages,
            "signal_quality": signal_quality,
            "search_console": search_console,
            "indexed_pages": indexed_pages,
            "analytics": GA4Client(self.settings).summary(week_start.date(), now.date()),
            "operations": operations,
            "cadence_review": cadence_review.to_dict(),
            "quality_issues": quality_issues,
            "next_actions": self._next_actions(articles, static_pages, public_posts, operations, signal_quality, quality_issues),
        }

        output_dir = ROOT_DIR / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{self.settings.site_key}-weekly-{now.date().isoformat()}.json"
        md_path = output_dir / f"{self.settings.site_key}-weekly-{now.date().isoformat()}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._to_markdown(report), encoding="utf-8")
        return md_path

    def _collect_articles(self, week_start: datetime) -> list[dict]:
        articles = []
        for metadata_path in self.generated_root.glob("*/*/metadata.json"):
            if metadata_path.stat().st_mtime < week_start.timestamp():
                continue
            article_dir = metadata_path.parent
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            article = metadata.get("article", {})
            candidate = metadata.get("candidate", {})
            research_report = self._read_report(article_dir / "research_report.json")
            publish_result_path = article_dir / "blogger_publish_result.json"
            update_result_path = article_dir / "blogger_update_result.json"
            validation_result_path = article_dir / "validation_result.json"
            blogger = self._best_blogger_result([publish_result_path, update_result_path])
            validation = self._read_report(validation_result_path)
            article_status = blogger.get("status") or _article_validation_status(validation)
            articles.append(
                {
                    "title": article.get("title"),
                    "slug": article.get("slug"),
                    "category": article.get("category"),
                    "seed_keyword": research_report.get("seed_keyword") or candidate.get("keyword", ""),
                    "content_domain": research_report.get("content_domain") or self.settings.content_domain,
                    "tags": article.get("tags", []),
                    "article_dir": str(article_dir),
                    "blogger_id": blogger.get("id"),
                    "blogger_status": blogger.get("status"),
                    "article_status": article_status,
                    "blogger_url": blogger.get("url"),
                    "updated": blogger.get("updated"),
                }
            )
        return sorted(articles, key=lambda item: item.get("title") or "")

    def _collect_public_posts(self, week_start: datetime) -> dict:
        try:
            posts = [
                post
                for post in parse_posts(fetch_public_feed(self.settings.site_url))
                if post["published_kst"].date() >= week_start.date()
            ]
        except Exception as exc:
            return {
                "status": "error",
                "site_url": self.settings.site_url,
                "error": str(exc),
                "posts": [],
            }

        return {
            "status": "connected",
            "site_url": self.settings.site_url,
            "posts": [
                {
                    "title": post["title"],
                    "url": post["url"],
                    "published_kst": post["published_kst"].isoformat(),
                }
                for post in posts
            ],
        }

    def _best_blogger_result(self, paths: list[Path]) -> dict:
        results = []
        for path in paths:
            if path.exists():
                results.append(json.loads(path.read_text(encoding="utf-8")).get("blogger", {}))
        if not results:
            return {}
        live_results = [item for item in results if item.get("status") == "LIVE"]
        if live_results:
            return max(live_results, key=lambda item: item.get("updated") or "")
        return max(results, key=lambda item: item.get("updated") or "")

    def _static_pages_result(self) -> list[dict]:
        path = self.generated_root / "static_pages" / "blogger_pages_result.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("pages", [])

    def _operations_result(
        self,
        now: datetime | None = None,
        public_posts: dict | None = None,
        search_console: dict | None = None,
    ) -> dict:
        report_dir = ROOT_DIR / "reports"
        daily_success = read_daily_success_report(self.settings.site_key, report_dir)
        daily_success_context = classify_daily_success_context(daily_success)
        publication_check = self._read_report(report_dir / f"{self.settings.site_key}-publication-check.json")
        if (
            now is not None
            and public_posts is not None
            and self._publication_check_needs_public_feed_refresh(publication_check, now, daily_success_context)
        ):
            publication_check = self._publication_check_from_public_posts(now, public_posts)
        sitemap_submit = self._read_report(report_dir / f"{self.settings.site_key}-search-console-sitemap-submit.json")
        sitemap_submit = self._normalize_sitemap_submit_report(sitemap_submit)
        if self._sitemap_report_is_not_current(sitemap_submit, now) and (public_posts or search_console):
            sitemap_submit = {
                "status": "not_persisted",
                "note": "이전 workflow artifact는 주간 workflow 환경에 자동 보존되지 않습니다. Daily publish workflow는 공개 발행 직후 sitemap 제출 단계를 실행합니다.",
                "previous_status": sitemap_submit.get("status", "not_uploaded"),
                "previous_submitted_at": sitemap_submit.get("submitted_at", ""),
            }
        daily_failure = self._daily_failure_for_current_day(
            self._read_report(report_dir / f"{self.settings.site_key}-daily-failure.json"),
            now,
        )
        return {
            "daily_success": daily_success,
            "daily_success_context": daily_success_context,
            "daily_seed_plan": self._seed_plan_for_current_day(
                self._read_report(report_dir / f"{self.settings.site_key}-daily-seed-plan.json"),
                now,
            ),
            "daily_failure": daily_failure,
            "preflight": self._read_report(report_dir / f"{self.settings.site_key}-preflight.json"),
            "reddit_health": self._reddit_health_for_current_day(
                self._read_report(report_dir / f"{self.settings.site_key}-reddit-health.json"),
                now,
            ),
            "publication_check": publication_check,
            "sitemap_submit": sitemap_submit,
        }

    def _publication_check_needs_public_feed_refresh(
        self,
        publication_check: dict,
        now: datetime,
        daily_success_context: dict,
    ) -> bool:
        if publication_check.get("status") == "not_uploaded":
            return True
        checked_at = _parse_datetime(publication_check.get("checked_at_kst", ""))
        if checked_at and checked_at.date() != now.date():
            return True
        evidence = publication_check.get("publication_evidence") or {}
        if (
            evidence.get("status") == "feed_and_workflow_confirmed_report_not_publish"
            and daily_success_context.get("status") == "not_uploaded"
        ):
            return True
        return False

    def _sitemap_report_is_not_current(self, sitemap_submit: dict, now: datetime | None) -> bool:
        if sitemap_submit.get("status") == "not_uploaded":
            return True
        if now is None:
            return False
        submitted_at = _parse_datetime(str(sitemap_submit.get("submitted_at", "")))
        if submitted_at is None:
            return sitemap_submit.get("timestamp_status") != "legacy_missing_submitted_at"
        return submitted_at.date() != now.date()

    def _normalize_sitemap_submit_report(self, sitemap_submit: dict) -> dict:
        if (
            sitemap_submit.get("status") == "submitted"
            and sitemap_submit.get("sitemap_url")
            and not sitemap_submit.get("submitted_at")
        ):
            return {
                **sitemap_submit,
                "note": (
                    sitemap_submit.get("note")
                    or "sitemap 제출 성공 리포트입니다. 이전 형식이라 submitted_at은 기록되지 않았습니다."
                ),
                "timestamp_status": "legacy_missing_submitted_at",
            }
        return sitemap_submit

    def _daily_failure_for_current_day(self, daily_failure: dict, now: datetime | None) -> dict:
        if daily_failure.get("status") != "failed" or now is None:
            return daily_failure
        created_at = _parse_datetime(str(daily_failure.get("created_at", "")))
        if created_at and created_at.astimezone(KST).date() == now.astimezone(KST).date():
            return daily_failure
        return {
            "status": "stale_failure",
            "note": "이전 일일 실패 리포트입니다. 오늘 실패로 보지 않습니다.",
            "previous_status": daily_failure.get("status", "failed"),
            "previous_created_at": daily_failure.get("created_at", ""),
            "error_type": daily_failure.get("error_type", ""),
            "error": daily_failure.get("error", ""),
            "seed": daily_failure.get("seed", ""),
        }

    def _reddit_health_for_current_day(self, reddit_health: dict, now: datetime | None) -> dict:
        if now is None:
            return reddit_health
        if reddit_health.get("status") == "not_uploaded":
            return {
                "status": "reddit_health_missing",
                "status_label": "Reddit Health 리포트 없음",
                "health_score": 0,
                "blocks_cadence_increase": True,
                "action_required": "Easy PC Fix Reddit OAuth Health workflow를 실행해 오늘 Reddit 수집 상태를 확인하세요.",
            }
        checked_at = _parse_datetime(str(reddit_health.get("checked_at", "")))
        if checked_at and checked_at.astimezone(KST).date() == now.astimezone(KST).date():
            return reddit_health
        return {
            **reddit_health,
            "status": "stale_reddit_health",
            "status_label": "이전 Reddit Health 리포트",
            "health_score": 0,
            "blocks_cadence_increase": True,
            "action_required": "Reddit Health 리포트가 오늘 실행된 결과가 아닙니다. workflow를 다시 실행해 최신 상태를 확인하세요.",
            "previous_status": reddit_health.get("status", "unknown"),
            "previous_checked_at": reddit_health.get("checked_at", ""),
        }

    def _seed_plan_for_current_day(self, seed_plan: dict, now: datetime | None) -> dict:
        if now is None or seed_plan.get("status") == "not_uploaded":
            return seed_plan
        today = now.astimezone(KST).date().isoformat()
        if seed_plan.get("today_kst") == today:
            return seed_plan
        return {
            **seed_plan,
            "status": "stale_seed_plan",
            "previous_today_kst": seed_plan.get("today_kst", ""),
            "note": "이전 일일 시드 계획입니다. 오늘 plan workflow가 아직 실행되지 않았거나 artifact가 보존되지 않았습니다.",
        }

    def _publication_check_from_public_posts(self, now: datetime, public_posts: dict) -> dict:
        if public_posts.get("status") != "connected":
            return {
                "status": "not_uploaded",
                "source": "public_feed",
                "note": "발행 확인 artifact가 없고 공개 피드도 확인되지 않았습니다.",
            }
        cutoff = now.replace(hour=9, minute=0, second=0, microsecond=0)
        all_todays_posts = []
        todays_posts = []
        for post in public_posts.get("posts", []):
            published_raw = post.get("published_kst", "")
            try:
                published_at = datetime.fromisoformat(published_raw)
            except ValueError:
                continue
            if published_at.date() == now.date():
                all_todays_posts.append(post)
                if published_at >= cutoff:
                    todays_posts.append(post)
        status = publication_status(todays_posts, all_todays_posts, cutoff)
        before_cutoff_window = now < cutoff and not all_todays_posts
        if before_cutoff_window:
            status = "pending_today_before_cutoff"
        public_feed_ok = is_success_status(status)
        duplicate_today = status == "duplicate_today"
        return {
            "site": self.settings.site_key,
            "site_name": self.settings.site_name,
            "site_url": self.settings.site_url,
            "checked_at_kst": now.isoformat(),
            "cutoff_kst": cutoff.isoformat(),
            "status": status,
            "source": "weekly_public_feed_fallback",
            "today_post_count": len(todays_posts),
            "today_total_post_count": len(all_todays_posts),
            "latest_posts": public_posts.get("posts", [])[:5],
            "publication_evidence": {
                "status": (
                    "weekly_duplicate_publication_detected"
                    if duplicate_today
                    else "weekly_public_feed_before_cutoff"
                    if before_cutoff_window
                    else "weekly_public_feed_confirmed"
                    if public_feed_ok
                    else "weekly_public_feed_missing_today"
                ),
                "label": (
                    "주간 보고 공개 피드 기준 오늘 글 2개 이상 감지"
                    if duplicate_today
                    else "주간 보고 실행 시각이 발행 기준 전"
                    if before_cutoff_window
                    else "주간 보고 공개 피드 기준 확인"
                    if public_feed_ok
                    else "주간 보고 공개 피드 기준 오늘 글 없음"
                ),
                "note": (
                    "하루 1개 운영 기준을 초과했습니다. 자동 발행 중복 또는 예약 발행 충돌 가능성을 확인하세요."
                    if duplicate_today
                    else "아직 09:00 KST 발행 확인 기준 전입니다. 오늘 발행 여부는 Daily workflow 실행 후 다시 확인합니다."
                    if before_cutoff_window
                    else (
                    "발행 확인 workflow artifact가 없거나 오래되어 공개 Blogger feed로 재계산했습니다."
                    if public_feed_ok
                    else "공개 Blogger feed에서 오늘 공개 글을 찾지 못했습니다."
                    )
                ),
                "needs_attention": (not public_feed_ok and not before_cutoff_window) or duplicate_today,
            },
        }

    def _read_report(self, path: Path) -> dict:
        if not path.exists():
            return {"status": "not_uploaded", "path": str(path)}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"status": "error", "path": str(path), "error": str(exc)}
        data.setdefault("path", str(path))
        return data

    def _quality_issue_count(self, articles: list[dict]) -> int:
        issue_count = 0
        resolved_seed_keywords = _resolved_seed_keywords(articles)
        for article in articles:
            if not _quality_report_is_actionable(article, resolved_seed_keywords):
                continue
            quality_path = Path(article.get("article_dir", "")) / "quality_report.json"
            if not quality_path.exists():
                continue
            try:
                report = json.loads(quality_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                issue_count += 1
                continue
            issue_count += len(report.get("issues", []))
        return issue_count

    def _quality_issues_result(self, articles: list[dict]) -> list[dict]:
        results = []
        resolved_seed_keywords = _resolved_seed_keywords(articles)
        for article in articles:
            if not _quality_report_is_actionable(article, resolved_seed_keywords):
                continue
            quality_path = Path(article.get("article_dir", "")) / "quality_report.json"
            if not quality_path.exists():
                continue
            try:
                report = json.loads(quality_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                results.append(
                    {
                        "title": article.get("title") or article.get("slug") or article.get("article_dir", ""),
                        "article_dir": article.get("article_dir", ""),
                        "code": "invalid_quality_report",
                        "message": str(exc),
                        "severity": "error",
                    }
                )
                continue
            for issue in report.get("issues", []):
                results.append(
                    {
                        "title": article.get("title") or article.get("slug") or article.get("article_dir", ""),
                        "article_dir": article.get("article_dir", ""),
                        "code": issue.get("code", "unknown"),
                        "message": issue.get("message", ""),
                        "severity": issue.get("severity", ""),
                    }
                )
        return results

    def _signal_quality_result(self, articles: list[dict]) -> dict:
        totals = {
            "article_count_with_research": 0,
            "live_reddit_signal_count": 0,
            "reddit_oauth_signal_count": 0,
            "reddit_public_json_signal_count": 0,
            "fallback_reddit_signal_count": 0,
            "google_suggest_signal_count": 0,
            "google_suggest_live_signal_count": 0,
            "google_suggest_fallback_signal_count": 0,
        }
        source_counts: dict[str, int] = {}
        reddit_method_counts: dict[str, int] = {}
        google_method_counts: dict[str, int] = {}
        fallback_articles: list[str] = []
        fallback_article_count = 0
        reddit_diagnostics: list[dict] = []
        google_diagnostics: list[dict] = []
        for article in articles:
            research_path = Path(article.get("article_dir", "")) / "research_report.json"
            if not research_path.exists():
                continue
            try:
                report = json.loads(research_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            totals["article_count_with_research"] += 1
            for key in [
                "live_reddit_signal_count",
                "reddit_oauth_signal_count",
                "reddit_public_json_signal_count",
                "fallback_reddit_signal_count",
                "google_suggest_signal_count",
                "google_suggest_live_signal_count",
                "google_suggest_fallback_signal_count",
            ]:
                totals[key] += int(report.get(key, 0) or 0)
            for source, count in report.get("signal_source_counts", {}).items():
                source_counts[source] = source_counts.get(source, 0) + int(count or 0)
            for method, count in report.get("reddit_collection_method_counts", {}).items():
                reddit_method_counts[method] = reddit_method_counts.get(method, 0) + int(count or 0)
            for method, count in report.get("google_suggest_method_counts", {}).items():
                google_method_counts[method] = google_method_counts.get(method, 0) + int(count or 0)
            if int(report.get("fallback_reddit_signal_count", 0) or 0) and not int(
                report.get("live_reddit_signal_count", 0) or 0
            ):
                fallback_article_count += 1
                fallback_articles.append(article.get("title") or article.get("slug") or article.get("article_dir", ""))
            diagnostics = report.get("reddit_collection_diagnostics") or {}
            if diagnostics:
                reddit_diagnostics.append(
                    {
                        "title": article.get("title") or article.get("slug") or article.get("article_dir", ""),
                        "status": diagnostics.get("status", "unknown"),
                        "oauth_configured": bool(diagnostics.get("oauth_configured")),
                        "public_json_error_count": int(diagnostics.get("public_json_error_count", 0) or 0),
                        "failed_subreddits": [
                            item.get("subreddit", "")
                            for item in diagnostics.get("public_json_failed_subreddits", [])
                            if item.get("subreddit")
                        ],
                        "fallback_reason": diagnostics.get("fallback_reason", ""),
                        "oauth_error": diagnostics.get("oauth_error", ""),
                    }
                )
            google_diagnostic = report.get("google_suggest_diagnostics") or {}
            if google_diagnostic:
                google_diagnostics.append(
                    {
                        "title": article.get("title") or article.get("slug") or article.get("article_dir", ""),
                        "status": google_diagnostic.get("status", "unknown"),
                        "live_suggestion_count": int(google_diagnostic.get("live_suggestion_count", 0) or 0),
                        "fallback_suggestion_count": int(google_diagnostic.get("fallback_suggestion_count", 0) or 0),
                        "used_fallback": bool(google_diagnostic.get("used_fallback")),
                        "fallback_reason": google_diagnostic.get("fallback_reason", ""),
                        "error": google_diagnostic.get("error", ""),
                    }
                )

        status = "not_uploaded"
        if totals["article_count_with_research"]:
            status = "fallback_only" if fallback_articles else "connected"
        return {
            "status": status,
            **totals,
            "signal_source_counts": dict(sorted(source_counts.items())),
            "reddit_collection_method_counts": dict(sorted(reddit_method_counts.items())),
            "google_suggest_method_counts": dict(sorted(google_method_counts.items())),
            "fallback_only_article_count": fallback_article_count,
            "fallback_only_articles": list(dict.fromkeys(fallback_articles)),
            "reddit_collection_diagnostics": reddit_diagnostics,
            "google_suggest_diagnostics": google_diagnostics,
        }

    def _next_actions(
        self,
        articles: list[dict],
        static_pages: list[dict],
        public_posts: dict | None = None,
        operations: dict | None = None,
        signal_quality: dict | None = None,
        quality_issues: list[dict] | None = None,
    ) -> list[str]:
        actions = []
        public_post_count = len((public_posts or {}).get("posts", []))
        has_local_live_article = any(article.get("blogger_status") == "LIVE" for article in articles)
        has_public_article = has_local_live_article or public_post_count > 0
        operations = operations or {}
        preflight_status = operations.get("preflight", {}).get("status")
        daily_failure_status = operations.get("daily_failure", {}).get("status")
        publication_status = operations.get("publication_check", {}).get("status")
        sitemap_status = operations.get("sitemap_submit", {}).get("status")
        daily_success = operations.get("daily_success", {})
        operational_status = daily_success.get("operational_status", {})
        reddit_health = operations.get("reddit_health", {})
        preflight_checks = operations.get("preflight", {}).get("checks", []) or []
        seed_file_check = next((check for check in preflight_checks if check.get("name") == "seed_file"), {})
        seed_inventory_check = next((check for check in preflight_checks if check.get("name") == "seed_inventory"), {})
        all_seed_quality_check = next((check for check in preflight_checks if check.get("name") == "all_seed_quality"), {})
        launch_queue_check = next((check for check in preflight_checks if check.get("name") == "launch_queue"), {})
        launch_queue_quality_check = next((check for check in preflight_checks if check.get("name") == "launch_queue_quality"), {})
        if preflight_status == "fail":
            actions.append("Preflight 실패 항목을 먼저 복구하세요. 설정, workflow 안전장치, 알림 설정을 확인해야 합니다.")
        elif preflight_status == "warn":
            actions.append("Preflight 주의 항목을 확인하세요. 자동화는 계속되지만 운영 리스크가 있습니다.")
        if launch_queue_check.get("status") in {"warn", "fail"}:
            launch_message = launch_queue_check.get("message", "")
            if "long-term seed list" in launch_message:
                actions.append(
                    "Launch queue가 소진되어 장기 Windows topic seed 목록으로 운영 중입니다. 새 블로그 초반 집중 주제가 더 필요하면 launch queue를 보충하세요."
                )
            else:
                actions.append(f"Launch queue 상태를 확인하세요. {launch_message}")
        if launch_queue_quality_check.get("status") in {"warn", "fail"}:
            quality_message = launch_queue_quality_check.get("message", "")
            actions.append(
                "Launch queue 품질검수에 실패했습니다. 너무 일반적인 Windows 주제, main seed 누락, Microsoft 출처 부족 항목을 고친 뒤 다시 실행하세요. "
                f"{quality_message}"
            )
        if seed_file_check.get("status") in {"warn", "fail"}:
            seed_file_message = seed_file_check.get("message", "")
            if "Duplicate topic seeds" in seed_file_message:
                actions.append(f"Windows topic seed 파일에 중복이 있습니다. 중복 시드를 제거한 뒤 다시 실행하세요. {seed_file_message}")
            elif "blank topic seed" in seed_file_message:
                actions.append(f"Windows topic seed 파일에 빈 항목이 있습니다. 빈 줄/빈 문자열을 제거하세요. {seed_file_message}")
            elif "Weak Windows topic seeds" in seed_file_message:
                actions.append(
                    f"Windows topic seed가 너무 모호합니다. 오류 코드, 증상, 앱, Windows 기능이 드러나는 구체 주제로 바꾸세요. {seed_file_message}"
                )
            elif seed_file_check.get("status") == "warn":
                actions.append(f"Windows topic seed 수가 부족합니다. 장기 자동화를 위해 새 주제를 보충하세요. {seed_file_message}")
            else:
                actions.append(f"Windows topic seed 파일을 확인하세요. {seed_file_message}")
        if seed_inventory_check.get("status") in {"warn", "fail"}:
            seed_message = seed_inventory_check.get("message", "")
            if seed_inventory_check.get("status") == "fail":
                actions.append(
                    f"Windows topic seed 재고가 소진되었습니다. 다음 무인 발행 전에 새 오류/증상 시드를 추가하세요. {seed_message}"
                )
            else:
                actions.append(
                    f"Windows topic seed 재고가 낮습니다. 최소 2주치 이상 새 주제를 보충하세요. {seed_message}"
                )
        if all_seed_quality_check.get("status") in {"warn", "fail"}:
            actions.append(
                "장기 Windows topic seed 품질검수에 실패했습니다. 장기 큐로 넘어가기 전에 일반적인 주제, 약한 Microsoft 출처, "
                f"카테고리 누락 항목을 수정하세요. {all_seed_quality_check.get('message', '')}"
            )
        if daily_failure_status == "failed":
            actions.append("최근 일일 자동화 실패 리포트를 확인하세요. daily failure JSON의 오류 타입, 메시지, traceback을 우선 점검해야 합니다.")
        if publication_status == "missing_today":
            actions.append("발행 확인에서 오늘 공개 글을 찾지 못했습니다. daily publish 실행 결과와 Blogger 공개 피드를 확인하세요.")
        elif publication_status == "error":
            actions.append("발행 확인 워크플로우 오류를 확인하세요. Blogger 공개 피드 접근 또는 알림 설정 문제가 있을 수 있습니다.")
        if sitemap_status == "error":
            actions.append("Search Console sitemap 제출 실패를 확인하세요. OAuth 토큰과 Search Console 권한을 점검해야 합니다.")
        elif sitemap_status == "not_uploaded":
            actions.append("Search Console sitemap 제출 결과 파일이 없습니다. publish 실행 후 sitemap 제출 단계가 실행됐는지 확인하세요.")
        elif sitemap_status == "not_persisted":
            actions.append(
                "Search Console sitemap 제출 리포트가 주간 workflow 환경에 보존되지 않았습니다. "
                "Daily Publish artifact에서 search-console-sitemap-submit.json을 확인하거나 sitemap 제출 workflow를 수동 재실행하세요."
            )
        if len(static_pages) < 4:
            actions.append("필수 고정 페이지 4개(About, Contact, Privacy Policy, Disclaimer)를 모두 발행하세요.")
        if not articles and not has_public_article:
            actions.append("최소 1개의 글 초안을 생성하세요.")
        if articles and not has_local_live_article and has_public_article:
            actions.append("로컬 생성 파일 기준 공개 글 결과가 없으므로 Blogger 공개 피드와 Actions 결과를 함께 확인하세요.")
        if any(article.get("blogger_status") == "DRAFT" for article in articles):
            actions.append("공개 발행 전 Blogger 초안 상태의 글을 확인하세요.")
        if not has_public_article:
            actions.append("공개 글이 생긴 뒤 Search Console 연결을 확인하세요.")
        if daily_success.get("skipped_duplicate_seeds"):
            actions.append(
                "최근 자동 발행에서 중복 주제가 감지되었습니다. 사용된 시드를 정리하고 launch queue 또는 Windows topic seed 목록에 새 주제를 보충하세요."
            )
        if daily_success.get("skipped_quality_seeds"):
            actions.append(
                "최근 자동 발행에서 품질검수 실패 후 다른 시드로 재시도했습니다. 실패 시드의 공식 출처, 이미지 계획, beginner-safe 섹션 구성을 보강하세요."
            )
        actions.extend(quality_issue_actions(quality_issues or []))
        reddit_health_blocks_cadence = bool(reddit_health.get("blocks_cadence_increase"))
        if not reddit_health_blocks_cadence and (signal_quality or {}).get("status") == "fallback_only":
            actions.append(
                "Reddit 실제 신호 없이 fallback 질문만 사용한 글이 있습니다. 하루 1개 자동 발행은 계속 가능하지만, "
                "승인 메일 전까지 하루 2~3개 증량은 보류하세요. 승인 후 Reddit OAuth 설정을 추가해 주제 수집 품질을 안정화합니다. "
                f"Reddit 앱: {REDDIT_APPS_URL} / GitHub Secrets: {GITHUB_SECRETS_URL} "
                f"({reddit_oauth_secret_label()})"
            )
        elif not reddit_health_blocks_cadence and (signal_quality or {}).get("reddit_public_json_signal_count", 0) and not (signal_quality or {}).get(
            "reddit_oauth_signal_count", 0
        ):
            actions.append(
                "Reddit 실제 신호가 public JSON 경로에만 의존하고 있습니다. 하루 1개 자동 발행은 계속 가능하지만, "
                "403 차단 가능성을 줄이고 발행량을 늘리려면 승인 후 Reddit OAuth 수집을 연결하세요. "
                f"Reddit 앱: {REDDIT_APPS_URL} / GitHub Secrets: {GITHUB_SECRETS_URL} "
                f"({reddit_oauth_secret_label()})"
            )
        if operational_status and not operational_status.get("ready_for_cadence_increase", False) and not reddit_health_blocks_cadence:
            actions.append(
                "일일 운영 상태 기준으로 아직 발행량 증량 준비가 아닙니다. 하루 1개를 유지하고, 품질 통과와 Reddit OAuth 수집 안정성을 모두 확인한 뒤 증량하세요."
            )
        if reddit_health_blocks_cadence:
            action_required = reddit_health.get("action_required") or "Reddit OAuth 상태를 점검하세요."
            actions.append(
                f"Reddit OAuth Health가 발행량 증량을 차단 중입니다. 하루 1개 자동 발행은 계속 가능하며, 승인 전에는 대기하세요. {action_required} "
                f"상태 점수: {reddit_health.get('health_score', 0)}/100."
            )
        actions.append("트래픽과 수익 신호가 보일 때까지 추가 유료 API 비용은 0원 정책을 유지하세요.")
        return actions

    def _to_markdown(self, report: dict) -> str:
        lines = [
            f"# 주간 자동화 보고서: {report['site_name']}",
            "",
            f"- 사이트: {report['site_url']}",
            f"- 기간: {report['week_start']} ~ {report['week_end']}",
            f"- 생성 글 수: {report['article_count']}",
            f"- 초안 글 수: {report['draft_count']}",
            f"- 공개 발행 글 수: {report['published_count']}",
            f"- 로컬 결과 기준 공개 글 수: {report.get('local_published_count', 0)}",
            f"- 상태별 산출물: {_format_article_status_counts(report.get('article_status_counts', {}))}",
            "",
            "## 글 목록",
            "",
        ]
        if report["articles"]:
            lines.append("| 제목 | 시드 | 도메인 | 카테고리 | 처리 상태 |")
            lines.append("|---|---|---|---|---|")
            for article in report["articles"]:
                lines.append(
                    f"| {article.get('title') or ''} | {article.get('seed_keyword') or ''} | "
                    f"{article.get('content_domain') or ''} | {article.get('category') or ''} | "
                    f"{_status_kr(article.get('article_status') or article.get('blogger_status'))} |"
                )
        else:
            lines.append("이번 기간에 생성된 글이 없습니다.")

        lines.extend(["", "## Blogger 공개 피드 확인", ""])
        public_posts = report.get("public_posts", {})
        lines.append(f"- 상태: {_status_kr(public_posts.get('status', 'unknown'))}")
        if public_posts.get("status") == "connected":
            posts = public_posts.get("posts", [])
            lines.append(f"- 최근 7일 공개 피드 글 수: {len(posts)}")
            if posts:
                lines.append("")
                lines.append("| 공개일(KST) | 제목 | URL |")
                lines.append("|---|---|---|")
                for post in posts:
                    lines.append(f"| {post.get('published_kst', '')} | {post.get('title', '')} | {post.get('url', '')} |")
        elif public_posts.get("error"):
            lines.append(f"- 오류: {public_posts.get('error')}")

        lines.extend(["", "## 고정 페이지", ""])
        if report["static_pages"]:
            lines.append("| 제목 | 상태 | URL |")
            lines.append("|---|---|---|")
            for page in report["static_pages"]:
                lines.append(f"| {page.get('title')} | {_status_kr(page.get('status'))} | {page.get('url')} |")
        else:
            lines.append("고정 페이지 업로드 결과가 없습니다.")

        lines.extend(["", "## 수집 신호 품질", ""])
        signal_quality = report.get("signal_quality", {})
        lines.append(f"- 상태: {_status_kr(signal_quality.get('status', 'not_uploaded'))}")
        lines.append(f"- research_report 확인 글 수: {signal_quality.get('article_count_with_research', 0)}")
        lines.append(f"- 실제 Reddit 신호 수: {signal_quality.get('live_reddit_signal_count', 0)}")
        lines.append(f"- Reddit OAuth 신호 수: {signal_quality.get('reddit_oauth_signal_count', 0)}")
        lines.append(f"- Reddit public JSON 신호 수: {signal_quality.get('reddit_public_json_signal_count', 0)}")
        lines.append(f"- Reddit fallback 신호 수: {signal_quality.get('fallback_reddit_signal_count', 0)}")
        lines.append(f"- Google Suggest 신호 수: {signal_quality.get('google_suggest_signal_count', 0)}")
        lines.append(f"- Google Suggest live 신호 수: {signal_quality.get('google_suggest_live_signal_count', 0)}")
        lines.append(f"- Google Suggest fallback 신호 수: {signal_quality.get('google_suggest_fallback_signal_count', 0)}")
        if signal_quality.get("fallback_only_articles"):
            lines.append(
                "- fallback만 사용한 글 수: "
                f"{signal_quality.get('fallback_only_article_count', len(signal_quality.get('fallback_only_articles', [])))}건 "
                f"(고유 제목 {len(signal_quality.get('fallback_only_articles', []))}개)"
            )
            lines.append("- fallback만 사용한 글:")
            for title in signal_quality.get("fallback_only_articles", [])[:5]:
                lines.append(f"  - {title}")
        if signal_quality.get("reddit_collection_diagnostics"):
            lines.append("- 최근 Reddit 수집 진단:")
            for item in signal_quality.get("reddit_collection_diagnostics", [])[:5]:
                lines.append(
                    f"  - {item.get('title', '')}: {_status_kr(item.get('status'))}, "
                    f"public JSON 실패 {item.get('public_json_error_count', 0)}개"
                )
                if item.get("failed_subreddits"):
                    lines.append(f"    - 실패 subreddit: {', '.join(item.get('failed_subreddits', [])[:5])}")
                if item.get("fallback_reason"):
                    lines.append(f"    - fallback 이유: {item.get('fallback_reason')}")
                if item.get("oauth_error"):
                    lines.append(f"    - OAuth 오류: {item.get('oauth_error')}")
        if signal_quality.get("google_suggest_diagnostics"):
            lines.append("- 최근 Google Suggest 수집 진단:")
            for item in signal_quality.get("google_suggest_diagnostics", [])[:5]:
                lines.append(
                    f"  - {item.get('title', '')}: {_status_kr(item.get('status'))}, "
                    f"live {item.get('live_suggestion_count', 0)}개, fallback {item.get('fallback_suggestion_count', 0)}개"
                )
                if item.get("fallback_reason"):
                    lines.append(f"    - fallback 이유: {item.get('fallback_reason')}")
                if item.get("error"):
                    lines.append(f"    - 오류: {item.get('error')}")

        lines.extend(["", "## Search Console", ""])
        search_console = report.get("search_console", {})
        lines.append(f"- 상태: {_status_kr(search_console.get('status', 'unknown'))}")
        if search_console.get("status") == "connected":
            totals = search_console.get("totals_from_top_queries", {})
            lines.append(f"- 상위 검색어 클릭 수: {totals.get('clicks', 0)}")
            lines.append(f"- 상위 검색어 노출 수: {totals.get('impressions', 0)}")
            lines.append("")
            lines.append("| 검색어 | 클릭 | 노출 | 평균 순위 |")
            lines.append("|---|---:|---:|---:|")
            for row in search_console.get("top_queries", []):
                lines.append(
                    f"| {row.get('query', '')} | {row.get('clicks', 0)} | {row.get('impressions', 0)} | {row.get('position', 0):.1f} |"
                )
        elif search_console.get("note"):
            lines.append(f"- 참고: {search_console.get('note')}")
        elif search_console.get("error"):
            lines.append(f"- 오류: {search_console.get('error')}")

        lines.extend(["", "## Analytics", ""])
        analytics = report.get("analytics", {})
        lines.append(f"- 상태: {_status_kr(analytics.get('status', 'unknown'))}")
        if analytics.get("status") == "connected":
            lines.append("| 페이지 | 조회수 | 활성 사용자 | 참여율 |")
            lines.append("|---|---:|---:|---:|")
            for row in analytics.get("top_pages", []):
                lines.append(
                    f"| {row.get('page_path', '')} | {row.get('views', 0)} | {row.get('active_users', 0)} | {row.get('engagement_rate', 0):.2f} |"
                )
        elif analytics.get("note"):
            lines.append(f"- 참고: {analytics.get('note')}")
        elif analytics.get("error"):
            lines.append(f"- 오류: {analytics.get('error')}")

        lines.extend(["", "## 운영 점검", ""])
        operations = report.get("operations", {})
        daily_success = operations.get("daily_success", {})
        daily_success_context = operations.get("daily_success_context") or classify_daily_success_context(daily_success)
        daily_seed_plan = operations.get("daily_seed_plan", {})
        daily_failure = operations.get("daily_failure", {})
        preflight = operations.get("preflight", {})
        reddit_health = operations.get("reddit_health", {})
        publication_check = operations.get("publication_check", {})
        sitemap_submit = operations.get("sitemap_submit", {})
        lines.append(f"- 최근 일일 성공 리포트: {_status_kr(daily_success.get('status', 'not_uploaded'))}")
        if daily_success_context.get("status") != "not_uploaded":
            lines.append(f"  - 리포트 구분: {daily_success_context.get('label')}")
            if daily_success_context.get("note"):
                lines.append(f"  - 참고: {daily_success_context.get('note')}")
        if daily_success.get("title"):
            lines.append(f"  - 제목: {daily_success.get('title', '')}")
        if daily_success.get("url"):
            lines.append(f"  - URL: {daily_success.get('url', '')}")
        if daily_success.get("quality_score") is not None:
            lines.append(f"  - 품질점수: {daily_success.get('quality_score')}/100")
        seed_attempt_summary = daily_success.get("seed_attempt_summary") or {}
        if seed_attempt_summary:
            lines.append(f"  - 시드 시도 수: {seed_attempt_summary.get('attempted_seed_count', 0)}")
            if seed_attempt_summary.get("selected_seed"):
                lines.append(f"  - 최종 선택 시드: {seed_attempt_summary.get('selected_seed')}")
            lines.append(f"  - 중복 스킵 수: {seed_attempt_summary.get('duplicate_skip_count', 0)}")
            lines.append(f"  - 품질 재시도 수: {seed_attempt_summary.get('quality_retry_count', 0)}")
        skipped_duplicate_seeds = daily_success.get("skipped_duplicate_seeds") or []
        if skipped_duplicate_seeds:
            lines.append(f"  - 중복으로 건너뛴 시드 수: {len(skipped_duplicate_seeds)}")
            lines.append(f"  - 중복 시드: {', '.join(skipped_duplicate_seeds[:5])}")
        skipped_quality_seeds = daily_success.get("skipped_quality_seeds") or []
        if skipped_quality_seeds:
            lines.append(f"  - 품질검수 실패로 재시도한 시드 수: {len(skipped_quality_seeds)}")
            lines.append(f"  - 품질 재시도 시드: {', '.join(skipped_quality_seeds[:5])}")
        operational_status = daily_success.get("operational_status") or {}
        if operational_status:
            lines.append(f"  - 운영 상태: {operational_status.get('status_label', '확인 필요')}")
            lines.append(
                "  - 발행 품질 안정성: "
                f"{'안정' if operational_status.get('publish_quality_ok') else '점검 필요'}"
            )
            lines.append(f"  - 수집 안정성: {operational_status.get('collection_status_label', '확인 필요')}")
            lines.append(
                "  - 발행량 증량 준비: "
                f"{'예' if operational_status.get('ready_for_cadence_increase') else '아니오'}"
            )
        lines.append(f"- 일일 시드 계획: {_status_kr(daily_seed_plan.get('status', daily_seed_plan.get('mode', 'not_uploaded')))}")
        if daily_seed_plan.get("previous_today_kst"):
            lines.append(f"  - 이전 계획 기준일: {daily_seed_plan.get('previous_today_kst')}")
        if daily_seed_plan.get("today_kst"):
            lines.append(f"  - 계획 기준일: {daily_seed_plan.get('today_kst')} KST")
        if daily_seed_plan.get("active_seed_source"):
            lines.append(f"  - 시드 소스: {daily_seed_plan.get('active_seed_source')}")
        if daily_seed_plan.get("date_selected_seed"):
            lines.append(f"  - 날짜 기준 시드: {daily_seed_plan.get('date_selected_seed')}")
            lines.append(
                f"  - 날짜 기준 시드 상태: {_seed_plan_status_kr(daily_seed_plan.get('date_selected_seed_status'))}"
            )
        if daily_seed_plan.get("next_publishable_seed") is not None:
            lines.append(f"  - 다음 발행 가능 시드: {daily_seed_plan.get('next_publishable_seed') or '없음'}")
            lines.append(
                f"  - 다음 발행 가능 시드 상태: {_seed_plan_status_kr(daily_seed_plan.get('next_publishable_seed_status'))}"
            )
        if daily_seed_plan.get("candidate_status_counts"):
            lines.append(
                "  - 후보 상태 집계: "
                f"{_format_seed_plan_status_counts_kr(daily_seed_plan.get('candidate_status_counts') or {})}"
            )
        lines.extend(_seed_plan_source_quality_lines(daily_seed_plan))
        if daily_seed_plan.get("unused_active_seed_count") is not None:
            lines.append(f"  - 미사용 활성 시드 수: {daily_seed_plan.get('unused_active_seed_count')}")
        if daily_seed_plan.get("note"):
            lines.append(f"  - 참고: {daily_seed_plan.get('note')}")
        lines.append(f"- 최근 일일 실패 리포트: {_status_kr(daily_failure.get('status', 'not_uploaded'))}")
        if daily_failure.get("note"):
            lines.append(f"  - 참고: {daily_failure.get('note')}")
        if daily_failure.get("previous_created_at"):
            lines.append(f"  - 이전 실패 시각: {daily_failure.get('previous_created_at')}")
        if daily_failure.get("error"):
            lines.append(f"  - 오류: {daily_failure.get('error')}")
        if daily_failure.get("seed"):
            lines.append(f"  - 실패 시드: {daily_failure.get('seed')}")
        lines.append(f"- Preflight: {_status_kr(preflight.get('status', 'not_uploaded'))}")
        readiness = preflight.get("readiness") or {}
        if readiness:
            lines.append(
                "  - 무인 발행 준비: "
                f"{'예' if readiness.get('ready_for_unattended_publish') else '아니오'}"
            )
            lines.append(
                "  - 발행량 증량 준비: "
                f"{'예' if readiness.get('ready_for_cadence_increase') else '아니오'}"
            )
            lines.append(f"  - 필요 사용자 조치 수: {readiness.get('required_user_action_count', 0)}")
        if preflight.get("setup_actions"):
            lines.append("  - 설정 조치:")
            for action in preflight.get("setup_actions", [])[:5]:
                lines.append(
                    f"    - {action.get('label', action.get('name', '설정'))}: {_status_kr(action.get('status'))} "
                    f"/ {action.get('urgency', 'review')} - {action.get('next_step', action.get('message', '확인 필요'))}"
                )
        if preflight.get("checks"):
            seed_inventory = next((check for check in preflight.get("checks", []) if check.get("name") == "seed_inventory"), None)
            if seed_inventory:
                lines.append(
                    f"  - 시드 재고: {_status_kr(seed_inventory.get('status'))} - {seed_inventory.get('message')}"
                )
            all_seed_quality = next((check for check in preflight.get("checks", []) if check.get("name") == "all_seed_quality"), None)
            if all_seed_quality:
                lines.append(
                    f"  - 장기 시드 품질: {_status_kr(all_seed_quality.get('status'))} - {all_seed_quality.get('message')}"
                )
            launch_queue_quality = next((check for check in preflight.get("checks", []) if check.get("name") == "launch_queue_quality"), None)
            if launch_queue_quality:
                lines.append(
                    f"  - Launch queue 품질: {_status_kr(launch_queue_quality.get('status'))} - {launch_queue_quality.get('message')}"
                )
            failed_or_warned = [check for check in preflight.get("checks", []) if check.get("status") != "pass"]
            if failed_or_warned:
                for check in failed_or_warned:
                    if check.get("name") in {"seed_inventory", "all_seed_quality", "launch_queue_quality"}:
                        continue
                    lines.append(f"  - {check.get('name')}: {_status_kr(check.get('status'))} - {check.get('message')}")
            else:
                lines.append("  - 전체 점검 통과")
        lines.append(f"- Reddit OAuth Health: {_status_kr(reddit_health.get('status', 'not_uploaded'))}")
        if reddit_health.get("status_label"):
            lines.append(f"  - 상태: {reddit_health.get('status_label')}")
        if reddit_health.get("previous_checked_at"):
            lines.append(f"  - 이전 점검 시각: {reddit_health.get('previous_checked_at')}")
        if reddit_health.get("health_score") is not None:
            lines.append(f"  - 상태 점수: {reddit_health.get('health_score')}/100")
        if reddit_health.get("blocks_cadence_increase") is not None:
            lines.append(
                "  - 발행량 증량 차단: "
                f"{'예' if reddit_health.get('blocks_cadence_increase') else '아니오'}"
            )
        if reddit_health.get("action_required"):
            lines.append(f"  - 조치: {reddit_health.get('action_required')}")
        if reddit_health.get("query_attempt_count") is not None:
            lines.append(f"  - 검색어 재시도 수: {reddit_health.get('query_attempt_count', 0)}")
        if reddit_health.get("query_attempts"):
            lines.append("  - 검색어 재시도 기록:")
            for attempt in reddit_health.get("query_attempts", [])[:5]:
                lines.append(
                    f"    - {attempt.get('query', '')}: {_status_kr(attempt.get('status'))} "
                    f"/ OAuth 신호 {attempt.get('oauth_signal_count', 0)}개"
                )
        if reddit_health.get("per_subreddit_counts"):
            subreddit_counts = ", ".join(
                f"{subreddit} {count}개" for subreddit, count in reddit_health.get("per_subreddit_counts", {}).items()
            )
            lines.append(f"  - subreddit별 결과: {subreddit_counts}")
        setup_links = reddit_health.get("setup_links") or {}
        if setup_links and reddit_health.get("blocks_cadence_increase"):
            lines.append(f"  - Reddit 앱 타입: {setup_links.get('recommended_app_type', 'script')}")
            if setup_links.get("recommended_redirect_uri"):
                lines.append(f"  - Redirect URI: {setup_links.get('recommended_redirect_uri')}")
            if setup_links.get("github_secret_mapping"):
                lines.append("  - GitHub 입력값:")
                for item in setup_links.get("github_secret_mapping", [])[:3]:
                    lines.append(f"    - {item}")
            if setup_links.get("user_action_checklist"):
                lines.append("  - 사용자가 직접 할 일:")
                for item in setup_links.get("user_action_checklist", []):
                    lines.append(f"    - {item}")
        lines.append(f"- 발행 확인: {_status_kr(publication_check.get('status', 'not_uploaded'))}")
        if publication_check.get("source"):
            lines.append(f"  - 확인 기준: {publication_check.get('source')}")
        if publication_check.get("note"):
            lines.append(f"  - 참고: {publication_check.get('note')}")
        publication_summary = _publication_check_summary(publication_check)
        if publication_summary:
            lines.append(f"  - 발행 확인 요약: {publication_summary}")
        if publication_check.get("today_post_count") is not None:
            lines.append(f"  - 기준 이후 공개 글 수: {publication_check.get('today_post_count', 0)}")
        if publication_check.get("today_total_post_count") is not None:
            lines.append(f"  - 오늘 전체 공개 글 수: {publication_check.get('today_total_post_count', 0)}")
        evidence = publication_check.get("publication_evidence") or {}
        if evidence:
            lines.append(f"  - 발행 증거 판정: {evidence.get('label', '확인 필요')}")
            if evidence.get("note"):
                lines.append(f"  - 판정 참고: {evidence.get('note')}")
            if evidence.get("needs_attention") is not None:
                lines.append(f"  - 추가 확인 필요: {'예' if evidence.get('needs_attention') else '아니오'}")
        if publication_check.get("action_items"):
            lines.append("  - 발행 확인 조치:")
            for item in publication_check.get("action_items", [])[:5]:
                lines.append(f"    - {item}")
        if publication_check.get("latest_posts"):
            latest = publication_check["latest_posts"][0]
            lines.append(f"  - 최근 글: {latest.get('title', '')}")
            if latest.get("url"):
                lines.append(f"  - 최근 글 URL: {latest.get('url')}")
        lines.append(f"- Sitemap 제출: {_status_kr(sitemap_submit.get('status', 'not_uploaded'))}")
        if sitemap_submit.get("note"):
            lines.append(f"  - 참고: {sitemap_submit.get('note')}")
        if sitemap_submit.get("sitemap_url"):
            lines.append(f"  - {sitemap_submit.get('sitemap_url')}")
        indexing_guidance = sitemap_submit.get("indexing_guidance") or {}
        if indexing_guidance:
            if indexing_guidance.get("meaning"):
                lines.append(f"  - 색인 의미: {indexing_guidance.get('meaning')}")
            lines.append(f"  - 색인 안내: {indexing_guidance.get('summary', '확인 필요')}")
            if indexing_guidance.get("expected_wait"):
                lines.append(f"  - 예상 대기: {indexing_guidance.get('expected_wait')}")
            if indexing_guidance.get("first_signal_check"):
                lines.append(f"  - 첫 신호 확인: {indexing_guidance.get('first_signal_check')}")
            if indexing_guidance.get("check_location"):
                lines.append(f"  - 확인 위치: {indexing_guidance.get('check_location')}")
            if indexing_guidance.get("url_inspection_target"):
                lines.append(f"  - URL 검사 대상: {indexing_guidance.get('url_inspection_target')}")
        if sitemap_submit.get("error"):
            lines.append(f"  - 오류: {sitemap_submit.get('error')}")

        lines.extend(["", "## 발행량 전환 검토", ""])
        cadence = report.get("cadence_review", {})
        lines.append(f"- 권장 조치: {cadence.get('action', '확인 필요')}")
        lines.append(f"- 운영 일수: {cadence.get('days_since_start', 0)}일")
        lines.append(f"- 공개 글 수: {cadence.get('published_posts', 0)}개")
        lines.append(f"- Search Console 색인/노출 페이지 추정: {cadence.get('indexed_pages_estimate', 0)}개")
        lines.append(f"- 최근 노출 수: {cadence.get('recent_impressions', 0)}")
        lines.append(f"- 품질 이슈 수: {cadence.get('quality_issue_count', 0)}")
        lines.append(f"- 수집 신호 상태: {_status_kr(cadence.get('signal_quality_status', 'not_uploaded'))}")
        lines.append(f"- Reddit OAuth 신호 수: {cadence.get('reddit_oauth_signal_count', 0)}")
        lines.append(f"- Reddit public JSON 신호 수: {cadence.get('reddit_public_json_signal_count', 0)}")
        lines.append(f"- Reddit fallback 신호 수: {cadence.get('fallback_reddit_signal_count', 0)}")
        lines.append(f"- Reddit Health 상태: {_status_kr(cadence.get('reddit_health_status', 'not_uploaded'))}")
        lines.append(f"- Reddit Health 점수: {cadence.get('reddit_health_score', 0)}/100")
        lines.append(
            "- Reddit Health 증량 차단: "
            f"{'예' if cadence.get('reddit_health_blocks_cadence_increase') else '아니오'}"
        )
        lines.append(f"- 하루 2개 검토 기준일: {cadence.get('two_post_review_date')}")
        lines.append(f"- 하루 3개 검토 기준일: {cadence.get('three_post_review_date')}")
        for reason in cadence.get("reasons", []):
            lines.append(f"- 판단 근거: {reason}")
        quality_issues = report.get("quality_issues", [])
        if quality_issues:
            lines.append("- 품질 이슈 상세:")
            for issue in quality_issues[:5]:
                lines.append(
                    f"  - {issue.get('title', '')}: {issue.get('code', 'unknown')} - {issue.get('message', '')}"
                )

        lines.extend(["", "## 2~3주 모니터링", ""])
        monitoring_items = monitoring_review_items(report)
        lines.append(f"- 운영 시작 기준일: {MONITORING_START_DATE.isoformat()}")
        lines.append(f"- 2주 점검일: {TWO_WEEK_MONITORING_DATE.isoformat()}")
        lines.append(f"- 3주 점검일: {THREE_WEEK_MONITORING_DATE.isoformat()}")
        for item in monitoring_items:
            lines.append(
                f"- {item['label']}: {item['status_label']} / 목표 {item['target_date']} "
                f"/ 조치: {item['action']}"
            )
        lines.append("- 확인 항목: 공개 발행 누락, 품질점수, Search Console 색인/노출, Reddit OAuth Health, 중복/품질 재시도 수")

        lines.extend(["", "## 다음 할 일", ""])
        for action in report["next_actions"]:
            lines.append(f"- {action}")
        lines.append("")
        return "\n".join(lines)


def monitoring_review_items(report: dict) -> list[dict]:
    today = _parse_report_date(report)
    operations = report.get("operations", {})
    daily_success = operations.get("daily_success", {})
    reddit_health = operations.get("reddit_health", {})
    publication_check = operations.get("publication_check", {})
    quality_issues = report.get("quality_issues", [])
    indexed_pages = report.get("indexed_pages", {})
    search_console = report.get("search_console", {})
    common = {
        "published_count": report.get("published_count", 0),
        "quality_issue_count": len(quality_issues),
        "reddit_health_status": reddit_health.get("status", "not_uploaded"),
        "publication_status": publication_check.get("status", "not_uploaded"),
        "indexed_page_count": indexed_pages.get("page_count_with_search_data", 0),
        "recent_impressions": search_console.get("totals_from_top_queries", {}).get("impressions", 0),
        "seed_attempt_count": (daily_success.get("seed_attempt_summary") or {}).get("attempted_seed_count", 0),
    }
    return [
        _monitoring_item(
            label="2주차 안정성 점검",
            target_date=TWO_WEEK_MONITORING_DATE,
            today=today,
            common=common,
            action=(
                "하루 1개 발행이 누락 없이 유지되는지 확인하고, Reddit OAuth 키/색인/품질 이슈가 있으면 먼저 복구"
            ),
        ),
        _monitoring_item(
            label="3주차 증량 사전 점검",
            target_date=THREE_WEEK_MONITORING_DATE,
            today=today,
            common=common,
            action=(
                "색인/노출과 품질검수 안정성을 확인한 뒤 7/22 하루 2개 전환 알림을 받을 준비"
            ),
        ),
    ]


def article_status_summary(articles: list[dict]) -> dict[str, int]:
    counts = Counter()
    for article in articles:
        status = article.get("article_status") or article.get("blogger_status") or "unknown"
        counts[str(status)] += 1
    preferred_order = ["LIVE", "DRAFT", "validated", "failed", "not_uploaded", "unknown"]
    ordered = {status: counts[status] for status in preferred_order if counts.get(status)}
    for status, count in sorted(counts.items()):
        if status not in ordered:
            ordered[status] = count
    return ordered


def _seed_plan_source_quality_lines(daily_seed_plan: dict) -> list[str]:
    candidate_preview = daily_seed_plan.get("candidate_preview") or []
    prechecks = [
        item.get("quality_precheck") or {}
        for item in candidate_preview
        if isinstance(item.get("quality_precheck"), dict)
    ]
    if not candidate_preview or not prechecks:
        return []

    ready_count = sum(1 for item in candidate_preview if (item.get("quality_precheck") or {}).get("status") == "ready")
    direct_counts = [_safe_int(precheck.get("direct_microsoft_source_count")) for precheck in prechecks]
    search_counts = [_safe_int(precheck.get("search_result_source_count")) for precheck in prechecks]
    lines = [
        "  - 후보 소스 품질: "
        f"발행 가능 {ready_count}/{len(candidate_preview)}개, "
        f"직접 Microsoft 최소 {min(direct_counts)}개, 검색 결과 최대 {max(search_counts)}개"
    ]

    next_seed = daily_seed_plan.get("next_publishable_seed") or daily_seed_plan.get("selected_seed")
    next_candidate = next((item for item in candidate_preview if item.get("seed") == next_seed), None)
    if next_candidate:
        precheck = next_candidate.get("quality_precheck") or {}
        lines.append(
            "  - 다음 시드 출처: "
            f"MS {_safe_int(precheck.get('microsoft_source_count'))}/"
            f"직접 {_safe_int(precheck.get('direct_microsoft_source_count'))}/"
            f"검색 {_safe_int(precheck.get('search_result_source_count'))}"
        )

    warning_candidates = [
        item for item in candidate_preview if (item.get("quality_precheck") or {}).get("status") == "warn"
    ]
    if warning_candidates:
        lines.append(f"  - 소스 점검 후보 수: {len(warning_candidates)}")
        for item in warning_candidates[:3]:
            precheck = item.get("quality_precheck") or {}
            issues = ", ".join(precheck.get("issues") or [])
            lines.append(f"    - {item.get('seed', 'unknown')}: {issues or '확인 필요'}")
    return lines


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_article_status_counts(counts: dict) -> str:
    if not counts:
        return "없음"
    return ", ".join(f"{_status_kr(str(status))} {count}개" for status, count in counts.items())


def _publication_check_summary(publication_check: dict) -> str:
    summary = str(publication_check.get("human_summary") or "").strip()
    if not summary:
        return ""
    for line in summary.splitlines():
        normalized = line.strip()
        if not normalized or normalized.startswith("[Posting Bot]"):
            continue
        if normalized.startswith("- 상태:") or normalized.startswith("- 발행 증거 판정:"):
            return normalized.removeprefix("- ").strip()
    return ""


def _monitoring_item(label: str, target_date, today, common: dict, action: str) -> dict:
    if today < target_date:
        status_label = "예정"
    elif common["quality_issue_count"] or common["reddit_health_status"] in {
        "missing_credentials",
        "approval_pending",
        "missing_user_agent",
        "reddit_health_missing",
        "stale_reddit_health",
        "oauth_error",
    }:
        status_label = "점검 필요"
    elif common["publication_status"] in {"missing_today", "error", "not_uploaded"}:
        status_label = "발행 확인 필요"
    else:
        status_label = "점검일 도달"
    return {
        "label": label,
        "target_date": target_date.isoformat(),
        "status_label": status_label,
        "action": action,
        **common,
    }


def _parse_report_date(report: dict):
    try:
        return datetime.fromisoformat(str(report.get("week_end"))).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(report.get("generated_at"))).astimezone(KST).date()
        except ValueError:
            return datetime.now(tz=KST).date()


def _status_kr(status: str | None) -> str:
    mapping = {
        "LIVE": "공개",
        "DRAFT": "초안",
        "connected": "연결됨",
        "not_configured": "미설정",
        "not_uploaded": "미업로드",
        "not_persisted": "이전 실행 파일 미보존",
        "error": "오류",
        "submitted": "제출됨",
        "pass": "통과",
        "warn": "주의",
        "fail": "실패",
        "published_today": "오늘 공개 글 확인",
        "published_today_before_cutoff": "오늘 공개 글 확인(기준 전 발행)",
        "pending_today_before_cutoff": "발행 확인 기준 전",
        "duplicate_today": "오늘 공개 글 2개 이상",
        "missing_today": "오늘 공개 글 없음",
        "partial_failure": "일부 실행 실패",
        "validated": "검증 완료",
        "draft_uploaded": "초안 업로드",
        "published": "공개 발행",
        "skipped_duplicate": "중복 건너뜀",
        "skipped_daily_limit": "하루 1개 제한으로 건너뜀",
        "fallback_only": "fallback 사용",
        "live_connected": "live 연결",
        "no_google_suggestions": "Google Suggest 신호 없음",
        "public_json_connected": "public JSON 연결",
        "no_reddit_signals": "Reddit 신호 없음",
        "failed": "실패",
        "stale_failure": "이전 실패 리포트",
        "oauth_connected": "OAuth 연결 확인",
        "oauth_connected_no_results": "OAuth 연결됨, 결과 없음",
        "missing_credentials": "Reddit OAuth 키 없음",
        "approval_pending": "Reddit 승인 대기",
        "missing_user_agent": "Reddit User-Agent 없음",
        "missing_praw": "PRAW 패키지 없음",
        "oauth_error": "OAuth 오류",
        "reddit_health_missing": "Reddit Health 리포트 없음",
        "stale_reddit_health": "이전 Reddit Health 리포트",
        "plan": "계획 완료",
        "planned": "계획 완료",
        "stale_seed_plan": "이전 시드 계획",
    }
    return mapping.get(status or "not_uploaded", status or "미업로드")


def _seed_plan_status_kr(status: str | None) -> str:
    mapping = {
        "ready": "발행 가능",
        "already_generated_or_validated": "생성/검증 이력 있음",
        "already_published_or_duplicate": "공개/중복 이력 있음",
        "quality_precheck_warning": "품질 사전점검 필요",
        "not_available": "후보 없음",
    }
    return mapping.get(status or "", status or "확인 필요")


def _format_seed_plan_status_counts_kr(counts: dict) -> str:
    if not counts:
        return "없음"
    return ", ".join(f"{_seed_plan_status_kr(str(status))} {count}개" for status, count in counts.items())


def _article_validation_status(validation: dict) -> str:
    if validation.get("mode") == "validate" and validation.get("passed") is True:
        return "validated"
    if validation.get("mode") == "validate" and validation.get("passed") is False:
        return "failed"
    return "not_uploaded"


def _quality_report_is_actionable(article: dict, resolved_seed_keywords: set[str] | None = None) -> bool:
    if article.get("blogger_status") in {"LIVE", "DRAFT"}:
        return True
    article_status = article.get("article_status")
    if article_status == "validated":
        return True
    if article_status == "failed":
        seed_keyword = str(article.get("seed_keyword") or "").casefold()
        return not seed_keyword or seed_keyword not in (resolved_seed_keywords or set())
    return False


def _resolved_seed_keywords(articles: list[dict]) -> set[str]:
    resolved = set()
    for article in articles:
        seed_keyword = str(article.get("seed_keyword") or "").casefold()
        if not seed_keyword:
            continue
        if article.get("blogger_status") in {"LIVE", "DRAFT"} or article.get("article_status") == "validated":
            resolved.add(seed_keyword)
            continue
        quality_path = Path(article.get("article_dir", "")) / "quality_report.json"
        if not quality_path.exists():
            continue
        try:
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if quality_report.get("passed") is True:
            resolved.add(seed_keyword)
    return resolved


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
