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
