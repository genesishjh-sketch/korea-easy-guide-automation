from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.reporting.analytics import GA4Client
from src.reporting.analytics import hostname_filter
from src.reporting.analytics import site_hostname


class GA4ClientTests(unittest.TestCase):
    def test_site_hostname_extracts_blogspot_host(self) -> None:
        self.assertEqual(site_hostname("https://koreaeasyguide.blogspot.com"), "koreaeasyguide.blogspot.com")
        self.assertEqual(site_hostname("easypcfixguide.blogspot.com"), "easypcfixguide.blogspot.com")

    def test_hostname_filter_uses_exact_host_name(self) -> None:
        self.assertEqual(
            hostname_filter("koreaeasyguide.blogspot.com"),
            {
                "dimensionFilter": {
                    "filter": {
                        "fieldName": "hostName",
                        "stringFilter": {
                            "matchType": "EXACT",
                            "value": "koreaeasyguide.blogspot.com",
                        },
                    }
                }
            },
        )

    def test_summary_filters_shared_ga4_property_by_site_hostname(self) -> None:
        settings = SimpleNamespace(
            ga4_property_id="336981737",
            site_url="https://easypcfixguide.blogspot.com",
        )
        service = FakeAnalyticsService(
            {
                "rows": [
                    {
                        "dimensionValues": [{"value": "/"}],
                        "metricValues": [{"value": "29"}, {"value": "6"}, {"value": "0.75"}, {"value": "31.2"}],
                    }
                ]
            }
        )

        with patch.object(GA4Client, "_service", return_value=service):
            summary = GA4Client(settings).summary(date(2026, 6, 22), date(2026, 6, 29))

        self.assertEqual(summary["status"], "connected")
        self.assertEqual(summary["hostname_filter"], "easypcfixguide.blogspot.com")
        self.assertEqual(service.captured_property, "properties/336981737")
        self.assertEqual(
            service.captured_body["dimensionFilter"]["filter"]["stringFilter"]["value"],
            "easypcfixguide.blogspot.com",
        )
        self.assertEqual(summary["top_pages"][0]["views"], 29)


class FakeAnalyticsService:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.captured_property = ""
        self.captured_body = {}

    def properties(self):
        return self

    def runReport(self, property: str, body: dict):
        self.captured_property = property
        self.captured_body = body
        return self

    def execute(self):
        return self.response


if __name__ == "__main__":
    unittest.main()
