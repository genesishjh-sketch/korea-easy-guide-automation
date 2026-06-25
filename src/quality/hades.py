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
MIN_WINDOWS_MICROSOFT_LINKS = 4
MIN_WINDOWS_DIRECT_MICROSOFT_LINKS = 2

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
    "microsoft.com",
    "learn.microsoft.com",
    "support.microsoft.com",
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

WINDOWS_REQUIRED_HEADINGS = {
    "Quick Summary",
    "Applies to / Risk level / Data loss risk / Estimated time / Last checked",
    "Symptoms",
    "What This Usually Means",
    "What Not to Do First",
    "Try This First",
    "Step-by-Step Fixes",
    "After Each Step",
    "What to Record Before Asking for Help",
    "Advanced Fixes",
    "When to Stop and Get Help",
    "FAQ",
    "Related Guides",
    "Sources",
}

WINDOWS_BLOCKED_PHRASES = {
    "crack",
    "kms activator",
    "activate windows for free",
    "download this repair tool",
    "disable antivirus permanently",
}

WINDOWS_ADVANCED_ONLY_TERMS = {
    "registry",
    "regedit",
    "bios",
    "uefi",
    "partition",
    "format",
    "powershell",
    "command prompt",
    "diskpart",
}

WINDOWS_COMMAND_REPAIR_TERMS = {
    "sfc",
    "dism",
    "chkdsk",
    "cmd",
    "powershell",
    "command prompt",
    "command-line",
    "command line",
    "diskpart",
}

WINDOWS_GENERIC_TOPIC_TOKENS = {
    "windows",
    "win10",
    "win11",
    "error",
    "issue",
    "issues",
    "problem",
    "problems",
    "working",
    "opening",
    "missing",
    "after",
    "before",
    "with",
    "from",
    "says",
    "code",
}

