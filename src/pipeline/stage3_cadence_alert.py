from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from src.config import load_settings
from src.notifications.telegram import NotificationClient
from src.publishing.blogger import BloggerCredentialsError, BloggerPublisher
from src.reporting.cadence import (
    THREE_POST_REVIEW_DATE,
    TWO_POST_REVIEW_DATE,
    build_cadence_alert_message,
    review_cadence,
)
from src.reporting.search_console import SearchConsoleClient
from src.reporting.weekly import KST, WeeklyReporter


def run(today: date | None = None, force: bool = False, site: str | None = None, verbose: bool = True) -> bool:
    settings = load_settings(site)
    selected_date = today or datetime.utcnow().date()

    if not force and selected_date not in {TWO_POST_REVIEW_DATE, THREE_POST_REVIEW_DATE}:
        if verbose:
            print(f"No cadence alert scheduled for {selected_date.isoformat()}.")
        return False

    week_start = selected_date - timedelta(days=7)
    reporter = WeeklyReporter(settings)
    articles = reporter._collect_articles(week_start=datetime.combine(week_start, datetime.min.time()))
    published_count = actual_public_post_count(settings, articles)
    quality_issue_count = reporter._quality_issue_count(articles)
    signal_quality = reporter._signal_quality_result(articles)
    operations = reporter._operations_result(now=datetime.combine(selected_date, datetime.min.time(), tzinfo=KST))

    search_console_client = SearchConsoleClient(settings)
    search_console = search_console_client.summary(week_start, selected_date)
    indexed_pages = search_console_client.indexed_page_estimate(week_start, selected_date)
    review = review_cadence(
        today=selected_date,
        published_posts=published_count,
        indexed_pages_estimate=indexed_pages.get("page_count_with_search_data", 0),
        recent_impressions=search_console.get("totals_from_top_queries", {}).get("impressions", 0),
        quality_issue_count=quality_issue_count,
        signal_quality=signal_quality,
        reddit_health=operations.get("reddit_health", {}),
    )

    message = build_cadence_alert_message(
        settings.site_name,
        settings.site_url,
        review,
        reddit_user_agent=settings.reddit_user_agent,
    )
    NotificationClient(settings).send_required(message)
    if verbose:
        print(message)
        print("sent: True")
    return True


def actual_public_post_count(settings, articles: list[dict]) -> int:
    try:
        return BloggerPublisher(settings).public_post_count()
    except BloggerCredentialsError:
        return sum(1 for item in articles if item.get("blogger_status") == "LIVE")
    except Exception:
        return sum(1 for item in articles if item.get("blogger_status") == "LIVE")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a Posting Bot alert on cadence review dates.")
    parser.add_argument("--date", help="Override date in YYYY-MM-DD format.")
    parser.add_argument("--force", action="store_true", help="Send alert even if today is not a review date.")
    parser.add_argument("--site", help="Site profile key, for example: easy_pc_fix_guide")
    args = parser.parse_args()
    selected_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    run(today=selected_date, force=args.force, site=args.site)


if __name__ == "__main__":
    main()
