from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import ROOT_DIR
from src.pipeline.stage1_generate import run as run_stage1
from src.pipeline.stage2_publish import run as run_stage2


def used_keywords() -> set[str]:
    values = set()
    for path in (ROOT_DIR / "data" / "generated").glob("*/*/metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidate = metadata.get("candidate", {})
        keyword = candidate.get("keyword")
        if keyword:
            values.add(keyword.lower())
    return values


def choose_seed(explicit_seed: str | None = None) -> str:
    if explicit_seed:
        return explicit_seed
    seeds = json.loads((ROOT_DIR / "data" / "seeds" / "topic_seeds.json").read_text(encoding="utf-8"))
    used = used_keywords()
    for seed in seeds:
        if seed.lower() not in used:
            return seed
    return seeds[0]


def run(seed: str | None = None) -> dict[str, str]:
    selected_seed = choose_seed(seed)
    article_dir = run_stage1(selected_seed)
    result_path = run_stage2(article_dir=article_dir, mode="draft")
    return {
        "seed": selected_seed,
        "article_dir": str(article_dir),
        "publish_result": str(result_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily pipeline: collect, generate, and upload a Blogger draft.")
    parser.add_argument("--seed", help="Optional explicit topic seed")
    args = parser.parse_args()
    result = run(args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
