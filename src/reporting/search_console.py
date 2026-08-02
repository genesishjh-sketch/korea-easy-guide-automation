from __future__ import annotations

from datetime import date
import time
from typing import Any

from googleapiclient.discovery import build

from src.config import Settings
from src.google_auth import SEARCH_CONSOLE_SUBMIT_SCOPE, get_credentials


URL_INSPECTION_ATTEMPTS = 3
URL_INSPECTION_RETRY_SECONDS = 2
TRANSIENT_INSPECTION_STATUSES = {429, 500, 502, 503, 504}
SEARCH_ANALYTICS_PAGE_SIZE = 25000


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

    def all_queries(
        self,
        start_date: date,
        end_date: date,
        *,
        page_size: int = SEARCH_ANALYTICS_PAGE_SIZE,
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        """Return the complete paginated query dataset for research backfills."""

        if not self.site_url:
            return {
                "status": "not_configured",
                "note": "SEARCH_CONSOLE_SITE_URL is missing.",
                "queries": [],
                "complete": False,
            }
        selected_page_size = max(1, min(int(page_size), SEARCH_ANALYTICS_PAGE_SIZE))
        selected_max_rows = (
            max(1, int(max_rows))
            if max_rows is not None
            else None
        )
        rows: list[dict[str, Any]] = []
        start_row = 0
        try:
            service = self._service(readonly=True)
            while True:
                remaining = (
                    selected_max_rows - len(rows)
                    if selected_max_rows is not None
                    else selected_page_size
                )
                if remaining <= 0:
                    break
                request_size = min(selected_page_size, remaining)
                response = (
                    service.searchanalytics()
                    .query(
                        siteUrl=self.site_url,
                        body={
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                            "dimensions": ["query"],
                            "dataState": "all",
                            "rowLimit": request_size,
                            "startRow": start_row,
                        },
                    )
                    .execute()
                )
                page = list(response.get("rows") or [])
                rows.extend(page)
                if len(page) < request_size:
                    return {
                        "status": "connected",
                        "site_url": self.site_url,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "queries": [_query_row(item) for item in rows],
                        "row_count": len(rows),
                        "complete": True,
                        "next_start_row": "",
                    }
                start_row += len(page)
            return {
                "status": "connected",
                "site_url": self.site_url,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "queries": [_query_row(item) for item in rows],
                "row_count": len(rows),
                "complete": False,
                "next_start_row": start_row,
                "note": "max_rows stopped pagination before source exhaustion",
            }
        except Exception as exc:
            return {
                "status": "error",
                "site_url": self.site_url,
                "error": str(exc),
                "queries": [_query_row(item) for item in rows],
                "row_count": len(rows),
                "complete": False,
                "next_start_row": start_row,
            }

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

    def list_sitemaps(self) -> dict[str, Any]:
        if not self.site_url:
            return {"status": "not_configured", "note": "SEARCH_CONSOLE_SITE_URL is missing."}
        try:
            response = self._service(readonly=True).sitemaps().list(siteUrl=self.site_url).execute()
            sitemaps = []
            for item in response.get("sitemap", []):
                contents = item.get("contents", [])
                sitemaps.append(
                    {
                        "path": item.get("path", ""),
                        "last_submitted": item.get("lastSubmitted", ""),
                        "last_downloaded": item.get("lastDownloaded", ""),
                        "is_pending": bool(item.get("isPending", False)),
                        "is_sitemaps_index": bool(item.get("isSitemapsIndex", False)),
                        "errors": int(item.get("errors", 0) or 0),
                        "warnings": int(item.get("warnings", 0) or 0),
                        "contents": [
                            {
                                "type": content.get("type", ""),
                                "submitted": int(content.get("submitted", 0) or 0),
                                "indexed": int(content.get("indexed", 0) or 0),
                            }
                            for content in contents
                        ],
                    }
                )
            return {"status": "connected", "site_url": self.site_url, "sitemaps": sitemaps}
        except Exception as exc:
            return {"status": "error", "site_url": self.site_url, "error": str(exc), "sitemaps": []}

    def inspect_url(self, inspected_url: str) -> dict[str, Any]:
        return self.inspect_urls([inspected_url])[0]

    def inspect_urls(self, inspected_urls: list[str]) -> list[dict[str, Any]]:
        if not self.site_url:
            return [{"status": "not_configured", "url": url} for url in inspected_urls]
        try:
            credentials = get_credentials(self.settings, [SEARCH_CONSOLE_SUBMIT_SCOPE])
            service = build("searchconsole", "v1", credentials=credentials)
            results = []
            for inspected_url in inspected_urls:
                for attempt in range(URL_INSPECTION_ATTEMPTS):
                    try:
                        response = (
                            service.urlInspection()
                            .index()
                            .inspect(
                                body={
                                    "inspectionUrl": inspected_url,
                                    "siteUrl": self.site_url,
                                    "languageCode": "en-US",
                                }
                            )
                            .execute()
                        )
                        results.append(parse_index_inspection(inspected_url, response))
                        break
                    except Exception as exc:
                        if (
                            attempt < URL_INSPECTION_ATTEMPTS - 1
                            and is_transient_inspection_error(exc)
                        ):
                            time.sleep(URL_INSPECTION_RETRY_SECONDS)
                            continue
                        results.append(
                            {
                                "status": "error",
                                "site_url": self.site_url,
                                "url": inspected_url,
                                "error": str(exc),
                            }
                        )
                        break
            return results
        except Exception as exc:
            return [
                {"status": "error", "site_url": self.site_url, "url": url, "error": str(exc)}
                for url in inspected_urls
            ]

    def search_performance(self, start_date: date, end_date: date) -> dict[str, Any]:
        if not self.site_url:
            return {"status": "not_configured", "note": "SEARCH_CONSOLE_SITE_URL is missing."}
        try:
            service = self._service(readonly=True)
            base_query = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dataState": "all",
            }
            totals_response = service.searchanalytics().query(siteUrl=self.site_url, body=base_query).execute()
            page_response = (
                service.searchanalytics()
                .query(
                    siteUrl=self.site_url,
                    body={**base_query, "dimensions": ["page"], "rowLimit": 25000},
                )
                .execute()
            )
            totals = (totals_response.get("rows") or [{}])[0]
            pages = page_response.get("rows", [])
            return {
                "status": "connected",
                "site_url": self.site_url,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "page_count_with_search_data": len(pages),
                "clicks": int(totals.get("clicks", 0) or 0),
                "impressions": int(totals.get("impressions", 0) or 0),
                "ctr": float(totals.get("ctr", 0) or 0),
                "position": float(totals.get("position", 0) or 0),
            }
        except Exception as exc:
            return {"status": "error", "site_url": self.site_url, "error": str(exc)}

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


