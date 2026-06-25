# Korea Easy Guide Automation

Multi-site Python automation for Blogger-based English blogs.

Current sites:

- `korea_easy_guide`: Korea travel and daily-life guide
- `easy_pc_fix_guide`: beginner Windows troubleshooting guide

The active production focus is `easy_pc_fix_guide` at:

```text
https://easypcfixguide.blogspot.com
```

## What It Does

The pipeline can:

- collect topic signals from Reddit and Google suggestions
- select a topic seed
- generate English article HTML/Markdown
- create an image plan and local fallback assets
- run the Hades Engineer quality gate
- publish to Blogger
- avoid duplicate public posts
- retry the next topic when an automatic publish candidate is already public
- submit the Blogger sitemap to Search Console after publish runs
- send Korean Telegram Posting Bot reports
- generate Korean weekly reports with Blogger feed, Search Console, and GA4 data

## Setup

```bash
cd korea_blog_automation
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Use Python 3.11 for local runs. GitHub Actions is also pinned to Python 3.11, so keeping the local virtualenv on the same runtime avoids dependency drift between manual checks and scheduled publishing.

Set `SITE_KEY` or pass `--site` for multi-site commands.

## Easy PC Preflight

Run this before changing schedules, secrets, or publish mode:

```bash
python -m src.pipeline.stage0_preflight --site easy_pc_fix_guide
```

The command writes:

```text
reports/easy_pc_fix_guide-preflight.json
```

It checks:

- site settings
- topic seed count
- daily workflow safety steps
- validate workflow trigger coverage
- public Blogger feed reachability
- local Google OAuth files
- Telegram notification settings

## Reddit OAuth Health

Easy PC Fix Guide can publish with fallback reader questions, but Reddit OAuth is required before topic discovery is considered stable enough for future cadence increases.

Required GitHub Secrets:

```text
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
```

Recommended GitHub Variable:

```text
EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT
```

Setup links:

- Reddit apps: https://www.reddit.com/prefs/apps
- GitHub Actions Secrets: https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions

Create the Reddit app as `script`, then copy the app client id and secret into the two GitHub Secrets above. The health check never prints secret values; it only reports whether OAuth can collect live Reddit signals.

Manual health check:

```bash
python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide --notify
```

GitHub Actions health check:

```text
.github/workflows/easy-pc-reddit-health.yml
```

The health check writes `reports/easy_pc_fix_guide-reddit-health.json`, prints a sanitized action summary in the Actions log, uploads the report as an artifact, and sends the same action summary to the Korean Posting Bot when Telegram is configured.

## Daily Automation

Validate only, no Blogger publishing:

```bash
python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode validate
```

Public publish mode:

```bash
python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode publish
```

Scheduled GitHub Actions publish at 09:10 KST daily:

```text
.github/workflows/easy-pc-daily.yml
```

The daily workflow runs regression tests before Blogger/OAuth steps. Sitemap submission runs only when `BLOGGER_PUBLISH_MODE` is `publish`.

## Weekly Report

```bash
python -m src.pipeline.stage3_weekly_report --site easy_pc_fix_guide
```

The weekly report is Korean and includes:

- local generated article results
- Blogger public feed confirmation
- static page status
- Search Console summary
- GA4 summary
- cadence review for 1 -> 2 -> 3 posts/day

## Safety Rules

Public publishing is blocked unless:

- Hades score is at least 90
- issue count is zero
- required sections exist
- two images exist
- research report exists
- official/platform sources exist
- Windows posts include safety fields such as risk level, data loss risk, estimated time, and last checked

See:

```text
docs/PUBLISHING_RULES.md
docs/CONTENT_QUALITY_STANDARD.md
docs/IMAGE_RULES.md
```

## Tests

```bash
python -m unittest discover -v
```

Tests cover:

- duplicate publish protection
- retrying the next seed after duplicate automatic candidates
- Windows safety/content blocks
- sitemap notification messages
- weekly report public feed logic
- workflow safety conditions
- preflight checks
