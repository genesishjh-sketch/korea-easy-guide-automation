from __future__ import annotations

import argparse
from collections import Counter
from types import SimpleNamespace
import json
import logging
from pathlib import Path

from src.collectors.google import GoogleSuggestCollector
from src.collectors.reddit import RedditCollector
from src.config import ROOT_DIR, load_settings
from src.content.generator import EnglishArticleGenerator
from src.content.topic_scoring import build_candidate
from src.content.windows_generator import WindowsArticleGenerator
from src.images.ai_library import install_windows_ai_assets
from src.images.ai_plan import build_article_image_plan
from src.images.local_svg import create_korea_svg_assets
from src.storage.article_store import ArticleStore


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage1")


def load_seed(default_seed: str | None, settings) -> str:
    if default_seed:
        return default_seed
    seeds_path = Path(settings.seed_file)
    if not seeds_path.is_absolute():
        seeds_path = ROOT_DIR / seeds_path
    seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
    return seeds[0]


def run(seed: str | None = None, site: str | None = None) -> Path:
    settings = load_settings(site)
    keyword = load_seed(seed, settings)
    LOGGER.info("Collecting signals for keyword: %s", keyword)
    reddit_public_json_skip_reason = reddit_public_json_skip_reason_for_settings(settings)

    reddit = RedditCollector(
        settings.reddit_user_agent,
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        subreddits=settings.reddit_subreddits,
        skip_public_json=bool(reddit_public_json_skip_reason),
        skip_public_json_reason=reddit_public_json_skip_reason,
    )
    google = GoogleSuggestCollector()
    reddit_signals = reddit.collect(keyword, limit=6)
    google_signals = google.collect(keyword, limit=8)
    signals = reddit_signals + google_signals

    candidate = build_candidate(keyword, signals, settings.content_domain)
    LOGGER.info("Selected topic category=%s score=%s", candidate.category, candidate.score)

    generator = WindowsArticleGenerator(settings) if settings.content_domain == "windows_help" else EnglishArticleGenerator(settings)
    provisional_plan = build_article_image_plan(candidate, f"{keyword} guide")
    provisional_article = generator.generate(
        candidate,
        provisional_plan.hero_asset(),
        provisional_plan.inline_assets(),
    )
    image_plan = build_article_image_plan(candidate, provisional_article.title)
    article = generator.generate(candidate, image_plan.hero_asset(), image_plan.inline_assets())

    store = ArticleStore(Path(settings.generated_output_dir))
    output_dir = store.save(article, candidate)
    (output_dir / "image_plan.json").write_text(
        json.dumps(image_plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if settings.content_domain == "windows_help":
        install_windows_ai_assets(output_dir, article.title, keyword)
    elif image_plan.images[0].filename.endswith(".svg"):
        create_korea_svg_assets(output_dir, article.title, keyword)
    article = apply_high_quality_korea_post_if_available(output_dir, article, settings.content_domain)
    (output_dir / "research_report.json").write_text(
        json.dumps(
            build_research_report(settings, keyword, article, signals, reddit.diagnostics, google.diagnostics),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    LOGGER.info("Saved article to %s", output_dir)
    return output_dir


def apply_high_quality_korea_post_if_available(output_dir: Path, article, content_domain: str):
    if content_domain == "windows_help":
        return article
    from src.pipeline.stage2_apply_high_quality_posts import run as apply_high_quality_posts

    if not apply_high_quality_posts(output_dir):
        return article
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    return SimpleNamespace(**metadata["article"])


def reddit_public_json_skip_reason_for_settings(settings) -> str:
    if settings.content_domain != "windows_help":
        return ""
    if settings.reddit_client_id and settings.reddit_client_secret:
        return ""
    if not settings.reddit_data_access_request_submitted_at:
        return ""
    return (
        "Reddit Data Access Request approval is pending, so public JSON collection is skipped "
        "until OAuth credentials are available."
    )


def build_research_report(
    settings,
    keyword: str,
    article,
    signals: list,
    reddit_diagnostics: dict | None = None,
    google_diagnostics: dict | None = None,
) -> dict:
    signal_queries = [signal.title for signal in signals[:4] if signal.title]
    signal_source_counts = Counter(signal.source for signal in signals)
    reddit_method_counts = Counter(
        (signal.metadata or {}).get("collection_method", "unknown")
        for signal in signals
        if signal.source in {"reddit", "reddit_fallback"}
    )
    google_method_counts = Counter(
        (signal.metadata or {}).get("collection_method", "unknown")
        for signal in signals
        if signal.source == "google_suggest"
    )
    queries = [keyword, f"{keyword} official", f"{keyword} beginner fix", *signal_queries]
    if settings.content_domain == "windows_help":
        queries.extend(
            [
                f"{keyword} Microsoft Support",
                f"{keyword} Microsoft Learn",
                f"{keyword} Windows release health",
            ]
        )
    sources = [
        {
            "name": source.get("name", ""),
            "url": source.get("url", ""),
            "type": "official_or_platform",
        }
        for source in article.sources
    ]
    if settings.content_domain == "windows_help":
        reader_questions = [
            f"What does {keyword} mean?",
            f"How do I fix {keyword} safely?",
            f"Should beginners try advanced fixes for {keyword}?",
            f"Can {keyword} cause data loss?",
            f"When should I get help for {keyword}?",
        ]
    else:
        reader_questions = [
            f"What is the easiest way to handle {keyword} in Korea?",
            f"What should foreign visitors prepare before using {keyword}?",
            f"What official links should I check for {keyword}?",
            f"What can go wrong with {keyword} during a Korea trip?",
            f"What backup option should I keep for {keyword}?",
        ]

    return {
        "site": settings.site_key,
        "content_domain": settings.content_domain,
        "seed_keyword": keyword,
        "topic": article.title,
        "queries": list(dict.fromkeys(queries))[:10],
        "sources": sources,
        "reader_questions": reader_questions,
        "signal_source_counts": dict(sorted(signal_source_counts.items())),
        "reddit_collection_method_counts": dict(sorted(reddit_method_counts.items())),
        "live_reddit_signal_count": signal_source_counts.get("reddit", 0),
        "reddit_oauth_signal_count": reddit_method_counts.get("oauth", 0),
        "reddit_public_json_signal_count": reddit_method_counts.get("public_json", 0),
        "fallback_reddit_signal_count": signal_source_counts.get("reddit_fallback", 0),
        "google_suggest_signal_count": signal_source_counts.get("google_suggest", 0),
        "google_suggest_live_signal_count": google_method_counts.get("live", 0),
        "google_suggest_fallback_signal_count": google_method_counts.get("fallback", 0),
        "google_suggest_method_counts": dict(sorted(google_method_counts.items())),
        "reddit_collection_diagnostics": reddit_diagnostics or {},
        "google_suggest_diagnostics": google_diagnostics or {},
        "notes": [
            "Reddit and Google Suggest are used for topic discovery.",
            "Official/platform sources are used for publishing validation.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1: collect signals, generate article, save outputs.")
    parser.add_argument("--seed", help="Topic seed keyword, for example: 'incheon airport to seoul'")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    output_dir = run(args.seed, args.site)
    print(output_dir)


if __name__ == "__main__":
    main()
