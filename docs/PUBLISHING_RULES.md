# Publishing Rules

## Cadence

- Current stabilization cadence: publish one new post per blog every day, including weekends.
- Target public publish time: 09:00 KST.
- Daily GitHub Actions publishing runs at 09:10 KST with a 09:25 KST backup run.
- The daily limit guard must stop the backup run from publishing a duplicate post if the primary run already published or found a valid same-day post.
- Send a Posting Bot daily result report every morning after the daily pipeline finishes.
- Send a Posting Bot cadence review alert in the weekly report before increasing daily post count.
- Do not imitate low-quality mass publishing. A quota never justifies generic padding, repeated structure, recycled images, or a near-duplicate topic.
- If the daily post fails quality checks, the system must first diagnose the reason, fix the issue, re-run Hades, and publish a recovered post when it passes.
- Skipping a daily slot is allowed only after the recovery loop reaches a hard stop. It is not the first response to a missing post.
- Move to two posts per blog per day only after 14 consecutive days with no Hades failure, no body-similarity warning, no reused image, and no unresolved publishing incident.
- Move to three posts per blog per day only after a further 30 stable days, a clean whole-site readiness audit, and Search Console showing that crawling/indexing is progressing without a structural error.
- Cadence changes require a Posting Bot review alert; they are never triggered merely because a calendar date arrived.

## Daily Topic Mix

When cadence eventually reaches three posts, use this mix:

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

- Current operating cadence is one post per blog per day while the strengthened quality system gathers a clean history.
- Do not increase beyond three posts per blog per day without a separate review.
- If Search Console shows crawl/indexing trouble, repeated quality issues, or weak impressions after several weeks, reduce cadence before lowering quality.
- A higher-cadence review requires roughly 50+ published posts, improving Search Console indexed/visible pages, no unresolved quality issues, and preferably visible impression growth.
- Cadence increase review also requires stable topic discovery. Google `site:reddit.com` search signals, Google Suggest signals, official-source coverage, and Hades quality results are enough for normal operation. Reddit OAuth is optional.
- Posting Bot should alert when cadence, indexing, or quality should be reviewed.

## Search Discovery and Indexing

- Submit only the canonical `https://{blog}.blogspot.com/sitemap.xml` after a successful public publish. Do not create duplicate Search Console properties or repeatedly submit alternate Atom feeds as a workaround.
- The public homepage must expose direct absolute `.html` post links in raw HTML. A JavaScript feed renderer may enhance the page, but it must not be the only discovery path.
- Every public post must return HTTP 200, declare itself as canonical, omit `noindex`, and avoid meta-refresh or multi-hop redirects.
- Run `stage3_search_console_audit` for the latest URL after daily publishing and for three representative URLs in each weekly report.
- Treat `URL is unknown to Google` and `Discovered - currently not indexed` as discovery delay when current live checks pass. They do not justify duplicate posts or repeated indexing requests.
- Treat Search Console `Redirect error` as a structural incident only when the current live Googlebot check also fails. If the live page returns direct 200 with a matching canonical, record the Search Console value as historical and request revalidation for one representative URL.
- Do not request indexing for every post every day. Submit the sitemap, request one representative URL after a material fix, and let Google recrawl the rest.
- Do not increase cadence while indexed/search-visible pages remain at zero or a current structural error is unresolved.

## Automation Mode