WINDOWS_TOPIC_CONTEXT_CONFLICTS = {
    "onedrive": {
        "topic_markers": ("onedrive",),
        "conflicting_phrases": (
            "windows update shows",
            "windows update troubleshooter",
            "windows update may be blocked",
            "check windows release health to see whether microsoft has listed a known update issue",
        ),
    }
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

    def __init__(self, content_domain: str = "korea_travel") -> None:
        self.content_domain = content_domain

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
        required_headings = WINDOWS_REQUIRED_HEADINGS if self.content_domain == "windows_help" else REQUIRED_HEADINGS
        missing_headings = sorted(required_headings - headings)
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

        if self.content_domain == "windows_help":
            issues.extend(self._review_windows_article(soup, text_lower, links))

        image_plan_path = article_dir / "image_plan.json"
        if not image_plan_path.exists():
            issues.append(QualityIssue("missing_image_plan", "image_plan.json is required before public publishing."))
        else:
            image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
            if not image_plan.get("strict", False):
                issues.append(QualityIssue("non_strict_image_plan", "image_plan.json must set strict=true."))
            required_images = [image for image in image_plan.get("images", []) if image.get("required", True)]
            if len(required_images) < 2:
                issues.append(QualityIssue("weak_image_plan", "Image plan must include at least two required images."))
            issues.extend(_review_image_descriptions(required_images))
            missing_assets = []
            invalid_urls = []
            for image in required_images:
                url = image.get("url") or f"assets/{image.get('filename', '')}"
                if not url.startswith("assets/"):
                    invalid_urls.append(url)
                    continue
                if not (article_dir / url).exists():
                    missing_assets.append(url)
            if invalid_urls:
                issues.append(QualityIssue("invalid_image_plan_url", f"Required images must be local assets/ files: {', '.join(invalid_urls)}."))
            if missing_assets:
                issues.append(QualityIssue("missing_required_image_assets", f"Missing image assets: {', '.join(missing_assets)}."))

        article = metadata.get("article", {})
        if not article.get("meta_description"):
            issues.append(QualityIssue("missing_meta_description", "Meta description is required."))
        if not article.get("tags"):
            issues.append(QualityIssue("missing_tags", "Tags are required."))
        if self.content_domain == "windows_help":
            issues.extend(_review_topic_alignment(metadata, text_lower))

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

    def _review_windows_article(self, soup: BeautifulSoup | None, text_lower: str, links: list) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        microsoft_links = [_href(link) for link in links if _is_microsoft_url(_href(link))]
        direct_microsoft_links = [url for url in microsoft_links if _is_direct_microsoft_url(url)]
        if len(microsoft_links) < MIN_WINDOWS_MICROSOFT_LINKS:
            issues.append(
                QualityIssue(
                    "weak_microsoft_sources",
                    f"Windows help articles require at least {MIN_WINDOWS_MICROSOFT_LINKS} official Microsoft source links.",
                )
            )
        if not microsoft_links:
            issues.append(QualityIssue("missing_microsoft_source", "Windows help articles require official Microsoft sources."))
        if len(direct_microsoft_links) < MIN_WINDOWS_DIRECT_MICROSOFT_LINKS:
            issues.append(
                QualityIssue(
                    "shallow_microsoft_sources",
                    "Windows help articles require at least "
                    f"{MIN_WINDOWS_DIRECT_MICROSOFT_LINKS} direct Microsoft support, Learn, release-health, or product links, not only search result pages.",
                )
            )
        for required in ["applies to", "risk level", "data loss risk", "estimated time", "last checked"]:
            if required not in text_lower:
                issues.append(QualityIssue("missing_windows_safety_field", f"Missing Windows safety field: {required}."))
        if "advanced fixes" in text_lower and "back up important files" not in text_lower:
            issues.append(QualityIssue("missing_advanced_warning", "Advanced fixes require a clear backup warning."))
        if soup is not None:
            issues.extend(self._review_windows_advanced_only_terms(soup))
            issues.extend(self._review_windows_related_guides(soup))
        issues.extend(self._review_windows_command_safety(text_lower))
        issues.extend(self._review_windows_topic_context(text_lower))
        for phrase in WINDOWS_BLOCKED_PHRASES:
            if phrase in text_lower:
                issues.append(QualityIssue("blocked_windows_phrase", f"Blocked Windows phrase found: {phrase}."))
        return issues

    def _review_windows_command_safety(self, text_lower: str) -> list[QualityIssue]:
        found_terms = sorted(term for term in WINDOWS_COMMAND_REPAIR_TERMS if term in text_lower)
        if not found_terms:
            return []

        issues: list[QualityIssue] = []
        if "do not run commands you do not understand" not in text_lower:
            issues.append(
                QualityIssue(
                    "missing_command_understanding_warning",
                    "Windows command-line repair mentions require a warning not to run commands the reader does not understand.",
                )
            )
        official_command_guard = (
            "copy commands only from official microsoft documentation" in text_lower
            or "use sfc or dism only from official microsoft instructions" in text_lower
            or "official microsoft instructions" in text_lower
        )
        if not official_command_guard:
            issues.append(
                QualityIssue(
                    "missing_official_command_source_warning",
                    "Windows command-line repair mentions require guidance to use only official Microsoft command instructions.",
                )
            )
        return issues

    def _review_windows_related_guides(self, soup: BeautifulSoup) -> list[QualityIssue]:
        related_items = _section_list_items_by_h2(soup).get("related guides", [])
        related_links = _section_links_by_h2(soup).get("related guides", [])
        if len(related_items) < 3:
            return [
                QualityIssue(
                    "weak_related_guides",
                    "Windows help articles require at least three Related Guides items for topic clustering.",
                )
            ]
        internal_links = [url for url in related_links if "/search?q=" in url or "easypcfixguide.blogspot.com" in url]
        if len(internal_links) < 3:
            return [
                QualityIssue(
                    "weak_related_guide_links",
                    "Windows help articles require at least three internal Related Guides links.",
                )
            ]
        return []

    def _review_windows_topic_context(self, text_lower: str) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for topic, rule in WINDOWS_TOPIC_CONTEXT_CONFLICTS.items():
            topic_markers = rule["topic_markers"]
            if not any(marker in text_lower for marker in topic_markers):
                continue
            conflicts = sorted(phrase for phrase in rule["conflicting_phrases"] if phrase in text_lower)
            if conflicts:
                issues.append(
                    QualityIssue(
                        "windows_topic_context_mismatch",
                        f"{topic.title()} article contains unrelated Windows Update troubleshooting copy: {', '.join(conflicts)}.",
                    )
                )
        return issues

    def _review_windows_advanced_only_terms(self, soup: BeautifulSoup) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        beginner_sections = {
            "try this first",
            "step-by-step fixes",
        }
        for heading, section_text in _section_text_by_h2(soup).items():
            if heading.casefold() not in beginner_sections:
                continue
            section_lower = section_text.casefold()
            found_terms = sorted(term for term in WINDOWS_ADVANCED_ONLY_TERMS if term in section_lower)
            if found_terms:
                issues.append(
                    QualityIssue(
                        "advanced_fix_in_beginner_section",
                        f"Advanced-only terms found in {heading}: {', '.join(found_terms)}.",
                    )
                )
        return issues

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
        if self.content_domain == "windows_help":
            official_sources = [
                source
                for source in sources
                if _is_microsoft_url(source.get("url") or "")
            ]
            direct_official_sources = [
                source
                for source in official_sources
                if _is_direct_microsoft_url(source.get("url") or "")
            ]
        else:
            direct_official_sources = official_sources

        metrics.update(
            {
                "research_query_count": len(queries),
                "research_source_count": len(sources),
                "research_official_source_count": len(official_sources),
                "research_direct_official_source_count": len(direct_official_sources),
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
        if self.content_domain == "windows_help":
            if len(official_sources) < MIN_WINDOWS_MICROSOFT_LINKS:
                issues.append(
                    QualityIssue(
                        "weak_microsoft_research",
                        f"Windows research must include at least {MIN_WINDOWS_MICROSOFT_LINKS} Microsoft official sources.",
                    )
                )
            if len(direct_official_sources) < MIN_WINDOWS_DIRECT_MICROSOFT_LINKS:
                issues.append(
                    QualityIssue(
                        "shallow_microsoft_research",
                        "Windows research must include direct Microsoft pages, not only Microsoft search result URLs.",
                    )
                )
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


def _section_text_by_h2(soup: BeautifulSoup) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in soup.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        parts = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            get_text = getattr(sibling, "get_text", None)
            if get_text:
                parts.append(get_text(" ", strip=True))
        sections[title] = " ".join(part for part in parts if part)
    return sections


def _section_list_items_by_h2(soup: BeautifulSoup) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    for heading in soup.find_all("h2"):
        title = heading.get_text(" ", strip=True).casefold()
        items = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            find_all = getattr(sibling, "find_all", None)
            if find_all:
                items.extend(item.get_text(" ", strip=True) for item in find_all("li"))
        sections[title] = [item for item in items if item]
    return sections


def _section_links_by_h2(soup: BeautifulSoup) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    for heading in soup.find_all("h2"):
        title = heading.get_text(" ", strip=True).casefold()
        links = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            find_all = getattr(sibling, "find_all", None)
            if find_all:
                links.extend(_href(link) for link in find_all("a"))
        sections[title] = [link for link in links if link]
    return sections


def _review_image_descriptions(images: list[dict]) -> list[QualityIssue]:
    weak_alt = []
    weak_caption = []
    generic_alt_values = {"hero", "inline", "image", "photo", "picture", "cover", "visual"}
    for image in images:
        filename = image.get("filename") or image.get("url") or "unknown image"
        alt = str(image.get("alt") or "").strip()
        caption = str(image.get("caption") or "").strip()
        if len(alt.split()) < 5 or alt.casefold() in generic_alt_values:
            weak_alt.append(filename)
        if len(caption.split()) < 7:
            weak_caption.append(filename)
    issues = []
    if weak_alt:
        issues.append(
            QualityIssue(
                "weak_image_alt_text",
                f"Required images need descriptive alt text tied to the topic: {', '.join(weak_alt)}.",
            )
        )
    if weak_caption:
        issues.append(
            QualityIssue(
                "weak_image_caption",
                f"Required images need helpful captions for readers: {', '.join(weak_caption)}.",
            )
        )
    return issues


def _review_topic_alignment(metadata: dict, text_lower: str) -> list[QualityIssue]:
    candidate = metadata.get("candidate", {}) or {}
    article = metadata.get("article", {}) or {}
    keyword = str(candidate.get("keyword") or "").strip()
    if not keyword:
        return []

    title = str(article.get("title") or "")
    haystack = _normalize_topic_text(f"{title} {text_lower}")
    error_codes = re.findall(r"0x[a-f0-9]{8}", keyword.casefold())
    missing_error_codes = [code.upper() for code in error_codes if code not in haystack]
    if missing_error_codes:
        return [
            QualityIssue(
                "topic_alignment_mismatch",
                f"Article does not preserve topic error code(s): {', '.join(missing_error_codes)}.",
            )
        ]

    tokens = _distinctive_topic_tokens(keyword)
    if len(tokens) < 2:
        return []
    matched = [token for token in tokens if token in haystack]
    required_matches = 2 if len(tokens) >= 2 else len(tokens)
    if len(matched) < required_matches:
        return [
            QualityIssue(
                "topic_alignment_mismatch",
                "Article title/body does not preserve enough distinctive topic words from the seed: "
                f"{', '.join(tokens[:6])}.",
            )
        ]
    return []


def _distinctive_topic_tokens(keyword: str) -> list[str]:
    normalized = _normalize_topic_text(keyword)
    tokens = []
    for token in re.findall(r"[a-z0-9]+", normalized):
        if token in WINDOWS_GENERIC_TOPIC_TOKENS:
            continue
        if len(token) < 4 and not token.startswith("0x"):
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def _normalize_topic_text(value: str) -> str:
    normalized = value.casefold()
    normalized = normalized.replace("wi-fi", "wifi").replace("wi fi", "wifi")
    return normalized


def _href(link: object) -> str:
    get = getattr(link, "get", None)
    if get:
        return get("href") or ""
    if isinstance(link, dict):
        return str(link.get("url") or link.get("href") or "")
    return ""


def _is_microsoft_url(url: str) -> bool:
    return any(domain in url for domain in ("microsoft.com", "learn.microsoft.com", "support.microsoft.com"))


def _is_direct_microsoft_url(url: str) -> bool:
    if not _is_microsoft_url(url):
        return False
    blocked_fragments = (
        "support.microsoft.com/search/results",
        "support.microsoft.com/search?",
        "bing.com/search",
    )
    return not any(fragment in url for fragment in blocked_fragments)
