from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from src.config import ROOT_DIR, load_settings
from src.publishing.blogger import BloggerPublisher
from src.quality.originality import MAX_BODY_SIMILARITY, shingle_similarity


KST = ZoneInfo("Asia/Seoul")
MIN_EDITORIAL_WORDS = 900
BLOCK_SIMILARITY_LIMIT = 0.42
PRESERVED_SECTIONS = {
    "Applies to / Risk level / Data loss risk / Estimated time / Last checked",
    "Related Guides",
    "Sources",
    "Official Links to Check",
}
SECTION_MINIMUMS = {
    "korea_easy_guide": {
        "Quick Answer": 3,
        "Before You Start": 3,
        "Step-by-Step Guide": 5,
        "Costs / Payment": 3,
        "Common Problems": 4,
        "Useful Tips for Foreign Visitors": 4,
        "FAQ": 5,
        "Final Summary": 1,
    },
    "easy_pc_fix_guide": {
        "Quick Summary": 4,
        "Before You Start": 3,
        "Symptoms": 4,
        "What This Usually Means": 3,
        "What Not to Do First": 3,
        "Try This First": 5,
        "Step-by-Step Fixes": 5,
        "After Each Step": 4,
        "What to Record Before Asking for Help": 1,
        "Advanced Fixes": 1,
        "When to Stop and Get Help": 4,
        "FAQ": 5,
        "Final Summary": 1,
    },
}


@dataclass
class ContentUnit:
    section: str
    nodes: tuple[Tag, ...]
    text: str
    similarity: float = 0.0
    keep: bool = False


def run(
    sites: list[str] | None = None,
    apply: bool = False,
    post_ids: set[str] | None = None,
) -> Path:
    selected_sites = sites or ["korea_easy_guide", "easy_pc_fix_guide"]
    stamp = datetime.now(tz=KST).strftime("%Y%m%d-%H%M%S")
    output_dir = ROOT_DIR / "data" / "previews" / "deduplicated_live_posts" / stamp
    backup_dir = ROOT_DIR / "data" / "backups" / "live_posts" / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at_kst": datetime.now(tz=KST).isoformat(),
        "apply": apply,
        "minimum_words": MIN_EDITORIAL_WORDS,
        "maximum_similarity": MAX_BODY_SIMILARITY,
        "sites": {},
    }

    for site in selected_sites:
        settings = load_settings(site)
        publisher = BloggerPublisher(settings)
        posts = publisher.list_live_posts(fetch_bodies=True)
        (backup_dir / f"{site}.json").write_text(
            json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        site_preview = output_dir / site
        site_preview.mkdir(parents=True, exist_ok=True)
        rewritten = limit_rewrites_to_post_ids(posts, build_rewrites(site, posts), post_ids)
        similarities = body_similarities(rewritten)
        site_report = {"backup": str(backup_dir / f"{site}.json"), "updated": [], "held": [], "unchanged": []}

        for post in posts:
            post_id = str(post.get("id") or "")
            original_html = str(post.get("content") or "")
            revised_html = rewritten[post_id]
            word_count = english_word_count(revised_html)
            similarity, similar_id = similarities[post_id]
            preview = site_preview / f"{post_id}.html"
            preview.write_text(revised_html, encoding="utf-8")
            checks = validate_rewrite(site, revised_html, word_count, similarity)
            record = {
                "id": post_id,
                "title": post.get("title"),
                "url": post.get("url"),
                "preview": str(preview),
                "word_count_before": english_word_count(original_html),
                "word_count_after": word_count,
                "max_similarity": round(similarity, 4),
                "most_similar_post_id": similar_id,
                "checks": checks,
            }
            if revised_html == original_html:
                site_report["unchanged"].append(record)
                continue
            if checks:
                site_report["held"].append(record)
                continue
            if apply:
                publisher.update_post(
                    post_id,
                    str(post.get("title") or ""),
                    revised_html,
                    list(post.get("labels") or []),
                )
            site_report["updated"].append(record)
        report["sites"][site] = site_report

    output = ROOT_DIR / "reports" / "live-post-deduplication-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def limit_rewrites_to_post_ids(
    posts: list[dict],
    rewritten: dict[str, str],
    post_ids: set[str] | None,
) -> dict[str, str]:
    if not post_ids:
        return rewritten
    return {
        str(post.get("id") or ""): (
            rewritten[str(post.get("id") or "")]
            if str(post.get("id") or "") in post_ids
            else str(post.get("content") or "")
        )
        for post in posts
    }


