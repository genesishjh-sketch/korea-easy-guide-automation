from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR, Settings
from src.pipeline.stage4_publication_check import classify_daily_success_context
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.reporting.cadence import review_cadence
from src.reporting.analytics import GA4Client
from src.reporting.search_console import SearchConsoleClient
from src.utils.reddit_setup import GITHUB_SECRETS_URL
from src.utils.reddit_setup import REDDIT_APPS_URL
from src.utils.reddit_setup import reddit_oauth_secret_label


KST = ZoneInfo("Asia/Seoul")


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
        local_published_count = sum(1 for item in articles if item.get("blogger_status") == "LIVE")
        published_count = max(local_published_count, len(public_posts.get("posts", [])))
        cadence_review = review_cadence(
            today=now.date(),
            published_posts=published_count,
            indexed_pages_estimate=indexed_pages.get("page_count_with_search_data", 0),
            recent_impressions=search_console.get("totals_from_top_queries", {}).get("impressions", 0),
            quality_issue_count=self._quality_issue_count(articles),
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
            "articles": articles,
            "public_posts": public_posts,
            "static_pages": static_pages,
            "signal_quality": signal_quality,
            "search_console": search_console,
            "indexed_pages": indexed_pages,
            "analytics": GA4Client(self.settings).summary(week_start.date(), now.date()),
            "operations": operations,
            "cadence_review": cadence_review.to_dict(),
            "quality_issues": self._quality_issues_result(articles),
            "next_actions": self._next_actions(articles, static_pages, public_posts, operations, signal_quality),
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
            publish_result_path = article_dir / "blogger_publish_result.json"
            update_result_path = article_dir / "blogger_update_result.json"
            blogger = self._best_blogger_result([publish_result_path, update_result_path])
            articles.append(
                {
                    "title": article.get("title"),
                    "slug": article.get("slug"),
                    "category": article.get("category"),
                    "tags": article.get("tags", []),
                    "article_dir": str(article_dir),
                    "blogger_id": blogger.get("id"),
                    "blogger_status": blogger.get("status"),
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
        publication_check = self._read_report(report_dir / f"{self.settings.site_key}-publication-check.json")
        if publication_check.get("status") == "not_uploaded" and now is not None and public_posts is not None:
            publication_check = self._publication_check_from_public_posts(now, public_posts)
        sitemap_submit = self._read_report(report_dir / f"{self.settings.site_key}-search-console-sitemap-submit.json")
        if sitemap_submit.get("status") == "not_uploaded" and (public_posts or search_console):
            sitemap_submit = {
                "status": "not_persisted",
                "note": "이전 workflow artifact는 주간 workflow 환경에 자동 보존되지 않습니다. Daily publish workflow는 공개 발행 직후 sitemap 제출 단계를 실행합니다.",
            }
        daily_success = self._read_report(report_dir / f"{self.settings.site_key}-daily-success.json")
        return {
            "daily_success": daily_success,
            "daily_success_context": classify_daily_success_context(daily_success),
            "daily_failure": self._read_report(report_dir / f"{self.settings.site_key}-daily-failure.json"),
            "preflight": self._read_report(report_dir / f"{self.settings.site_key}-preflight.json"),
            "reddit_health": self._read_report(report_dir / f"{self.settings.site_key}-reddit-health.json"),
            "publication_check": publication_check,
            "sitemap_submit": sitemap_submit,
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
        status = "published_today" if todays_posts else "published_today_before_cutoff" if all_todays_posts else "missing_today"
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
        for article in articles:
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
        for article in articles:
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
        }
        source_counts: dict[str, int] = {}
        reddit_method_counts: dict[str, int] = {}
        fallback_articles: list[str] = []
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
            ]:
                totals[key] += int(report.get(key, 0) or 0)
            for source, count in report.get("signal_source_counts", {}).items():
                source_counts[source] = source_counts.get(source, 0) + int(count or 0)
            for method, count in report.get("reddit_collection_method_counts", {}).items():
                reddit_method_counts[method] = reddit_method_counts.get(method, 0) + int(count or 0)
            if int(report.get("fallback_reddit_signal_count", 0) or 0) and not int(
                report.get("live_reddit_signal_count", 0) or 0
            ):
                fallback_articles.append(article.get("title") or article.get("slug") or article.get("article_dir", ""))

        status = "not_uploaded"
        if totals["article_count_with_research"]:
            status = "fallback_only" if fallback_articles else "connected"
        return {
            "status": status,
            **totals,
            "signal_source_counts": dict(sorted(source_counts.items())),
            "reddit_collection_method_counts": dict(sorted(reddit_method_counts.items())),
            "fallback_only_articles": fallback_articles,
        }

    def _next_actions(
        self,
        articles: list[dict],
        static_pages: list[dict],
        public_posts: dict | None = None,
        operations: dict | None = None,
        signal_quality: dict | None = None,
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
        operational_status = operations.get("daily_success", {}).get("operational_status", {})
        reddit_health = operations.get("reddit_health", {})
        if preflight_status == "fail":
            actions.append("Preflight 실패 항목을 먼저 복구하세요. 설정, workflow 안전장치, 알림 설정을 확인해야 합니다.")
        elif preflight_status == "warn":
            actions.append("Preflight 주의 항목을 확인하세요. 자동화는 계속되지만 운영 리스크가 있습니다.")
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
        if (signal_quality or {}).get("status") == "fallback_only":
            actions.append(
                "Reddit 실제 신호 없이 fallback 질문만 사용한 글이 있습니다. Reddit OAuth 설정을 추가해 주제 수집 품질을 안정화하세요. "
                f"Reddit 앱: {REDDIT_APPS_URL} / GitHub Secrets: {GITHUB_SECRETS_URL} "
                f"({reddit_oauth_secret_label()})"
            )
        elif (signal_quality or {}).get("reddit_public_json_signal_count", 0) and not (signal_quality or {}).get(
            "reddit_oauth_signal_count", 0
        ):
            actions.append(
                "Reddit 실제 신호가 public JSON 경로에만 의존하고 있습니다. 403 차단 가능성을 줄이려면 Reddit OAuth 수집을 점검하세요. "
                f"Reddit 앱: {REDDIT_APPS_URL} / GitHub Secrets: {GITHUB_SECRETS_URL} "
                f"({reddit_oauth_secret_label()})"
            )
        if operational_status and not operational_status.get("ready_for_cadence_increase", False):
            actions.append(
                "일일 운영 상태 기준으로 아직 발행량 증량 준비가 아닙니다. 품질 통과와 Reddit OAuth 수집 안정성을 모두 확인한 뒤 증량하세요."
            )
        if reddit_health.get("blocks_cadence_increase"):
            action_required = reddit_health.get("action_required") or "Reddit OAuth 상태를 점검하세요."
            actions.append(
                f"Reddit OAuth Health가 발행량 증량을 차단 중입니다. {action_required} "
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
            "",
            "## 글 목록",
            "",
        ]
        if report["articles"]:
            lines.append("| 제목 | 카테고리 | Blogger 상태 |")
            lines.append("|---|---|---|")
            for article in report["articles"]:
                lines.append(
                    f"| {article.get('title') or ''} | {article.get('category') or ''} | {_status_kr(article.get('blogger_status'))} |"
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
        if signal_quality.get("fallback_only_articles"):
            lines.append("- fallback만 사용한 글:")
            for title in signal_quality.get("fallback_only_articles", [])[:5]:
                lines.append(f"  - {title}")

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
        lines.append(f"- 최근 일일 실패 리포트: {_status_kr(daily_failure.get('status', 'not_uploaded'))}")
        if daily_failure.get("error"):
            lines.append(f"  - 오류: {daily_failure.get('error')}")
        if daily_failure.get("seed"):
            lines.append(f"  - 실패 시드: {daily_failure.get('seed')}")
        lines.append(f"- Preflight: {_status_kr(preflight.get('status', 'not_uploaded'))}")
        if preflight.get("checks"):
            seed_inventory = next((check for check in preflight.get("checks", []) if check.get("name") == "seed_inventory"), None)
            if seed_inventory:
                lines.append(
                    f"  - 시드 재고: {_status_kr(seed_inventory.get('status'))} - {seed_inventory.get('message')}"
                )
            failed_or_warned = [check for check in preflight.get("checks", []) if check.get("status") != "pass"]
            if failed_or_warned:
                for check in failed_or_warned:
                    if check.get("name") == "seed_inventory":
                        continue
                    lines.append(f"  - {check.get('name')}: {_status_kr(check.get('status'))} - {check.get('message')}")
            else:
                lines.append("  - 전체 점검 통과")
        lines.append(f"- Reddit OAuth Health: {_status_kr(reddit_health.get('status', 'not_uploaded'))}")
        if reddit_health.get("status_label"):
            lines.append(f"  - 상태: {reddit_health.get('status_label')}")
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
        lines.append(f"- 발행 확인: {_status_kr(publication_check.get('status', 'not_uploaded'))}")
        if publication_check.get("source"):
            lines.append(f"  - 확인 기준: {publication_check.get('source')}")
        if publication_check.get("note"):
            lines.append(f"  - 참고: {publication_check.get('note')}")
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
        if publication_check.get("latest_posts"):
            latest = publication_check["latest_posts"][0]
            lines.append(f"  - 최근 글: {latest.get('title', '')}")
        lines.append(f"- Sitemap 제출: {_status_kr(sitemap_submit.get('status', 'not_uploaded'))}")
        if sitemap_submit.get("note"):
            lines.append(f"  - 참고: {sitemap_submit.get('note')}")
        if sitemap_submit.get("sitemap_url"):
            lines.append(f"  - {sitemap_submit.get('sitemap_url')}")
        indexing_guidance = sitemap_submit.get("indexing_guidance") or {}
        if indexing_guidance:
            lines.append(f"  - 색인 안내: {indexing_guidance.get('summary', '확인 필요')}")
            if indexing_guidance.get("expected_wait"):
                lines.append(f"  - 예상 대기: {indexing_guidance.get('expected_wait')}")
            if indexing_guidance.get("check_location"):
                lines.append(f"  - 확인 위치: {indexing_guidance.get('check_location')}")
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

        lines.extend(["", "## 다음 할 일", ""])
        for action in report["next_actions"]:
            lines.append(f"- {action}")
        lines.append("")
        return "\n".join(lines)


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
        "missing_today": "오늘 공개 글 없음",
        "validated": "검증 완료",
        "draft_uploaded": "초안 업로드",
        "published": "공개 발행",
        "skipped_duplicate": "중복 건너뜀",
        "skipped_daily_limit": "하루 1개 제한으로 건너뜀",
        "fallback_only": "fallback 사용",
        "failed": "실패",
        "oauth_connected": "OAuth 연결 확인",
        "oauth_connected_no_results": "OAuth 연결됨, 결과 없음",
        "missing_credentials": "Reddit OAuth 키 없음",
        "missing_user_agent": "Reddit User-Agent 없음",
        "missing_praw": "PRAW 패키지 없음",
        "oauth_error": "OAuth 오류",
    }
    return mapping.get(status or "not_uploaded", status or "미업로드")
