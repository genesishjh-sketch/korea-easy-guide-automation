from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re

from bs4 import BeautifulSoup


REQUIRED_HEADINGS = {
    "Quick Answer",
    "Before You Start",
    "Step-by-Step Guide",
    "Costs / Payment",
    "Common Problems",
    "Useful Tips for Foreign Visitors",
    "FAQ",
    "Official Links to Check",
}

MIN_WORD_COUNT = 1400
MIN_OFFICIAL_LINKS = 4
MIN_FAQ_QUESTIONS = 5
MIN_RESEARCH_QUERIES = 6
MIN_RESEARCH_SOURCES = 6
MIN_RESEARCH_READER_QUESTIONS = 5

OFFICIAL_SOURCE_DOMAINS = (
    ".go.kr",
    "visitkorea.or.kr",
    "korail.com",
    "airport.kr",
    "airportrailroad.com",
    "tmoney.co.kr",
    "seoul.go.kr",
    "seoulmetro.co.kr",
    "skroaming.com",
    "kt.com",
    "lguplus.com",
    "kakaomobility.com",
    "wowpass.io",
    "namanecard.com",
    "naver.com",
    "kakao.com",
    "apple.com",
    "google.com",
)

BLOCKED_PHRASES = {
    "lorem ipsum",
    "insert image",
    "placeholder",
    "as an ai",
    "i cannot",
    "sources to check before you go",
    "common mistakes to avoid",
    "what you should know first",
}


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class QualityReport:
    reviewer: str
    passed: bool
    score: int
    min_score: int
    issues: list[QualityIssue]
    metrics: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "reviewer": self.reviewer,
            "passed": self.passed,
            "score": self.score,
            "min_score": self.min_score,
            "issues": [asdict(issue) for issue in self.issues],
            "metrics": self.metrics,
        }


class HadesQualityGate:
    """Strict automated reviewer for public Blogger publishing."""

    reviewer_name = "Hades Engineer"
    min_score = 90

    def review_article_dir(self, article_dir: Path) -> QualityReport:
        html_path = article_dir / "article.html"
        metadata_path = article_dir / "metadata.json"
        if not html_path.exists() or not metadata_path.exists():
            return self._report(
                0,
                [QualityIssue("missing_article_files", "article.html and metadata.json are required.")],
                {},
            )

        html = html_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return self.review_html(html, article_dir, metadata)

    def review_html(self, html: str, article_dir: Path, metadata: dict) -> QualityReport:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        text_lower = text.lower()
        words = re.findall(r"[A-Za-z0-9']+", text)
        headings = {heading.get_text(" ", strip=True) for heading in soup.find_all(["h2", "h3"])}
        images = soup.find_all("img")
        links = soup.find_all("a")
        official_links = [
            link
            for link in links
            if any(domain in (link.get("href") or "") for domain in OFFICIAL_SOURCE_DOMAINS)
        ]
        faq_heading = soup.find(string=re.compile(r"^FAQ$", re.I))
        faq_questions = 0
        if faq_heading:
            faq_questions = len([heading for heading in soup.find_all("h3")])

        issues: list[QualityIssue] = []
        missing_headings = sorted(REQUIRED_HEADINGS - headings)
        if missing_headings:
            issues.append(QualityIssue("missing_required_sections", f"Missing sections: {', '.join(missing_headings)}."))
        if len(words) < MIN_WORD_COUNT:
            issues.append(QualityIssue("thin_content", f"Article must contain at least {MIN_WORD_COUNT} words before public publishing."))
        if len(images) < 2:
            issues.append(QualityIssue("missing_images", "Article must include at least one hero image and one inline image."))
        if len(official_links) < MIN_OFFICIAL_LINKS:
            issues.append(QualityIssue("weak_sources", f"Article must include at least {MIN_OFFICIAL_LINKS} official or platform source links."))
        if faq_questions < MIN_FAQ_QUESTIONS:
            issues.append(QualityIssue("weak_faq", f"FAQ must include at least {MIN_FAQ_QUESTIONS} questions."))

        for phrase in BLOCKED_PHRASES:
            if phrase in text_lower:
                issues.append(QualityIssue("blocked_phrase", f"Blocked phrase found: {phrase}."))

        image_plan_path = article_dir / "image_plan.json"
        if image_plan_path.exists():
            image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
            missing_assets = []
            for image in image_plan.get("images", []):
                if image.get("required", True):
                    url = image.get("url") or f"assets/{image.get('filename', '')}"
                    if url.startswith("assets/") and not (article_dir / url).exists():
                        missing_assets.append(url)
            if missing_assets:
                issues.append(QualityIssue("missing_required_image_assets", f"Missing image assets: {', '.join(missing_assets)}."))

        article = metadata.get("article", {})
        if not article.get("meta_description"):
            issues.append(QualityIssue("missing_meta_description", "Meta description is required."))
        if not article.get("tags"):
            issues.append(QualityIssue("missing_tags", "Tags are required."))

        research_metrics, research_issues = self._review_research_report(article_dir)
        issues.extend(research_issues)

        score = max(0, 100 - sum(12 if issue.severity == "error" else 4 for issue in issues))
        metrics = {
            "word_count": len(words),
            "image_count": len(images),
            "official_link_count": len(official_links),
            "faq_question_count": faq_questions,
            "heading_count": len(headings),
            **research_metrics,
        }
        return self._report(score, issues, metrics)

    def _review_research_report(self, article_dir: Path) -> tuple[dict[str, int], list[QualityIssue]]:
        report_path = article_dir / "research_report.json"
        metrics = {
            "research_query_count": 0,
            "research_source_count": 0,
            "research_official_source_count": 0,
            "research_reader_question_count": 0,
        }
        if not report_path.exists():
            return metrics, [QualityIssue("missing_research_report", "research_report.json is required before public publishing.")]

        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return metrics, [QualityIssue("invalid_research_report", "research_report.json must be valid JSON.")]

        queries = report.get("queries", [])
        sources = report.get("sources", [])
        reader_questions = report.get("reader_questions", [])
        official_sources = [
            source
            for source in sources
            if any(domain in (source.get("url") or "") for domain in OFFICIAL_SOURCE_DOMAINS)
        ]

        metrics.update(
            {
                "research_query_count": len(queries),
                "research_source_count": len(sources),
                "research_official_source_count": len(official_sources),
                "research_reader_question_count": len(reader_questions),
            }
        )

        issues: list[QualityIssue] = []
        if len(queries) < MIN_RESEARCH_QUERIES:
            issues.append(QualityIssue("shallow_research_queries", f"Research must include at least {MIN_RESEARCH_QUERIES} search queries."))
        if len(sources) < MIN_RESEARCH_SOURCES:
            issues.append(QualityIssue("shallow_research_sources", f"Research must include at least {MIN_RESEARCH_SOURCES} sources."))
        if len(official_sources) < 3:
            issues.append(QualityIssue("weak_official_research", "Research must include at least three official or platform sources."))
        if len(reader_questions) < MIN_RESEARCH_READER_QUESTIONS:
            issues.append(QualityIssue("weak_reader_questions", f"Research must include at least {MIN_RESEARCH_READER_QUESTIONS} reader questions or search intents."))
        return metrics, issues

    def _report(self, score: int, issues: list[QualityIssue], metrics: dict[str, int]) -> QualityReport:
        return QualityReport(
            reviewer=self.reviewer_name,
            passed=score >= self.min_score and not issues,
            score=score,
            min_score=self.min_score,
            issues=issues,
            metrics=metrics,
        )