def build_rewrites(site: str, posts: list[dict]) -> dict[str, str]:
    soups = {
        str(post.get("id") or ""): BeautifulSoup(str(post.get("content") or ""), "html.parser")
        for post in posts
    }
    units_by_post = {post_id: collect_units(soup) for post_id, soup in soups.items()}
    shingles_by_post = {
        post_id: [(unit, text_shingles(unit.text)) for unit in units]
        for post_id, units in units_by_post.items()
    }

    for post_id, unit_shingles in shingles_by_post.items():
        other_shingles = [
            shingles
            for other_id, other_units in shingles_by_post.items()
            if other_id != post_id
            for _, shingles in other_units
            if shingles
        ]
        for unit, shingles in unit_shingles:
            unit.similarity = max((jaccard(shingles, other) for other in other_shingles), default=0.0)

    for post_id, soup in soups.items():
        units = units_by_post[post_id]
        grouped: dict[str, list[ContentUnit]] = defaultdict(list)
        for unit in units:
            grouped[unit.section].append(unit)
        for section, section_units in grouped.items():
            if section in PRESERVED_SECTIONS:
                for unit in section_units:
                    unit.keep = True
                continue
            minimum = SECTION_MINIMUMS[site].get(section, 0)
            ranked = sorted(section_units, key=lambda unit: (unit.similarity, -len(unit.text)))
            for unit in ranked[:minimum]:
                unit.keep = True
            for unit in ranked:
                if unit.similarity < BLOCK_SIMILARITY_LIMIT:
                    unit.keep = True

        ensure_minimum_words(soup, units)
        for unit in units:
            if not unit.keep:
                for node in unit.nodes:
                    node.decompose()
        remove_empty_containers(soup)
        replace_summary(soup)
    return {post_id: str(soup) for post_id, soup in soups.items()}


def collect_units(soup: BeautifulSoup) -> list[ContentUnit]:
    units: list[ContentUnit] = []
    for heading in soup.find_all("h2"):
        section = heading.get_text(" ", strip=True)
        cursor = heading.find_next_sibling()
        while cursor and not (isinstance(cursor, Tag) and cursor.name == "h2"):
            following = cursor.find_next_sibling()
            if not isinstance(cursor, Tag):
                cursor = following
                continue
            if cursor.name == "h3" and isinstance(following, Tag) and following.name == "p":
                text = f"{cursor.get_text(' ', strip=True)} {following.get_text(' ', strip=True)}".strip()
                if text:
                    units.append(ContentUnit(section, (cursor, following), text))
                following = following.find_next_sibling()
            elif cursor.name in {"p", "div"} and cursor.get_text(" ", strip=True):
                units.append(ContentUnit(section, (cursor,), cursor.get_text(" ", strip=True)))
            elif cursor.name in {"ul", "ol"}:
                for item in cursor.find_all("li", recursive=False):
                    if item.get_text(" ", strip=True):
                        units.append(ContentUnit(section, (item,), item.get_text(" ", strip=True)))
            elif cursor.name == "table":
                rows = cursor.find_all("tr", recursive=False)
                for row in rows[1:]:
                    if row.get_text(" ", strip=True):
                        units.append(ContentUnit(section, (row,), row.get_text(" ", strip=True)))
            cursor = following
    return units


def ensure_minimum_words(soup: BeautifulSoup, units: list[ContentUnit]) -> None:
    current_words = english_word_count(str(soup))
    removed_words = sum(len(re.findall(r"[A-Za-z0-9']+", unit.text)) for unit in units if not unit.keep)
    projected = current_words - removed_words
    if projected >= MIN_EDITORIAL_WORDS:
        return
    for unit in sorted((unit for unit in units if not unit.keep), key=lambda item: (item.similarity, -len(item.text))):
        unit.keep = True
        projected += len(re.findall(r"[A-Za-z0-9']+", unit.text))
        if projected >= MIN_EDITORIAL_WORDS:
            return


