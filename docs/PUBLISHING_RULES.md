# Publishing Rules

## Cadence

- Publish one new post every day, including weekends.
- Target public publish time: 09:00 KST.
- Send a Posting Bot daily result report every morning after the daily pipeline finishes.
- Send a Posting Bot cadence review alert in the weekly report before increasing daily post count.
- Do not batch-publish multiple new posts on the same day during the early growth phase.
- If the daily post fails quality checks, skip publishing instead of lowering the standard.

## Cadence Review

- Keep one post per day from 2026-06-24 through 2026-07-21.
- From 2026-07-22, review whether two posts per day is appropriate.
- From 2026-08-19, review whether three posts per day is appropriate.
- Do not automatically increase cadence. Posting Bot should alert for review first.
- Two-post review requires roughly 20+ published posts, 20+ Search Console indexed/visible pages, and no quality issues.
- Three-post review requires roughly 50+ published posts, 50+ Search Console indexed/visible pages, no quality issues, and preferably visible Search Console impression growth.
- Posting Bot sends separate cadence review alerts at 09:30 KST on 2026-07-22 and 2026-08-19.

## Automation Mode

- The target operating mode is full automation.
- The pipeline must create the topic, article, image plan, images, quality report, Blogger post, and weekly report without manual editorial approval.
- Manual review is replaced by the automated Hades Engineer quality gate.
- Posting Bot must report daily success or failure, including title, Blogger status, URL, quality score, and action notes.
- Reddit OAuth credentials are recommended for stable question discovery. If Reddit public JSON is blocked, the pipeline may use fallback reader questions, and preflight should show a warning rather than hiding the reduced data quality.
- Research reports and weekly reports must separate Reddit OAuth signals, Reddit public JSON signals, and Reddit fallback signals so collection quality problems are visible.
- If weekly reports show public JSON signals without OAuth signals, treat it as a stability warning because public Reddit JSON can be blocked with 403.

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
- Codex-generated raster images are the preferred image source.
- Local SVG assets are allowed as zero-cost fallback assets for unattended automation.
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

Under the zero-additional-cost policy, GitHub Actions can run the Python pipeline, but it cannot independently create Codex raster images. The production pipeline therefore creates local SVG fallback assets so unattended runs can still satisfy the image gate. Replace SVG fallback assets with Codex-generated JPG images when visual quality is being upgraded manually or through a Codex-capable automation.
