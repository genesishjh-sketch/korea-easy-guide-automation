# Publishing Rules

## Cadence

- Publish three new posts per blog every day, including weekends, unless the quality gate blocks a candidate.
- Target public publish time: 09:00 KST.
- Daily GitHub Actions publishing runs at 09:10 KST with a 09:25 KST backup run.
- The daily limit guard must stop the backup run from publishing a duplicate post if the primary run already published or found a valid same-day post.
- Send a Posting Bot daily result report every morning after the daily pipeline finishes.
- Send a Posting Bot cadence review alert in the weekly report before increasing daily post count.
- Do not imitate low-quality mass publishing. The default operating limit is three posts per blog per day, and weak candidates must be skipped rather than used to fill quota.
- If the daily post fails quality checks, skip publishing instead of lowering the standard.

## Daily Topic Mix

For each blog, the normal three-post day uses this mix:

- Slot 1: evergreen search demand.
- Slot 2: evergreen search demand.
- Slot 3: trend, seasonal, urgent, or recent-issue demand.

Examples:

- Korea Easy Guide evergreen: airport routes, eSIM, maps, KTX, payment, delivery, accommodation.
- Korea Easy Guide trend/seasonal: rainy season, heatwave, winter snow, Chuseok/Seollal travel, public holiday transport, airport congestion, lost passport or emergency topics.
- Easy PC Fix Guide evergreen: Windows error codes, Wi-Fi, Microsoft Store, printer, sound, file explorer, beginner settings.
- Easy PC Fix Guide trend/recent issue: problems after latest Windows update, cumulative update install errors, blue screen after update, Wi-Fi/sound/printer broken after update.

Trend slots still require official-source verification and Hades approval. If no safe trend/seasonal candidate passes duplicate and quality checks, the slot falls back to an evergreen topic.

## Cadence Review

- Current operating cadence is three posts per blog per day.
- Do not increase beyond three posts per blog per day without a separate review.
- If Search Console shows crawl/indexing trouble, repeated quality issues, or weak impressions after several weeks, reduce cadence before lowering quality.
- A higher-cadence review requires roughly 50+ published posts, improving Search Console indexed/visible pages, no unresolved quality issues, and preferably visible impression growth.
- Cadence increase review also requires stable topic discovery. Google `site:reddit.com` search signals, Google Suggest signals, official-source coverage, and Hades quality results are enough for normal operation. Reddit OAuth is optional.
- Posting Bot should alert when cadence, indexing, or quality should be reviewed.

## Automation Mode

- The target operating mode is full automation.
- The pipeline must create the topic, article, image plan, images, quality report, Blogger post, and weekly report without manual editorial approval.
- Manual review is replaced by the automated Hades Engineer quality gate.
- Posting Bot must report daily success or failure, including title, Blogger status, URL, quality score, and action notes.
- Validate-only smoke tests must write `daily-validation-success.json` or `daily-validation-failure.json`; they must not overwrite `daily-success.json` or `daily-failure.json`, which are reserved for publish/draft/daily-limit operational results.
- Reddit OAuth credentials are optional. If Reddit public JSON is blocked or OAuth is unavailable, the pipeline should use Google `site:reddit.com` search-intent signals before falling back to local reader questions.
- Research reports and weekly reports must separate Reddit OAuth signals, Reddit public JSON signals, Reddit Google search signals, and Reddit fallback signals so collection quality is visible.
- If weekly reports show only fallback reader questions and no Google site-search/OAuth/public signals, treat it as a topic-discovery warning.
- Run `python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide --notify` only when you want to check optional Reddit OAuth status and send the result to Posting Bot.

## Hades Engineer Quality Gate

Every post must pass automated review before Blogger publishing.

Required checks:

- At least 1,400 English words.
- Required article sections:
  - Quick Answer
  - Before You Start
  - Step-by-Step Guide
  - Costs / Payment
  - Common Problems
  - Useful Tips for Foreign Visitors
  - FAQ
  - Official Links to Check
- At least two images:
  - `assets/ai-hero.jpg` or `assets/ai-hero.svg`
  - `assets/ai-inline-1.jpg` or `assets/ai-inline-1.svg`
- At least four official or platform source links in the article.
- For app, transport, ticket, SIM/eSIM, taxi, map, delivery, shopping, and booking posts, include useful action links such as official app-store pages, official booking pages, operator pages, and government/tourism pages.
- At least five FAQ questions.
- A `research_report.json` file must exist for every public post.
- Research must include at least:
  - six search queries
  - six source records
  - three official or platform sources
  - five reader questions or search intents
- Windows help posts must include at least four official Microsoft links in the article and research report.
- Windows help posts must include at least two direct Microsoft support, Learn, release-health, or product pages. Microsoft search-result URLs are useful fallback links, but they do not count as direct source depth.
- Meta description and tags must exist.
- Placeholder, generic old-template, and AI refusal phrases are blocked.

The post is publishable only when:

```text
Hades score >= 90
and issue count == 0
```

## Image Rules

- Do not call paid image APIs from the Python pipeline.
- GitHub Actions for unattended publishing must not receive paid or external image API keys such as `OPENAI_API_KEY`, `OPENAI_IMAGES_API_KEY`, or `PEXELS_API_KEY`.
- The preflight check must fail if paid image API keys are wired into unattended workflows.
- If paid/external image API keys exist only in the local shell, preflight should warn so the operator can confirm they are not used by scheduled publishing.
- Each generated post must include `image_plan.json`.
- Public posts must use fresh article-specific Codex-generated raster images.
- Reusable library images under `src/images/ai_assets/korea/` or `src/images/ai_assets/windows/` are draft aids only and must not be used for public publishing.
- Public publishing may only use unique hosted assets under `src/images/ai_assets/hosted/`.
- Do not reuse an image URL that already appears in a published Blogger post.
- Do not use `general` fallback images for public posts.
- Local SVG assets are not allowed for public posts.
- If required image files are missing, Blogger publishing must stop.

## Repeat-Until-Quality Rule

The automation should improve and re-check a post until it passes the Hades gate.

For unattended scheduled publishing, the pipeline must not lower quality criteria. If the selected
candidate fails the Hades gate, the daily publisher may try the next scheduled topic candidate and
run the full generation -> image -> Hades -> publish check again. The Posting Bot daily report must
show which topic seeds were skipped because of quality failure.

Allowed improvement targets:

- Expand thin sections.
- Add missing FAQ entries.
- Improve source links.
- Add reader-useful related links, not only generic homepages.
- Add deeper official-source research.
- Add reader-question coverage from Reddit, Google suggestions, and search results.
- Regenerate weak image prompts.
- Replace missing or poor images.
- Remove blocked phrases.

Hard stop:

- If a post still fails after three improvement attempts, skip public publishing and keep the failed output for inspection.
- If three scheduled topic candidates fail quality in one run, fail the run and send the daily failure report instead of publishing a weak post.

## Current Practical Constraint

Under the zero-additional-cost policy, GitHub Actions can run the Python pipeline, but it cannot independently create Codex raster images. Therefore unattended publishing must stop when fresh hosted Codex JPG assets are missing or when a generated post tries to reuse an existing image URL. A Codex-capable automation step must create article-specific JPG assets first, store them under `src/images/ai_assets/hosted/`, and then allow Blogger publishing to continue.
