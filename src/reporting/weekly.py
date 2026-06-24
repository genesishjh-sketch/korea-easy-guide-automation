from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import ROOT_DIR, Settings
from src.pipeline.stage4_publication_check import fetch_public_feed
from src.pipeline.stage4_publication_check import parse_posts
from src.reporting.cadence import review_cadence
from src.reporting.analytics import GA4Client
from src.reporting.search_console import SearchConsoleClient


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
        search_console_client = SearchConsoleClient(self.settings)
        search_console = search_console_client.summary(week_start.date(), now.date())
        indexed_pages = search_console_client.indexed_page_estimate(week_start.date(), now.date())
        local_published_count = sum(1 for item in articles if item.get("blogger_status") == "LIVE")
        published_count = max(local_published_count, len(public_posts.get("posts", [])))
        cadence_review = review_cadence(
            today=now.date(),
            published_posts=published_count,
            indexed_pages_estimate=indexed_pages.get("page_count_with_search_data", 0),
            recent_impressions=search_console.get("totals_from_top_queries", {}).get("impressions", 0),
            quality_issue_count=self._quality_issue_count(articles),
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
            "search_console": search_console,
            "indexed_pages": indexed_pages,
            "analytics": GA4Client(self.settings).summary(week_start.date(), now.date()),
            "cadence_review": cadence_review.to_dict(),
            "next_actions": self._next_actions(articles, static_pages, public_posts),
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

    def _next_actions(self, articles: list[dict], static_pages: list[dict], public_posts: dict | None = None) -> list[str]:
        actions = []
        public_post_count = len((public_posts or {}).get("posts", []))
        has_local_live_article = any(article.get("blogger_status") == "LIVE" for article in articles)
        has_public_article = has_local_live_article or public_post_count > 0
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

        lines.extend(["", "## 발행량 전환 검토", ""])
        cadence = report.get("cadence_review", {})
        lines.append(f"- 권장 조치: {cadence.get('action', '확인 필요')}")
        lines.append(f"- 운영 일수: {cadence.get('days_since_start', 0)}일")
        lines.append(f"- 공개 글 수: {cadence.get('published_posts', 0)}개")
        lines.append(f"- Search Console 색인/노출 페이지 추정: {cadence.get('indexed_pages_estimate', 0)}개")
        lines.append(f"- 최근 노출 수: {cadence.get('recent_impressions', 0)}")
        lines.append(f"- 품질 이슈 수: {cadence.get('quality_issue_count', 0)}")
        lines.append(f"- 하루 2개 검토 기준일: {cadence.get('two_post_review_date')}")
        lines.append(f"- 하루 3개 검토 기준일: {cadence.get('three_post_review_date')}")
        for reason in cadence.get("reasons", []):
            lines.append(f"- 판단 근거: {reason}")

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
        "error": "오류",
        "submitted": "제출됨",
    }
    return mapping.get(status or "not_uploaded", status or "미업로드")
