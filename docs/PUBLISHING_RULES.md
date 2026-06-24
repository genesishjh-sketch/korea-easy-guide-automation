# Publishing Rules

## Cadence

- Publish one new post every day, including weekends.
- Target public publish time: 09:00 KST.
- Do not batch-publish multiple new posts on the same day during the early growth phase.
- If the daily post fails quality checks, skip publishing instead of lowering the standard.

## Automation Mode

- The target operating mode is full automation.
- The pipeline must create the topic, article, image plan, images, quality report, Blogger post, and weekly report without manual editorial approval.
- Manual review is replaced by the automated Hades Engineer quality gate.

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
  - `assets/ai-hero.jpg`
  - `assets/ai-inline-1.jpg`
- At least four official or platform source links in the article.
- For app, transport, ticket, SIM/eSIM, taxi, map, delivery, shopping, and booking posts, include useful action links such as official app-store pages, official booking pages, operator pages, and government/tourism pages.
- At least five FAQ questions.
- A `research_report.json` file must exist for every public post.
- Research must include at least:
  - six search queries
  - six source records
  - three official or platform sources
  - five reader questions or search intents
- Meta description and tags must exist.
- Placeholder, generic old-template, and AI refusal phrases are blocked.

The post is publishable only when:

```text
Hades score >= 90
and issue count == 0
```

## Image Rules

- Do not call paid image APIs from the Python pipeline.
- Each generated post must include `image_plan.json`.
- Codex-generated raster images are the preferred image source.
- Local SVG covers are fallback assets only and should not be used for public posts.
- If required image files are missing, Blogger publishing must stop.

## Repeat-Until-Quality Rule

The automation should improve and re-check a post until it passes the Hades gate.

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

## Current Practical Constraint

Under the zero-additional-cost policy, GitHub Actions can run the Python pipeline, but it cannot independently create Codex images. A fully unattended public publish requires the Codex image-generation step to run in a Codex-capable environment. Until that is wired as an automation, the quality gate intentionally blocks posts with missing required images.
