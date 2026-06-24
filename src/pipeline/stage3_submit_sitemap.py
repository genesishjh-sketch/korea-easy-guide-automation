from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import ROOT_DIR, load_settings
from src.reporting.search_console import SearchConsoleClient


def run(sitemap_url: str | None = None) -> Path:
    settings = load_settings()
    selected_sitemap = sitemap_url or f"{settings.site_url.rstrip('/')}/sitemap.xml"
    result = SearchConsoleClient(settings).submit_sitemap(selected_sitemap)

    output_dir = ROOT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "search-console-sitemap-submit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit Blogger sitemap to Google Search Console.")
    parser.add_argument("--sitemap-url", help="Defaults to SITE_URL/sitemap.xml")
    args = parser.parse_args()
    print(run(args.sitemap_url))


if __name__ == "__main__":
    main()
