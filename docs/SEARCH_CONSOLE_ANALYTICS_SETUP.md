# Search Console and GA4 Setup

## Goal

Connect Korea Easy Guide to:

- Google Search Console for search queries, impressions, clicks, CTR, and average position.
- Google Analytics 4 for page views, active users, engagement, and top pages.

## Required APIs

Enable these APIs in the same Google Cloud project used by the Blogger OAuth client:

- Google Search Console API
- Google Analytics Data API

## Environment Variables

```text
SEARCH_CONSOLE_SITE_URL=https://koreaeasyguide.blogspot.com/
GA4_MEASUREMENT_ID=G-XXXXXXXXXX
GA4_PROPERTY_ID=123456789
```

`GA4_MEASUREMENT_ID` is used in Blogger/theme setup.

`GA4_PROPERTY_ID` is used by the reporting API. It is numeric and is different from the `G-...` measurement ID.

## Search Console Setup

1. Open Google Search Console.
2. Add URL-prefix property:

```text
https://koreaeasyguide.blogspot.com/
```

3. Verify ownership using the same logged-in Google account that owns the Blogger blog.
4. Submit sitemap:

```text
https://koreaeasyguide.blogspot.com/sitemap.xml
```

After API credentials are authorized, the project can also submit the sitemap:

```bash
python -m src.pipeline.stage3_submit_sitemap
```

Note: Google does not provide a general public API for requesting indexing of ordinary blog posts. URL Inspection can be done in Search Console UI.

## GA4 Setup

1. Create or open a Google Analytics 4 property.
2. Create a Web data stream for:

```text
https://koreaeasyguide.blogspot.com/
```

3. Copy the Measurement ID:

```text
G-XXXXXXXXXX
```

4. Add the GA4 tag to Blogger theme or Blogger's Google Analytics setting if available.
5. Copy the numeric GA4 Property ID from Admin settings and set:

```text
GA4_PROPERTY_ID=123456789
```

## Weekly Report

Once connected:

```bash
python -m src.pipeline.stage3_weekly_report
```

The report includes:

- Search Console top queries
- Clicks
- Impressions
- Average position
- GA4 top pages
- Views
- Active users
- Engagement rate
