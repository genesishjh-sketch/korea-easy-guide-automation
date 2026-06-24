from __future__ import annotations

from datetime import date
from typing import Any

from googleapiclient.discovery import build

from src.config import Settings
from src.google_auth import SEARCH_CONSOLE_SUBMIT_SCOPE, get_credentials


class SearchConsoleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.site_url = normalize_site_url(settings.search_console_site_url or settings.site_url)

    def summary(self, start_date: date, end_date: date) -> dict[str, Any]:
        if not self.site_url:
            return {"status": "not_configured", "note": "SEARCH_CONSOLE_SITE_URL is missing."}
        try:
            service = self._service(readonly=True)
            query = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query"],
                "rowLimit": 10,
            }
            response = service.searchanalytics().query(siteUrl=self.site_url, body=query).execute()
            rows = response.get("rows", [])
            totals = {
                "clicks": sum(row.get("clicks", 0) for row in rows),
                "impressions": sum(row.get("impressions", 0) for row in rows),
                "ctr": _weighted_ctr(rows),
                "position": _weighted_position(rows),
            }
            return {
                "status": "connected",
                "site_url": self.site_url,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "totals_from_top_queries": totals,
                "top_queries": [
                    {
                        "query": row.get("keys", [""])[0],
                        "clicks": row.get("clicks", 0),
                        "impressions": row.get("impressions", 0),
                        "ctr": row.get("ctr", 0),
                        "position": row.get("position", 0),
                    }
                    for row in rows
                ],
            }
        except Exception as exc:
            return {"status": "error", "site_url": self.site_url, "error": str(exc)}

    def indexed_page_estimate(self, start_date: date, end_date: date) -> dict[str, Any]:
        if not self.site_url:
            return {"status": "not_configured", "note": "SEARCH_CONSOLE_SITE_URL is missing."}
        try:
            service = self._service(readonly=True)
            response = (
                service.searchanalytics()
                .query(
                    siteUrl=self.site_url,
                    body={
                        "startDate": start_date.isoformat(),
                        "endDate": end_date.isoformat(),
                        "dimensions": ["page"],
                        "rowLimit": 250,
                    },
                )
                .execute()
            )
            pages = [
                {
                    "url": row.get("keys", [""])[0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                }
                for row in response.get("rows", [])
            ]
            return {
                "status": "connected",
                "page_count_with_search_data": len(pages),
                "pages": pages,
            }
        except Exception as exc:
            return {"status": "error", "site_url": self.site_url, "error": str(exc)}

    def submit_sitemap(self, sitemap_url: str) -> dict[str, Any]:
        try:
            service = self._service(readonly=False)
            service.sitemaps().submit(siteUrl=self.site_url, feedpath=sitemap_url).execute()
            return {"status": "submitted", "site_url": self.site_url, "sitemap_url": sitemap_url}
        except Exception as exc:
            return {"status": "error", "site_url": self.site_url, "sitemap_url": sitemap_url, "error": str(exc)}

    def _service(self, readonly: bool):
        credentials = get_credentials(self.settings, [SEARCH_CONSOLE_SUBMIT_SCOPE])
        return build("webmasters", "v3", credentials=credentials)


def normalize_site_url(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("sc-domain:"):
        return value
    if not value.endswith("/"):
        value += "/"
    return value


def _weighted_ctr(rows: list[dict]) -> float:
    impressions = sum(row.get("impressions", 0) for row in rows)
    if not impressions:
        return 0.0
    clicks = sum(row.get("clicks", 0) for row in rows)
    return clicks / impressions


def _weighted_position(rows: list[dict]) -> float:
    impressions = sum(row.get("impressions", 0) for row in rows)
    if not impressions:
        return 0.0
    return sum(row.get("position", 0) * row.get("impressions", 0) for row in rows) / impressions
