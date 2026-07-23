from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from src.config import ROOT_DIR, load_settings
from src.publishing.blogger import BloggerPublisher


KST = ZoneInfo("Asia/Seoul")
MAX_ORPHAN_LINKS_PER_SOURCE = 2
LINK_OVERRIDES = {
    "https://koreaeasyguide.blogspot.com/2026/07/how-to-order-food-in-korean-restaurants.html": (
        "https://koreaeasyguide.blogspot.com/2026/06/how-to-use-baemin-food-delivery-in.html"
    ),
}
STOPWORDS = {
    "a",
    "and",
    "as",
    "for",
    "guide",
    "how",
    "in",
    "of",
    "on",
    "the",
    "to",
    "use",
    "windows",
}


def run(sites: list[str] | None = None, apply: bool = False) -> Path:
    selected_sites = sites or ["korea_easy_guide", "easy_pc_fix_guide"]
    stamp = datetime.now(tz=KST).strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT_DIR / "data" / "backups" / "live_posts" / stamp
    preview_dir = ROOT_DIR / "data" / "previews" / "indexing_link_repairs" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    report = {"created_at_kst": datetime.now(tz=KST).isoformat(), "apply": apply, "sites": {}}

    for site in selected_sites:
        settings = load_settings(site)
        publisher = BloggerPublisher(settings)
        posts = publisher.list_live_posts(fetch_bodies=True)
        backup_path = backup_dir / f"{site}.json"
        backup_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        transformed, site_report = build_repairs(posts, settings.site_url)
        site_report["backup"] = str(backup_path)
        site_preview_dir = preview_dir / site
        site_preview_dir.mkdir(parents=True, exist_ok=True)

        for post in posts:
            post_id = str(post.get("id") or "")
            old_html = str(post.get("content") or "")
            new_html = transformed[post_id]
            if old_html == new_html:
                continue
            preview_path = site_preview_dir / f"{post_id}.html"
            preview_path.write_text(new_html, encoding="utf-8")
            record = {
                "id": post_id,
                "title": post.get("title"),
                "url": post.get("url"),
                "preview": str(preview_path),
            }
            if apply:
                try:
                    publisher.update_post(
                        post_id,
                        str(post.get("title") or ""),
                        new_html,
                        list(post.get("labels") or []),
                    )
                except Exception as exc:
                    site_report["failed"].append({**record, "error": str(exc)})
                    continue
            site_report["updated"].append(record)
        report["sites"][site] = site_report

    output_path = ROOT_DIR / "reports" / "indexing-link-repair-report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_repairs(posts: list[dict], site_url: str) -> tuple[dict[str, str], dict]:
    live_urls = {normalize_url(str(post.get("url") or "")): post for post in posts}
    transformed: dict[str, str] = {}
    replacements: list[dict] = []
    unresolved: list[dict] = []
    for post in posts:
        post_id = str(post.get("id") or "")
        html, changed, missing = replace_broken_links(post, posts, live_urls, site_url)
        transformed[post_id] = html
        replacements.extend(changed)
        unresolved.extend(missing)

    incoming = incoming_counts(posts, transformed, live_urls, site_url)
    orphan_urls = [url for url, count in incoming.items() if count == 0]
    additions: list[dict] = []
    source_addition_counts: Counter[str] = Counter()
    for orphan_url in sorted(orphan_urls):
        orphan = live_urls[orphan_url]
        source = choose_orphan_source(orphan, posts, source_addition_counts)
        if not source:
            continue
        source_id = str(source.get("id") or "")
        revised = add_related_link(
            transformed[source_id],
            str(orphan.get("title") or ""),
            str(orphan.get("url") or ""),
        )
        if revised == transformed[source_id]:
            continue
        transformed[source_id] = revised
        source_addition_counts[source_id] += 1
        additions.append(
            {
                "source_id": source_id,
                "source_title": source.get("title"),
                "source_url": source.get("url"),
                "target_title": orphan.get("title"),
                "target_url": orphan.get("url"),
            }
        )

    final_incoming = incoming_counts(posts, transformed, live_urls, site_url)
    remaining_orphans = [
        {"title": live_urls[url].get("title"), "url": live_urls[url].get("url")}
        for url, count in final_incoming.items()
        if count == 0
    ]
    return transformed, {
        "updated": [],
        "failed": [],
        "broken_link_replacements": replacements,
        "unresolved_broken_links": unresolved,
        "orphan_link_additions": additions,
        "remaining_orphans": remaining_orphans,
    }


