# Registry and research contracts

## Stable identity

- Keep `category_id`, `cluster_id`, and `topic_id` immutable.
- Preserve merged identifiers as aliases.
- Keep every question and publication reference when merging.
- Never derive a replacement ID merely because a title, display category, or
  Blogger label changes.
- Use `(source, source_id)` as the primary question dedupe key. When absent, use
  canonical URL plus content hash.

## Allowed actions and lifecycle

Actions are `NEW_POST`, `UPDATE_EXISTING`, `FAQ_ADD`, `WATCH`, `REJECT`, and
`MERGE`.

Lifecycle states are `DISCOVERED`, `REVIEW`, `READY`, `SCHEDULED`, `CLAIMED`,
`GENERATED`, `LIVE_UNVERIFIED`, `PUBLISHED`, `HOLD`, `MERGED`, `REJECTED`, and
`STALE`.

Reject invalid transitions. A `PUBLISHED`, `MERGED`, or `REJECTED` topic cannot be
claimed for a new post. Use optimistic revision checks for mutations.

## Research bundle

Every import bundle must include:

- a schema version and unique run ID;
- KST start/end times and stop condition;
- per-site source coverage and unexplored query families;
- structured questions using only allowed stored fields;
- cluster assignments with problem signatures;
- topic decisions with action, evidence IDs, and existing-post comparisons;
- editor briefs for publishable actions;
- Auditor decision and reasons; and
- degraded/incomplete flags.

Treat the JSON schema in `data/topics/schemas/` as authoritative. Validate the
entire bundle before any persistent mutation. Apply changes atomically.

An interrupted research process is not a completed logical run. Store a durable
campaign ID plus site/source/query-family cursor, coverage manifest and hash, and
resume state. Existing `TIME_BUDGET` archives remain immutable historical records,
but new runs use `PAUSED` for infrastructure interruption and may claim completion
only after the finite coverage manifest is exhausted or the documented saturation
rule is met.

For Search Console evidence, the immutable evidence locator is the verified site
property plus query receipt/source item ID; a public URL is not required. For
community evidence, the immutable locator is the canonical opened URL or approved
authenticated source item ID.

## Shadow promotion

Count only complete, non-degraded Sunday runs after the required backfill is
complete for both sites. Count at most one qualifying run per KST ISO week and do
not count out-of-order or skipped-week runs as consecutive. The second consecutive
qualifying week completes the two shadow comparisons and may activate the queue
consumed in the third operating week when:

- both bundles pass schema and invariant validation;
- every READY topic has at least one verified immutable evidence locator;
- no suggestion, query plan, or fallback influenced READY;
- no obvious duplicate of an existing Blogger post remains; and
- neither run is degraded.

Any failure keeps shadow mode. Do not reset qualifying history for a harmless
idempotent rerun of the same run ID.

A single-signal recurrence exception is never trusted merely because it appears in
a research bundle. It must reference a separately persisted, revision-checked user
decision ID. Automated actors may not approve their own exception.

## Publication consistency

- Pass `topic_id` and `topic_revision` through queue, metadata, and publish result.
- Revalidate topic status and all live Blogger posts on publication day.
- Prevent a second Blogger insert for an already published topic.
- Record Blogger post ID and URL before attempting Sheet synchronization.
- On Registry or Sheet failure after Blogger success, create a durable outbox item.
- Retry reconciliation, not publication.
- Use `LIVE_UNVERIFIED` after a Blogger write receipt until either the public URL
  is verified or an authenticated Blogger `status=LIVE` catalog reconciliation
  confirms the post. A locally supplied, non-authoritative snapshot is not enough.

## Monthly category rules

- A new category requires at least five active clusters, observation in at least
  three weekly runs, and at least three READY or PUBLISHED topics.
- A split requires at least four clusters and two READY or PUBLISHED topics in
  each resulting group.
- Unpublished obvious duplicates may merge automatically.
- Any change affecting a published cluster or public Blogger label is proposal
  only.
- Applying an approved label proposal requires a pre-change snapshot and rollback
  file.
- Theme navigation is outside automatic scope.

## Sheet controls

The Google Sheet mirrors Registry state and accepts only these user decisions:

- `HOLD` or `REJECT` override;
- priority override;
- notes; and
- category-proposal approval.

Match rows by immutable IDs, never by row number or title. Reject duplicate or
missing IDs. Escape user-visible text that begins with `=`, `+`, `-`, or `@` to
prevent formula injection. A Sheet error must not alter Registry or Blogger truth.
