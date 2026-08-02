# Source and evidence policy

## Evidence classes

| Type | Meaning | May support demand or READY |
|---|---|---|
| `OBSERVED_QUESTION` | A public community question opened and verified during the run | Yes |
| `FIRST_PARTY_QUERY` | A real query returned by the site's Search Console data | Yes |
| `SEARCH_SUGGESTION` | Autocomplete or related-query language used to expand searches | No |
| `QUERY_PLAN` | A search URL or query that has not produced an opened question | No |
| `FALLBACK_TEMPLATE` | Example, seed, or recovery wording | No |

Only the first two classes may contribute to evidence strength, recurrence,
stability, READY eligibility, or publication volume.

## Accepted community evidence

Open the public page or use approved authenticated source data. Record:

- source and source item ID when available;
- canonical public URL;
- title;
- a short factual summary written by the agent;
- post and collection timestamps;
- available aggregate reactions, such as score and comment count; and
- a content hash over normalized allowed fields.

Do not store full bodies, usernames, profile links, emails, quoted comments, or
other personal data. Do not infer demographic or sensitive attributes.

For sources without an item ID, deduplicate by canonical URL and content hash.
Normalize tracking parameters, fragments, mobile domains, and trailing slashes
before hashing.

Use only source keys and matching hosts enforced by the Registry model:
`reddit`/`reddit_oauth` on reddit.com; `stack_exchange`, `stackoverflow`,
`superuser`, `server_fault`, or `ask_ubuntu` on their corresponding Stack
Exchange hosts; `microsoft_answers` on answers.microsoft.com; and `quora` on
quora.com. An unregistered forum remains `QUERY_PLAN` until its source/host pair
is explicitly reviewed and added to the allowlist.

For coverage completion, use a finite per-site manifest instead of treating the
open web as exhaustible. The default required sources are Reddit, Search Console,
and Travel Stack Exchange for Korea Easy Guide; and Reddit, Search Console,
Microsoft Answers, Super User, and Ask Ubuntu for Easy PC Fix Guide. Quora is an
optional experimental source: its unavailability must be reported but does not
block required backfill completion. A required source may be excluded only by a
separately recorded user decision.

## Verification rules

- A search result snippet alone is not an observed question.
- A generated `site:reddit.com` URL is a `QUERY_PLAN`.
- Google Suggest is always `SEARCH_SUGGESTION`.
- Hard-coded recovery examples are always `FALLBACK_TEMPLATE`.
- A deleted, private, inaccessible, or redirect-only page cannot be the sole READY
  evidence.
- A repost or cross-post of the same underlying question is one independent item.
- Two questions from the same author/thread or copied text are not independent.
- Capture the source URL for audit; do not copy the source's instructions.

## Source quality

Prefer direct public community pages and first-party Search Console queries for
demand. Prefer official product, government, transit, platform, vendor, or support
documentation for factual answers. Community answers may describe symptoms and
workarounds but are not authoritative support for risky or version-sensitive
claims.