def replace_broken_links(
    post: dict,
    posts: list[dict],
    live_urls: dict[str, dict],
    site_url: str,
) -> tuple[str, list[dict], list[dict]]:
    original = str(post.get("content") or "")
    soup = BeautifulSoup(original, "html.parser")
    changed: list[dict] = []
    unresolved: list[dict] = []
    site_host = urlparse(site_url).netloc.casefold()
    current_url = normalize_url(str(post.get("url") or ""))
    for anchor in soup.select("a[href]"):
        old_url = normalize_url(urljoin(site_url.rstrip("/") + "/", str(anchor.get("href") or "")))
        parsed = urlparse(old_url)
        if parsed.netloc.casefold() != site_host or not parsed.path.endswith(".html"):
            continue
        if old_url in live_urls:
            continue
        replacement = best_replacement(
            anchor.get_text(" ", strip=True),
            old_url,
            posts,
            current_url=current_url,
        )
        if not replacement:
            unresolved.append(
                {
                    "source_title": post.get("title"),
                    "source_url": post.get("url"),
                    "broken_url": old_url,
                    "anchor": anchor.get_text(" ", strip=True),
                }
            )
            continue
        anchor["href"] = str(replacement.get("url") or "")
        anchor.string = str(replacement.get("title") or anchor.get_text(" ", strip=True))
        changed.append(
            {
                "source_title": post.get("title"),
                "source_url": post.get("url"),
                "old_url": old_url,
                "new_url": replacement.get("url"),
                "new_title": replacement.get("title"),
            }
        )
    return (str(soup) if changed else original), changed, unresolved


def best_replacement(anchor: str, broken_url: str, posts: list[dict], current_url: str) -> dict | None:
    override_url = LINK_OVERRIDES.get(broken_url)
    if override_url:
        override = next(
            (
                post
                for post in posts
                if normalize_url(str(post.get("url") or "")) == normalize_url(override_url)
            ),
            None,
        )
        if override and normalize_url(str(override.get("url") or "")) != current_url:
            return override
    query = f"{anchor} {urlparse(broken_url).path.replace('-', ' ')}"
    ranked = [
        (semantic_score(query, str(post.get("title") or "")), post)
        for post in posts
        if normalize_url(str(post.get("url") or "")) != current_url
    ]
    score, post = max(ranked, default=(0.0, None), key=lambda item: item[0])
    return post if post and score >= 0.2 else None


def choose_orphan_source(orphan: dict, posts: list[dict], addition_counts: Counter[str]) -> dict | None:
    orphan_id = str(orphan.get("id") or "")
    orphan_text = " ".join([str(orphan.get("title") or ""), " ".join(orphan.get("labels") or [])])
    ranked = []
    for post in posts:
        post_id = str(post.get("id") or "")
        if post_id == orphan_id or addition_counts[post_id] >= MAX_ORPHAN_LINKS_PER_SOURCE:
            continue
        source_text = " ".join([str(post.get("title") or ""), " ".join(post.get("labels") or [])])
        ranked.append((semantic_score(orphan_text, source_text), str(post.get("published") or ""), post))
    _, _, selected = max(ranked, default=(0.0, "", None), key=lambda item: (item[0], item[1]))
    return selected


def semantic_score(first: str, second: str) -> float:
    first_tokens = content_tokens(first)
    second_tokens = content_tokens(second)
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def content_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in STOPWORDS
    }


def add_related_link(html: str, title: str, url: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    if any(normalize_url(str(anchor.get("href") or "")) == normalize_url(url) for anchor in soup.select("a[href]")):
        return html
    heading = next(
        (
            item
            for item in soup.find_all("h2")
            if item.get_text(" ", strip=True).casefold() == "related guides"
        ),
        None,
    )
    if not heading:
        heading = soup.new_tag("h2")
        heading.string = "Related Guides"
        boundary = next(
            (
                item
                for item in soup.find_all("h2")
                if item.get_text(" ", strip=True).casefold()
                in {"sources", "official links to check", "final summary"}
            ),
            None,
        )
        if boundary:
            boundary.insert_before(heading)
        else:
            (soup.find("article") or soup).append(heading)
    listing = next_sibling_list(heading)
    if not listing:
        listing = soup.new_tag("ul")
        heading.insert_after(listing)
    item = soup.new_tag("li")
    anchor = soup.new_tag("a", href=url)
    anchor.string = title
    item.append(anchor)
    listing.append(item)
    return str(soup)


def next_sibling_list(heading: Tag) -> Tag | None:
    cursor = heading.find_next_sibling()
    while cursor and not (isinstance(cursor, Tag) and cursor.name == "h2"):
        if isinstance(cursor, Tag) and cursor.name in {"ul", "ol"}:
            return cursor
        cursor = cursor.find_next_sibling()
    return None


def incoming_counts(
    posts: list[dict],
    transformed: dict[str, str],
    live_urls: dict[str, dict],
    site_url: str,
) -> dict[str, int]:
    counts = {url: 0 for url in live_urls}
    site_host = urlparse(site_url).netloc.casefold()
    for post in posts:
        current_url = normalize_url(str(post.get("url") or ""))
        soup = BeautifulSoup(transformed[str(post.get("id") or "")], "html.parser")
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            target = normalize_url(urljoin(site_url.rstrip("/") + "/", str(anchor.get("href") or "")))
            if (
                urlparse(target).netloc.casefold() == site_host
                and target in counts
                and target != current_url
                and target not in seen
            ):
                counts[target] += 1
                seen.add(target)
    return counts


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair broken Blogger post links and add one incoming link to orphan posts.")
    parser.add_argument("--site", action="append", choices=["korea_easy_guide", "easy_pc_fix_guide"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(run(args.site, args.apply))


if __name__ == "__main__":
    main()
