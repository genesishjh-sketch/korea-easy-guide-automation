# Implementation Stages

## Stage 1: Collect -> Generate -> Save

Implemented now.

- Reddit research collector with optional OAuth, public JSON, Google `site:reddit.com` search-intent fallback, and local fallback questions
- Google suggestion collector
- Topic scoring
- English article generation
- Strict Codex image plan generation
- Markdown, HTML, and metadata storage
- GitHub Actions artifact workflow

Run:

```bash
python -m src.pipeline.stage1_generate --seed "incheon airport to seoul"
```

## Stage 2: Auto Publish

Implemented now.

- Google OAuth flow
- Blogger API client
- Draft post creation
- Hades Engineer automated quality gate
- Codex app image-generation handoff for zero-cost raster images
- Required static pages creation
- Label/category mapping
- Optional direct publishing
- Publish result persistence

Publishing cadence:

- One post per day.
- Includes weekends.
- Target public publish time: 09:00 KST.
- If quality fails, diagnose the cause, repair or replace the candidate, re-run Hades, and publish a same-day recovery post when it passes. Skip only after the recovery loop reaches a hard stop.

Entrypoint:

```bash
python -m src.pipeline.stage2_publish --article-dir data/generated/YYYY-MM-DD/slug
```

The publish command writes `quality_report.json` and stops when the article
does not pass the Hades Engineer gate.

Missing-publication recovery:

- A missing daily post is not considered resolved by waiting for the next run.
- Check the latest daily batch result, quality report, image plan, research report, and workflow logs.
- Fix the root cause, re-run Hades, and publish the recovered post if it reaches `score >= 90` with no issues.
- If recovery fails after the hard-stop limit, keep the failed output and send one concise Posting Bot alert with the cause and next action.

Codex image-generation loop:

- `image_plan.json` is an art-direction brief, not a fixed prompt to paste blindly.
- Codex app automation must use built-in `image_gen` for missing or weak images.
- Before each image call, Codex writes a fresh one-off prompt from the article title, reader intent, image role, and recent visual history.
- If the result repeats recent visuals, uses a generic laptop/phone/traveler scene, contains readable UI/text, or does not help the article, regenerate.
- Final images are copied into both article `assets/` and `src/images/ai_assets/hosted/`, then hosted files are committed and pushed before Blogger publishing.
- GitHub Actions alone cannot perform this image generation step without a paid API path, so it must hold the slot when hosted Codex images are missing.

Publish an existing Blogger draft after review:

```bash
python -m src.pipeline.stage2_make_public --post-id BLOGGER_POST_ID --result-path data/generated/YYYY-MM-DD/slug/blogger_publish_result.json
```

Required pages:

```bash
python -m src.pipeline.stage2_pages
```

Search Console:

- Add the URL prefix property for the Blogger URL.
- Submit `sitemap.xml` after at least one post is public.
- Use URL inspection to request indexing for newly published posts.

## Stage 3: Weekly Report

Implemented as a local generated report.

- Generated article count
- Published post count
- Failed runs
- Top topic signals
- Search Console placeholder, until credentials are available
- Markdown and HTML weekly report output

Entrypoint:

```bash
python -m src.pipeline.stage3_weekly_report
```