- The target operating mode is full automation.
- The pipeline must create the topic, article, image plan, images, quality report, Blogger post, and weekly report without manual editorial approval.
- Manual review is replaced by the automated Hades Engineer quality gate.
- Posting Bot must report daily success or failure, including title, Blogger status, URL, quality score, and action notes.
- A missing-publication alert is an incident trigger, not the final outcome. The required response is missing detected -> root cause identified -> article/images/sources/topic repaired or replaced -> Hades rechecked -> same-day recovery publish when possible.
- Validate-only smoke tests must write `daily-validation-success.json` or `daily-validation-failure.json`; they must not overwrite `daily-success.json` or `daily-failure.json`, which are reserved for publish/draft/daily-limit operational results.
- Reddit OAuth credentials are optional. If Reddit public JSON is blocked or OAuth is unavailable, the pipeline should use Google `site:reddit.com` search-intent signals before falling back to local reader questions.
- Research reports and weekly reports must separate Reddit OAuth signals, Reddit public JSON signals, Reddit Google search signals, and Reddit fallback signals so collection quality is visible.
- If weekly reports show only fallback reader questions and no Google site-search/OAuth/public signals, treat it as a topic-discovery warning.
- Run `python -m src.pipeline.stage0_reddit_health --site easy_pc_fix_guide --notify` only when you want to check optional Reddit OAuth status and send the result to Posting Bot.

## Hades Engineer Quality Gate

Every post must pass automated review before Blogger publishing.

Required checks:

- At least 800 useful English words. The normal target is 900-1,600 words, determined by search intent and topic complexity. There is no reward for generic filler.
- Headings and article order must vary with the topic. Hades checks semantic reader tasks rather than forcing one visible outline.
- Korea articles must contain a decision/quick-answer component, orientation, practical steps, pitfalls or mistake prevention, FAQ, direct Related Guides, official sources, and a final summary.
- Windows articles must contain safety facts, symptoms/observations, diagnosis, concrete steps, Advanced Fixes boundaries, stop/get-help signals, FAQ, direct Related Guides, Microsoft sources, and a final summary.
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
- Windows help posts must include at least four official Microsoft links in the article and research report.
- Windows help posts must include at least two direct Microsoft support, Learn, release-health, or product pages. Microsoft search-result URLs are useful fallback links, but they do not count as direct source depth.
- Meta description and tags must exist.
- Placeholder, generic old-template, and AI refusal phrases are blocked.
- Candidate body similarity of 0.35 or higher is a rewrite warning; 0.45 or higher is a hard publish block.
- Repeated generic title endings and already-covered search intent are blocked even when the exact title text differs.
- Existing-post refresh code must never append generic paragraphs to reach a word count.

The post is publishable only when:

```text
Hades score >= 90
and issue count == 0
```

## Image Rules

- Do not call paid image APIs from the Python pipeline.
- The zero-cost production image path is Codex app automation using the built-in `image_gen` tool, not GitHub Actions alone.
- GitHub Actions may collect, draft, validate, and publish only after hosted image assets exist. It must not pretend to generate Codex images by reusing local SVGs or old library photos.
- GitHub Actions for unattended publishing must not receive paid or external image API keys such as `OPENAI_API_KEY`, `OPENAI_IMAGES_API_KEY`, or `PEXELS_API_KEY`.
- The preflight check must fail if paid image API keys are wired into unattended workflows.
- If paid/external image API keys exist only in the local shell, preflight should warn so the operator can confirm they are not used by scheduled publishing.
- Each generated post must include `image_plan.json`.
- Each `image_plan.json` must include `prompt_policy` declaring:
  - `generation_owner=codex_app_automation`
  - `tool=built_in_image_gen`
  - no paid image API use
  - fresh one-off prompt generation
  - recent-image repetition avoidance
- Public posts must use fresh article-specific Codex-generated raster images.
- Reusable library images under `src/images/ai_assets/korea/` or `src/images/ai_assets/windows/` are draft aids only and must not be used for public publishing.
- Public publishing may only use unique hosted assets under `src/images/ai_assets/hosted/`.
- Do not reuse an image URL that already appears in a published Blogger post.
- Do not use `general` fallback images for public posts.
- Local SVG assets are not allowed for public posts.
- If required image files are missing, Blogger publishing must stop.
- Missing image files are not the final outcome for Codex app automation. The Codex automation must generate fresh images, copy them into the article assets, copy hosted versions into `src/images/ai_assets/hosted/`, commit/push those hosted files, re-run Hades, and then publish.
- Image prompts must not be static templates. Codex must create a new one-off prompt from the article title, search intent, reader problem, image role, and recent image history before calling `image_gen`.
- Hero and inline images must have different jobs:
  - hero: problem context, situation, or decision moment
  - inline: process, checklist, comparison, warning, route, cause-and-fix, or decision flow
