---
id: gap-015-all-private-profile-requires-visibility-public-a
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: all-private profile requires visibility public at spec-seed not assert-entry only
visibility: public
tags: [source:feedback, signal:feedback-prd-041-visibility-spec-seed-2026-07-01, prd-041, prd-034]
source_pr: 284
absorbs: []
---

# all-private profile requires visibility public at spec-seed not assert-entry only

_Captured from PRD 041 deliver (`feedback-prd-041-visibility-spec-seed-2026-07-01`). Distilled in Recallium #2282, #2285._

## Summary

Under `planning.visibilityProfile: all-private`, frozen PRD/task bodies tracked in git need
`visibility: public` in frontmatter. Without it, `wave_spec_seed.assert_no_tracked_private_bodies` fails at
**deliver-loop spec-seed** with `tracked-private-body` (exit 20) — not only at `assert-entry`.

Operators may add frontmatter on `main` as duplicate uncommitted edits while spec-seed already committed
visibility to `feat/<slug>` idempotently.

## PRD 041 evidence

- Run start blocked until visibility frontmatter added (see sibling PRDs 039/040/042 pattern).
- spec-seed first run committed public bodies to `feat/self-improving-loop` only.
- Re-run spec-seed is idempotent; main must not retain duplicate frontmatter copies.

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **PRD 034** | Visibility resolver + tracked-private reject |
| **gap-005** | spec-seed cwd-dependent repo-root — different failure mode |
| **Mem #2282, #2285** | Operator learnings — now formalized |

## Remediation direction

1. **Freeze-time guard:** `/sw-tasks` freeze or `/sw-freeze` requires `visibility: public` when profile is
   `all-private` and artifact is git-tracked.
2. **Clear error at spec-seed** with remediation pointing to feat branch, not bare main edits.
3. Fixture: `all-private-spec-seed-tracked-private-body`.

## Schedule

Triage to **PRD 034** amendment or **PRD 041** doc-impact follow-on.
