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
- Required static pages creation
- Label/category mapping
- Optional direct publishing
- Publish result persistence

Publishing cadence:

- One post per day.
- Includes weekends.
- Target public publish time: 09:00 KST.
- If quality fails, skip publishing instead of batch-publishing later.

Entrypoint:

```bash
python -m src.pipeline.stage2_publish --article-dir data/generated/YYYY-MM-DD/slug
```

The publish command writes `quality_report.json` and stops when the article
does not pass the Hades Engineer gate.

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