def replace_summary(soup: BeautifulSoup) -> None:
    heading = next(
        (item for item in soup.find_all("h2") if item.get_text(" ", strip=True).casefold() == "final summary"),
        None,
    )
    title = soup.find("h1")
    if not heading or not title:
        return
    summary = heading.find_next_sibling("p")
    if not summary:
        summary = soup.new_tag("p")
        heading.insert_after(summary)
    first_step = section_first_item(soup, "Step-by-Step Guide") or section_first_item(soup, "Try This First")
    first_problem = section_first_item(soup, "Common Problems") or section_first_item(soup, "Symptoms")
    pieces = [f"For {title.get_text(' ', strip=True)}, begin with the first reversible check that matches what you can actually observe."]
    if first_step:
        pieces.append(f"A practical starting point is: {first_step}")
    if first_problem:
        pieces.append(f"Keep this diagnostic clue in mind: {first_problem}")
    pieces.append("Use the official links below to confirm current menus, service rules, schedules, or support guidance before making a time-sensitive or advanced change.")
    summary.string = " ".join(pieces)


def section_first_item(soup: BeautifulSoup, section_name: str) -> str:
    heading = next(
        (item for item in soup.find_all("h2") if item.get_text(" ", strip=True).casefold() == section_name.casefold()),
        None,
    )
    if not heading:
        return ""
    cursor = heading.find_next_sibling()
    while cursor and not (isinstance(cursor, Tag) and cursor.name == "h2"):
        if isinstance(cursor, Tag):
            item = cursor.find("li") if cursor.name in {"ul", "ol"} else cursor
            text = item.get_text(" ", strip=True) if isinstance(item, Tag) else ""
            if text:
                return text
        cursor = cursor.find_next_sibling()
    return ""


def remove_empty_containers(soup: BeautifulSoup) -> None:
    for container in soup.find_all(["ul", "ol", "table"]):
        if not container.get_text(" ", strip=True):
            container.decompose()


def validate_rewrite(site: str, html: str, word_count: int, similarity: float) -> list[str]:
    issues = []
    soup = BeautifulSoup(html, "html.parser")
    if word_count < MIN_EDITORIAL_WORDS:
        issues.append("under_minimum_words")
    if similarity >= MAX_BODY_SIMILARITY:
        issues.append("content_similarity_high")
    if len(soup.find_all("img")) < 2:
        issues.append("image_count_low")
    if len(soup.find_all("h3")) < 5:
        issues.append("faq_count_low")
    for section, minimum in SECTION_MINIMUMS[site].items():
        if section == "FAQ":
            continue
        if count_section_units(soup, section) < minimum:
            issues.append(f"section_too_shallow:{section}")
    return issues


def count_section_units(soup: BeautifulSoup, section_name: str) -> int:
    return sum(1 for unit in collect_units(soup) if unit.section == section_name)


def body_similarities(rewritten: dict[str, str]) -> dict[str, tuple[float, str]]:
    result = {}
    for post_id, html in rewritten.items():
        matches = [
            (shingle_similarity(html, other_html), other_id)
            for other_id, other_html in rewritten.items()
            if other_id != post_id
        ]
        result[post_id] = max(matches, default=(0.0, ""), key=lambda item: item[0])
    return result


def text_shingles(text: str, size: int = 7) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.casefold())
    return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}


def jaccard(first: set, second: set) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def english_word_count(html: str) -> int:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(["style", "script", "noscript"]):
        node.decompose()
    return len(re.findall(r"[A-Za-z0-9']+", soup.get_text(" ", strip=True)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove repeated filler from live Blogger posts without weakening required sections.")
    parser.add_argument("--site", action="append", choices=["korea_easy_guide", "easy_pc_fix_guide"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--post-id", action="append", default=[], help="Limit changes to one or more Blogger post IDs.")
    args = parser.parse_args()
    print(run(args.site, args.apply, set(args.post_id) or None))


if __name__ == "__main__":
    main()