def _query_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": str((row.get("keys") or [""])[0]),
        "clicks": float(row.get("clicks", 0) or 0),
        "impressions": float(row.get("impressions", 0) or 0),
        "ctr": float(row.get("ctr", 0) or 0),
        "position": float(row.get("position", 0) or 0),
    }


def parse_index_inspection(inspected_url: str, response: dict[str, Any]) -> dict[str, Any]:
    index_status = response.get("inspectionResult", {}).get("indexStatusResult", {})
    return {
        "status": "connected",
        "url": inspected_url,
        "verdict": index_status.get("verdict", "VERDICT_UNSPECIFIED"),
        "coverage_state": index_status.get("coverageState", ""),
        "page_fetch_state": index_status.get("pageFetchState", ""),
        "last_crawl_time": index_status.get("lastCrawlTime", ""),
        "robots_txt_state": index_status.get("robotsTxtState", ""),
        "indexing_state": index_status.get("indexingState", ""),
        "user_canonical": index_status.get("userCanonical", ""),
        "google_canonical": index_status.get("googleCanonical", ""),
        "referring_urls": index_status.get("referringUrls", []),
        "sitemap": index_status.get("sitemap", []),
    }


def is_transient_inspection_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None)
    if status in TRANSIENT_INSPECTION_STATUSES:
        return True
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "http error 429",
            "httperror 429",
            "http error 500",
            "httperror 500",
            "http error 502",
            "httperror 502",
            "http error 503",
            "httperror 503",
            "http error 504",
            "httperror 504",
            "internal error encountered",
            "backend error",
            "service unavailable",
            "timed out",
            "timeout",
            "temporary failure",
            "connection reset",
            "connection aborted",
            "name or service not known",
        )
    )


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
