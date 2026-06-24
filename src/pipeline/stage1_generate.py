from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from src.collectors.google import GoogleSuggestCollector
from src.collectors.reddit import RedditCollector
from src.config import ROOT_DIR, load_settings
from src.content.generator import EnglishArticleGenerator
from src.content.topic_scoring import build_candidate
from src.images.ai_plan import build_article_image_plan
from src.storage.article_store import ArticleStore


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("stage1")


def load_seed(default_seed: str | None) -> str:
    if default_seed:
        return default_seed
    seeds_path = ROOT_DIR / "data" / "seeds" / "topic_seeds.json"
    seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
    return seeds[0]


def run(seed: str | None = None) -> Path:
    settings = load_settings()
    keyword = load_seed(seed)
    LOGGER.info("Collecting signals for keyword: %s", keyword)

    reddit = RedditCollector(
        settings.reddit_user_agent,
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
    )
    google = GoogleSuggestCollector()
    signals = reddit.collect(keyword, limit=6) + google.collect(keyword, limit=8)

    candidate = build_candidate(keyword, signals)
    LOGGER.info("Selected topic category=%s score=%s", candidate.category, candidate.score)

    generator = EnglishArticleGenerator(settings)
    provisional_plan = build_article_image_plan(candidate, f"{keyword} guide")
    provisional_article = generator.generate(
        candidate,
        provisional_plan.hero_asset(),
        provisional_plan.inline_assets(),
    )
    image_plan = build_article_image_plan(candidate, provisional_article.title)
    article = generator.generate(candidate, image_plan.hero_asset(), image_plan.inline_assets())

    store = ArticleStore()
    output_dir = store.save(article, candidate)
    (output_dir / "image_plan.json").write_text(
        json.dumps(image_plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Saved article to %s", output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1: collect signals, generate article, save outputs.")
    parser.add_argument("--seed", help="Topic seed keyword, for example: 'incheon airport to seoul'")
    args = parser.parse_args()
    output_dir = run(args.seed)
    print(output_dir)


if __name__ == "__main__":
    main()
