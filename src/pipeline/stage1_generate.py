from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
from pathlib import Path

from src.collectors.google import GoogleSuggestCollector
from src.collectors.reddit import RedditCollector
from src.config import ROOT_DIR, load_settings
from src.content.generator import EnglishArticleGenerator
from src.content.topic_scoring import build_candidate
from src.content.windows_generator import WindowsArticleGenerator
from src.images.ai_plan import build_article_image_plan
from src.images.local_svg import create_korea_svg_assets
from src.images.local_svg import create_windows_svg_assets
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

    reddit = RedditCollector(
        settings.reddit_user_agent,
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        subreddits=settings.reddit_subreddits,
    )
    google = GoogleSuggestCollector()
    signals = reddit.collect(keyword, limit=6) + google.collect(keyword, limit=8)

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
    if image_plan.images[0].filename.endswith(".svg"):
        if settings.content_domain == "windows_help":
            create_windows_svg_assets(output_dir, article.title, keyword)
        else:
            create_korea_svg_assets(output_dir, article.title, keyword)
    (output_dir / "research_report.json").write_text(
        json.dumps(build_research_report(settings, keyword, article, signals), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Saved article to %s", output_dir)
    return output_dir


def build_research_report(settings, keyword: str, article, signals: list) -> dict:
    signal_queries = [signal.title for signal in signals[:4] if signal.title]
    signal_source_counts = Counter(signal.source for signal in signals)
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
    return {
        "site": settings.site_key,
        "topic": article.title,
        "queries": list(dict.fromkeys(queries))[:10],
        "sources": sources,
        "reader_questions": [
            f"What does {keyword} mean?",
            f"How do I fix {keyword} safely?",
            f"Should beginners try advanced fixes for {keyword}?",
            f"Can {keyword} cause data loss?",
            f"When should I get help for {keyword}?",
        ],
        "signal_source_counts": dict(sorted(signal_source_counts.items())),
        "live_reddit_signal_count": signal_source_counts.get("reddit", 0),
        "fallback_reddit_signal_count": signal_source_counts.get("reddit_fallback", 0),
        "google_suggest_signal_count": signal_source_counts.get("google_suggest", 0),
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
