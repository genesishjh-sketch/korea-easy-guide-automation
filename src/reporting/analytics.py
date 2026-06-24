from __future__ import annotations

from datetime import date
from typing import Any

from googleapiclient.discovery import build

from src.config import Settings
from src.google_auth import ANALYTICS_READONLY_SCOPE, get_credentials


class GA4Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.property_id = settings.ga4_property_id.strip()

    def summary(self, start_date: date, end_date: date) -> dict[str, Any]:
        if not self.property_id:
            return {"status": "not_configured", "note": "GA4_PROPERTY_ID is missing."}
        try:
            service = self._service()
            response = (
                service.properties()
                .runReport(
                    property=f"properties/{self.property_id}",
                    body={
                        "dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}],
                        "dimensions": [{"name": "pagePath"}],
                        "metrics": [
                            {"name": "screenPageViews"},
                            {"name": "activeUsers"},
                            {"name": "engagementRate"},
                            {"name": "averageSessionDuration"},
                        ],
                        "limit": 10,
                        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
                    },
                )
                .execute()
            )
            rows = response.get("rows", [])
            return {
                "status": "connected",
                "property_id": self.property_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "top_pages": [_parse_row(row) for row in rows],
            }
        except Exception as exc:
            return {"status": "error", "property_id": self.property_id, "error": str(exc)}

    def _service(self):
        credentials = get_credentials(self.settings, [ANALYTICS_READONLY_SCOPE])
        return build("analyticsdata", "v1beta", credentials=credentials)


def _parse_row(row: dict[str, Any]) -> dict[str, Any]:
    dimensions = row.get("dimensionValues", [])
    metrics = row.get("metricValues", [])
    return {
        "page_path": dimensions[0].get("value", "") if dimensions else "",
        "views": _number(metrics, 0),
        "active_users": _number(metrics, 1),
        "engagement_rate": _float(metrics, 2),
        "average_session_duration": _float(metrics, 3),
    }


def _number(metrics: list[dict], index: int) -> int:
    try:
        return int(float(metrics[index].get("value", 0)))
    except (IndexError, ValueError):
        return 0


def _float(metrics: list[dict], index: int) -> float:
    try:
        return float(metrics[index].get("value", 0))
    except (IndexError, ValueError):
        return 0.0
