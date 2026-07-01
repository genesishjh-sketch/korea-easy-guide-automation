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
- write a daily seed plan before generation/publishing
- generate English article HTML/Markdown
- create an image plan and local fallback assets
- run the Hades Engineer quality gate
- publish to Blogger
- avoid duplicate public posts
- retry the next topic when an automatic publish candidate is already public
- validate launch queue topic quality before unattended publishing
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
- exact-match seed inventory
- launch queue inventory
- launch queue topic quality, including specific Windows categories and Microsoft source readiness
- daily workflow safety steps
- validate workflow trigger coverage
- public Blogger feed reachability
- local Google OAuth files
- Telegram notification settings

Launch queue quality can also be checked directly:

```bash
python -m src.pipeline.stage0_launch_queue_validate --site easy_pc_fix_guide
```

The command writes:

```text
reports/easy_pc_fix_guide-launch-queue-validation.json
```

Use `--generate --limit 2` when you want a stronger sample check that generates the first two launch topics and runs Hades validation without publishing:

```bash
python -m src.pipeline.stage0_launch_queue_validate --site easy_pc_fix_guide --generate --limit 2
```

## Reddit Research Mode

Easy PC Fix Guide now treats Reddit OAuth as an optional upgrade. The default zero-cost research path is:

```text
Google site:reddit.com searches -> Google Suggest -> official Microsoft validation
```

If public Reddit JSON returns 403 or Reddit OAuth is not approved yet, the pipeline still creates Reddit-intent signals with `site:reddit.com/r/...` Google search URLs. Publishing quality is guarded by Microsoft official sources and the Hades quality gate, not by Reddit OAuth approval.

Optional GitHub Secrets:

```text
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
```

Optional GitHub Variable:

```text
EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT
EASY_PC_FIX_GUIDE_REDDIT_DATA_ACCESS_REQUEST_SUBMITTED_AT
```

Setup links:

- Reddit apps: https://www.reddit.com/prefs/apps
- Reddit Data Access Request: https://support.reddithelp.com/hc/en-us/requests/new?tf_42139884615700=api_request_type_developer_clone&ticket_form_id=14868593862164
- Responsible Builder Policy: https://support.reddithelp.com/hc/articles/42728983564564
- GitHub Actions Secrets: https://github.com/genesishjh-sketch/korea-easy-guide-automation/settings/secrets/actions

Create the Reddit app as `script` only if you later want direct OAuth collection. If Reddit shows the Responsible Builder Policy/Data API registration message instead of creating the app, stop retrying and keep using the default Google site-search path. The health check never prints secret values; it only reports whether OAuth can collect live Reddit signals.

Current Reddit Data Access Request status:

```text
Submitted: 2026-06-25
Current mode: search-based Reddit research; publishing continues without Reddit OAuth.
Next step: no action required now. If Reddit approval arrives later, create the script app and store REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET as an optional upgrade.
```

Suggested Reddit app fields:

```text
name: Easy PC Fix Guide Automation
type: script
description/about url: blank is OK
redirect uri: http://localhost:8080
```

Secret mapping:

```text
REDDIT_CLIENT_ID = short client id shown under the Reddit app name
REDDIT_CLIENT_SECRET = secret shown in the Reddit app details
EASY_PC_FIX_GUIDE_REDDIT_USER_AGENT = easy-pc-fix-guide/0.1 by posting-automation-alert-bot
```

User action checklist:

```text
1. Keep the blog running with Google site:reddit.com search-based Reddit research.
2. Open https://www.reddit.com/prefs/apps.
3. Click create app or create another app.
4. Enter name: Easy PC Fix Guide Automation.
5. Select app type: script.
6. Enter redirect uri: http://localhost:8080.
7. If Reddit still blocks creation with the Responsible Builder Policy/Data API message, stop retrying and keep the OAuth upgrade optional.
8. Before pressing create app, complete the reCAPTCHA "I'm not a robot" check. If Reddit shows `Incorrect response. Try again.`, complete reCAPTCHA again and press create app again.
9. Copy the short client id under the app name into GitHub Secret REDDIT_CLIENT_ID.
10. Copy the app secret into GitHub Secret REDDIT_CLIENT_SECRET.
11. Run Actions > Easy PC Fix Reddit OAuth Health.
```

Data Access Request draft:

```text
Request type: Data Access Request
Role: I'm a developer
Inquiry: I'm a developer and want to build a Reddit App that does not work in the Devvit ecosystem.
Reddit account name: Primary-Tax3188
Purpose: read-only topic research for beginner Windows troubleshooting posts; no posting, voting, messaging, moderation, or Reddit write actions.
Source/platform URL: https://github.com/genesishjh-sketch/korea-easy-guide-automation
Target subreddits: r/WindowsHelp, r/Windows11, r/techsupport, r/pchelp
```

Manual health check:

```bash
python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide --notify
```

GitHub Actions health check:

```text
.github/workflows/easy-pc-reddit-health.yml
```

The health check writes `reports/easy_pc_fix_guide-reddit-health.json` and `reports/easy_pc_fix_guide-reddit-health.md`. The JSON file also embeds a `human_summary_markdown` field. Scheduled runs upload both files quietly; manual workflow runs can still send the same action summary to the Korean Posting Bot with `notify=true`.
It checks every configured subreddit and reports tested subreddits, matched subreddits, and per-subreddit signal counts when OAuth is configured. Missing OAuth is an optional-upgrade warning, not a publishing blocker.

## Daily Automation

Validate only, no Blogger publishing:

```bash
python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode validate
```

Preview the next topic seed without generating or publishing:

```bash
python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode plan --no-notify
```

Plan mode writes:

```text
reports/easy_pc_fix_guide-daily-seed-plan.json
```

It records the selected seed, candidate rotation, category, used/generated flags, and active seed source. The scheduled daily workflow writes this plan before Blogger/OAuth steps and uploads it with the generated output artifact.

Validate mode writes `reports/easy_pc_fix_guide-daily-validation-success.json` or
`reports/easy_pc_fix_guide-daily-validation-failure.json` so smoke tests do not
overwrite the latest real publishing report.

Public publish mode:

```bash
python -m src.pipeline.daily_draft --site easy_pc_fix_guide --mode publish
```

Publish, draft, duplicate-skip, and daily-limit results write
`reports/easy_pc_fix_guide-daily-success.json` or
`reports/easy_pc_fix_guide-daily-failure.json`.

Scheduled GitHub Actions publish at 09:10 KST daily:

```text
.github/workflows/easy-pc-daily.yml
```

The daily workflow runs regression tests and writes the daily seed plan before Blogger/OAuth steps. Sitemap submission runs only when `BLOGGER_PUBLISH_MODE` is `publish`.

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
- Windows posts include direct Microsoft sources, not only Microsoft search-result pages
- Related Guides include internal blog links for topic clustering

For `easy_pc_fix_guide`, launch queue topics must also:

- exist in `data/seeds/windows_topic_seeds.json`
- use a specific category instead of generic `Computer Help`
- have enough Microsoft official sources before unattended publishing
- remain free of duplicate or blank topic seeds

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