- Do not fill posts with multiple similar images. Add a third or fourth image only when it has a distinct reader-useful role.
- PC blog images must not default to repeated laptop-on-desk scenes. Use topic-specific objects, macro details, physical process diagrams, abstract diagnostic metaphors, peripheral close-ups, or educational bitmap diagrams where more appropriate.
- Korea blog images must not default to repeated traveler-with-phone, luggage-only airport, skyline-only, or cafe-table phone scenes. Use route decisions, service steps, payment/checklist objects, place-specific practical actions, comparison visuals, and mistake-prevention visuals.
- If a generated image looks generic, repeated, text-heavy, off-topic, or too similar to recent posts, discard it and regenerate. Do not publish it just because an image file exists.

## Missing Publication Recovery Rule

If a scheduled post is missing, the automation must not simply wait for the next day. It must treat the missing slot as a recoverable publishing incident.

Required recovery order:

1. Confirm the public Blogger feed has fewer posts than the daily minimum.
2. Identify the blocking reason from the latest daily batch, publish result, quality report, image plan, research report, and workflow logs.
3. Fix the root cause:
   - image issue: generate fresh article-specific Codex JPG images, avoid SVG/base64/general/reused assets, store hosted assets, and re-run image checks.
   - source issue: replace weak, dead, shortcut, or generic links with direct official/platform sources.
   - content issue: expand thin sections, add missing FAQs, improve steps, strengthen reader intent coverage, and remove blocked phrases.
   - topic issue: choose the next non-duplicate weekly queue topic with a different search intent.
   - duplicate issue: change the angle or replace the topic; do not publish near-duplicate posts.
4. Re-run the full Hades quality gate.
5. If Hades passes with `score >= 90` and `issue count == 0`, publish the recovered post the same day.
6. Submit sitemap after the recovery publish.
7. Record the original failure reason, recovery action, recovered URL, and quality score in the daily report.

Telegram policy:

- Do not send noisy messages for every internal retry.
- Send the morning summary and only critical failure/recovery notifications.
- If recovery succeeds, include the recovered post in the next daily summary.
- If recovery hard-stops, send one concise alert with the root cause and the next required human/Codex action.

Hard stop:

- If three improvement attempts for the same post still fail Hades, replace the topic.
- If three topic candidates fail in one run, fail the slot and send a concise recovery-failed alert.
- Never publish a weak post just to remove a missing alert.

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
- Replace visually repetitive images even when the files technically exist.
- Rewrite image prompts from scratch when the visual concept collapses back into a repeated pattern.
- Remove blocked phrases.

Hard stop:

- If a post still fails after three improvement attempts, skip public publishing and keep the failed output for inspection.
- If three scheduled topic candidates fail quality in one run, fail the run and send the daily failure report instead of publishing a weak post.

## Current Practical Constraint

Under the zero-additional-cost policy, GitHub Actions can run the Python pipeline, but it cannot independently create Codex raster images. Therefore GitHub Actions must stop when fresh hosted Codex JPG assets are missing or when a generated post tries to reuse an existing image URL.

The preferred production path is Codex app automation:

1. Wake the local Codex automation.
2. Select topic and generate/rewrite the article.
3. Read `image_plan.json` as an art-direction brief.
4. Write a fresh prompt for each image based on the article, image role, and recent visual history.
5. Use built-in `image_gen` to create raster images without paid image API calls.
6. Inspect the images. If they are repetitive or weak, regenerate before publishing.
7. Save final images as article assets and hosted assets.
8. Commit/push hosted assets so Blogger receives stable raw image URLs.
9. Re-run Hades and publish only if the article and images pass.
