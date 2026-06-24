from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from src.config import ROOT_DIR, Settings


class WeeklyReporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.generated_root = ROOT_DIR / "data" / "generated"

    def generate(self) -> Path:
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)
        articles = self._collect_articles(week_start)
        static_pages = self._static_pages_result()

        report = {
            "generated_at": now.isoformat(),
            "site_name": self.settings.site_name,
            "site_url": self.settings.site_url,
            "week_start": week_start.date().isoformat(),
            "week_end": now.date().isoformat(),
            "article_count": len(articles),
            "draft_count": sum(1 for item in articles if item.get("blogger_status") == "DRAFT"),
            "published_count": sum(1 for item in articles if item.get("blogger_status") == "LIVE"),
            "articles": articles,
            "static_pages": static_pages,
            "search_console": {
                "status": "not_connected",
                "note": "Search Console metrics will be added after Search Console API credentials are configured.",
            },
            "next_actions": self._next_actions(articles, static_pages),
        }

        output_dir = ROOT_DIR / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"weekly-{now.date().isoformat()}.json"
        md_path = output_dir / f"weekly-{now.date().isoformat()}.md"
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

    def _next_actions(self, articles: list[dict], static_pages: list[dict]) -> list[str]:
        actions = []
        if len(static_pages) < 4:
            actions.append("Create all required static pages: About, Contact, Privacy Policy, Disclaimer.")
        if not articles:
            actions.append("Generate at least one article draft.")
        if any(article.get("blogger_status") == "DRAFT" for article in articles):
            actions.append("Review Blogger drafts manually before public publishing.")
        if not any(article.get("blogger_status") == "LIVE" for article in articles):
            actions.append("Connect Search Console after the site has public content.")
        actions.append("Keep AI/API costs at zero until traffic and revenue signals are visible.")
        return actions

    def _to_markdown(self, report: dict) -> str:
        lines = [
            f"# Weekly Report: {report['site_name']}",
            "",
            f"- Site: {report['site_url']}",
            f"- Period: {report['week_start']} to {report['week_end']}",
            f"- Generated articles: {report['article_count']}",
            f"- Draft posts: {report['draft_count']}",
            f"- Published posts: {report['published_count']}",
            "",
            "## Articles",
            "",
        ]
        if report["articles"]:
            lines.append("| Title | Category | Blogger Status |")
            lines.append("|---|---|---|")
            for article in report["articles"]:
                lines.append(
                    f"| {article.get('title') or ''} | {article.get('category') or ''} | {article.get('blogger_status') or 'not_uploaded'} |"
                )
        else:
            lines.append("No generated articles found for this period.")

        lines.extend(["", "## Static Pages", ""])
        if report["static_pages"]:
            lines.append("| Title | Status | URL |")
            lines.append("|---|---|---|")
            for page in report["static_pages"]:
                lines.append(f"| {page.get('title')} | {page.get('status')} | {page.get('url')} |")
        else:
            lines.append("No static page upload result found.")

        lines.extend(["", "## Next Actions", ""])
        for action in report["next_actions"]:
            lines.append(f"- {action}")
        lines.append("")
        return "\n".join(lines)
