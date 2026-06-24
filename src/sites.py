from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SiteProfile:
    key: str
    name: str
    url: str
    author: str
    content_domain: str
    seed_file: Path
    launch_seed_file: Path | None
    reddit_user_agent: str
    reddit_subreddits: list[str]
    automation_start_date: str = "2026-06-24"
    default_blogger_blog_id: str = ""
    default_search_console_site_url: str = ""
    default_ga4_measurement_id: str = ""
    output_dir: Path = field(default_factory=lambda: ROOT_DIR / "data" / "generated")


SITE_PROFILES = {
    "korea_easy_guide": SiteProfile(
        key="korea_easy_guide",
        name="Korea Easy Guide",
        url="https://koreaeasyguide.blogspot.com",
        author="Korea Easy Guide Editorial Team",
        content_domain="korea_travel",
        seed_file=ROOT_DIR / "data" / "seeds" / "topic_seeds.json",
        launch_seed_file=None,
        reddit_user_agent="korea-easy-guide/0.1",
        reddit_subreddits=["koreatravel", "korea", "Living_in_Korea", "travel", "solotravel"],
        automation_start_date="2026-06-24",
        default_blogger_blog_id="288143591612645486",
        default_search_console_site_url="https://koreaeasyguide.blogspot.com/",
        output_dir=ROOT_DIR / "data" / "generated" / "korea_easy_guide",
    ),
    "easy_pc_fix_guide": SiteProfile(
        key="easy_pc_fix_guide",
        name="Easy PC Fix Guide",
        url="https://easypcfixguide.blogspot.com",
        author="Easy PC Fix Guide Editorial Team",
        content_domain="windows_help",
        seed_file=ROOT_DIR / "data" / "seeds" / "windows_topic_seeds.json",
        launch_seed_file=ROOT_DIR / "data" / "seeds" / "windows_launch_queue.json",
        reddit_user_agent="easy-pc-fix-guide/0.1",
        reddit_subreddits=["WindowsHelp", "Windows11", "techsupport", "pchelp"],
        automation_start_date="2026-06-24",
        default_blogger_blog_id="8389138341810407852",
        default_search_console_site_url="https://easypcfixguide.blogspot.com/",
        output_dir=ROOT_DIR / "data" / "generated" / "easy_pc_fix_guide",
    ),
}


def get_site_profile(site_key: str | None) -> SiteProfile:
    selected = normalize_site_key(site_key)
    try:
        return SITE_PROFILES[selected]
    except KeyError as exc:
        valid = ", ".join(sorted(SITE_PROFILES))
        raise ValueError(f"Unknown site profile: {selected}. Valid values: {valid}") from exc


def normalize_site_key(site_key: str | None) -> str:
    return (site_key or "korea_easy_guide").strip() or "korea_easy_guide"
