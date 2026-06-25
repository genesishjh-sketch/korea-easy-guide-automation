# Content Quality Standard

This project should publish posts at or above the strengthened T-money article quality level.

## Minimum Public-Post Standard

- 1,400+ English words.
- Clear practical intent for foreign visitors in Korea.
- Specific topic depth, not generic Korea travel filler.
- Two required images:
  - preferred: `assets/ai-hero.jpg` and `assets/ai-inline-1.jpg`
  - zero-cost CI fallback: `assets/ai-hero.svg` and `assets/ai-inline-1.svg`
- Four or more official/platform links in the article.
- App/service articles must include direct app-store, official service, booking, or operator links that help the reader take action.
- Five or more FAQ questions.
- No placeholder phrases, AI refusal phrases, or generic old-template section names.

## Required Research Before Writing

Every public post must have `research_report.json`.

Required fields:

```json
{
  "topic": "string",
  "queries": ["query 1"],
  "reader_questions": ["question or search intent"],
  "sources": [
    {
      "name": "Source name",
      "url": "https://example.com",
      "type": "official|platform|community|search"
    }
  ],
  "notes": ["short factual notes used in the article"]
}
```

Minimum research volume:

- 6+ search queries.
- 6+ source records.
- 3+ official or platform sources.
- 5+ reader questions or search intents.

## Search Targets

Use several search angles before writing:

- Reddit questions from foreign visitors.
- Google suggestions and related long-tail phrases.
- Official Korean service pages.
- Government or tourism organization pages.
- App Store / Google Play pages for app-related posts.
- Existing SERP patterns to understand what readers expect.

## Article Depth Requirements

A public post should answer:

- What the service/item is.
- Who should use it.
- Where to get it or start.
- Step-by-step usage.
- Cost/payment/refund or cancellation issues.
- Foreigner-specific blockers.
- Common errors and fixes.
- Safer alternatives or comparisons.
- Official links to verify current details.
- Related app, booking, or service links where they improve reader convenience.

## Hades Gate

The Hades Engineer quality gate is the hard blocker. If Hades fails, do not publish.

The automation may improve and retry up to three times. If the post still fails, keep the output for inspection and skip that day rather than publishing weak content.

## Easy PC Fix Guide Rules

Windows troubleshooting posts must be safer and more explicit than general travel posts.

Every public Windows post must include:

- `Applies to`, `Risk level`, `Data loss risk`, `Estimated time`, and `Last checked`.
- A concrete risk level: `Low`, `Medium`, or `High`.
- A concrete data-loss value: `No`, `Yes`, or `Possible`.
- A concrete estimated time, such as `5 minutes` or `20 minutes`.
- A `Last checked` date in `YYYY-MM-DD` format.
- A backup warning when data loss is possible.
- Direct Microsoft sources in the article and research report, not only Microsoft search-result pages.
- Three or more internal Related Guides links.

Keep risky steps in `Advanced Fixes` only:

- Registry or `regedit`
- BIOS/UEFI
- partitions, formatting, or reset/recovery operations
- PowerShell, Command Prompt, `sfc`, `dism`, `chkdsk`, or `diskpart`

Launch queue topics must pass preflight before unattended publishing:

- The topic must exist in `data/seeds/windows_topic_seeds.json`.
- The topic must map to a specific Windows category, not generic `Computer Help`.
- The topic must have enough Microsoft source coverage for Hades.
- The queue must avoid duplicate, blank, or already weak topics.
