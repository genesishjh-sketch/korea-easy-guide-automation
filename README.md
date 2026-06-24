# Korea Easy Guide Automation

Python pipeline for an English Blogger-based Korea travel and daily-life information blog.

## Current Stage

Stage 1, Stage 2, and Stage 3 are implemented:

1. Collect topic signals from Reddit and Google suggestions.
2. Score and select a posting topic.
3. Generate an English article from structured templates.
4. Generate a strict Codex image plan for hero and inline images.
5. Save Markdown, HTML, and metadata files.
6. Block Blogger publishing unless the Hades Engineer quality gate passes.

The target publishing cadence is one public post per day, including weekends,
at 09:00 KST. Public publishing is allowed only after automated quality review
passes. See `docs/PUBLISHING_RULES.md`.

## Setup

```bash
cd korea_blog_automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run Stage 1

```bash
python -m src.pipeline.stage1_generate --seed "incheon airport to seoul"
```

Outputs are saved under:

```text
data/generated/YYYY-MM-DD/
```

## Project Structure

```text
korea_blog_automation/
  .github/workflows/
  .env.example
  requirements.txt
  README.md
  docs/
  data/
    seeds/
  src/
    collectors/
    content/
    images/
    pipeline/
    publishing/
    reporting/
    storage/
    utils/
```

## GitHub Repository Notes

This folder is ready to become its own GitHub repository. Add these optional
repository secrets when you want live data:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `PEXELS_API_KEY`

The included workflow runs Stage 1 daily and uploads generated articles as
GitHub Actions artifacts.

Workflow YAML files are stored under `docs/github-workflows/` as templates.
Move them to `.github/workflows/` after your GitHub token or SSH setup can push
workflow files.

## Run Stage 2

Set up Blogger API credentials first:

```text
docs/BLOGGER_SETUP.md
```

Then publish the latest generated article as a Blogger draft:

```bash
python -m src.pipeline.stage2_publish --mode draft
```

Make an existing draft public:

```bash
python -m src.pipeline.stage2_make_public --post-id BLOGGER_POST_ID
```

Direct public publishing is blocked unless required images and the Hades
quality report pass:

```bash
python -m src.pipeline.stage2_publish --mode publish
```

## Run Daily Draft Pipeline

```bash
python -m src.pipeline.daily_draft
```

This chooses the next unused seed, generates an article, and uploads it as a
Blogger draft.

## Run Weekly Report

```bash
python -m src.pipeline.stage3_weekly_report
```
