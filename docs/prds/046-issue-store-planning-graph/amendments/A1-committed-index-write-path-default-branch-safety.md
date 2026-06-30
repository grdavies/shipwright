---
date: 2026-06-30
amends: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
absorbs: [gap-002-living-doc-reconcile-commits-bypass-r31-default-]
frozen: true
frozen_at: 2026-06-30
---

# Amendment A1: Committed-INDEX write path inherits default-branch commit safety

## Overview

`/sw-feedback` validated (2026-06-30) that the existing **R31** default-branch-commit-refusal guardrail
(PRD 033 A1) is implemented for the full-corpus reconciler path
(`scripts/reconcile_lib.py:reconcile_prd_index`) but **not** for the scoped primitives R31 itself sanctioned
as the post-merge alternative (`set_index_status`) or for the automated caller that chains them to a git
commit (`scripts/wave_living_docs.py:git_commit_living_docs`, invoked via
`python3 scripts/wave.py living-docs reconcile --commit`). This was reproduced live: local `main` carried two
unpushed, non-PR commits produced by this exact path. Full evidence is recorded in the canonical gap unit
`docs/prds/gap/gap-002-living-doc-reconcile-commits-bypass-r31-default-/`.

This matters specifically for PRD 046 because **R80/D22** introduce a **new** committed-write path: the
deliver-owned `inFlight` tuple is projected, read-only, into the committed INDEX `inFlight` region on every
deliver run-start and phase transition — for both file-derived and issue-derived projections. Without an
explicit requirement, R80's implementation is free to reuse (or re-derive) the same unguarded commit pattern,
shipping the defect into the new issue-store-aware projection from day one. This amendment adds that
requirement. It continues the parent R-ID namespace into the reserved **R95–R99** band and does not modify
the parent file.

## Context

The parent PRD's own Non-Goals explicitly exclude "changing the file-store planning-graph behavior... when
issue-store is inactive" — so the underlying primitive fix (closing the gap in `set_index_status` /
`git_commit_living_docs` themselves) is out of this amendment's scope; that is upstream, shared-tooling work
the operator should schedule independently (e.g. a further PRD 033/035 amendment or a direct fix), and is
called out as an open dependency below, not resolved here. What this amendment **does** own is making sure
PRD 046's own new write path — which is in scope for this PRD regardless of backend — does not assume an
unguarded primitive is safe to build on, and is independently tested for the failure mode.

## Goals

1. R80's committed-`inFlight`/INDEX projection write path never commits when the resolved worktree's current
   branch is `defaultBaseBranch`, regardless of whether the projection source is file-derived or
   issue-derived.
2. The same guard applies to any committed-INDEX write R25/R80 perform as part of normal operation (e.g. a
   regenerated `structural`/`derived` region alongside the `inFlight` projection in the same commit).
3. A regression fixture proves the failure mode (default-branch checkout) fails closed rather than committing.

## Non-Goals

- Fixing the underlying unguarded primitives (`reconcile_lib.py:set_index_status`,
  `wave_living_docs.py:git_commit_living_docs`) themselves — shared, backend-agnostic tooling outside this
  PRD's file-store-behavior Non-Goal boundary; tracked as a dependency, not delivered here.
- Any other R80/D22 behavior (run-state authority, divergence doctor, tracking-issue projection) — unchanged.

## Requirements

- **R95** — Before any commit produced by the R80 committed-`inFlight`/INDEX projection write path (or any
  other commit R25/R80 perform against the committed planning INDEX), the write path MUST verify the current
  git branch of the resolved worktree is not `defaultBaseBranch` and fail closed (no commit, actionable error
  naming the allowed path) if it is — for both file-derived and issue-derived projection sources. This is the
  same contract as PRD 033 A1 R31, applied at the new R80 write path rather than re-derived independently.
- **R96** — R95's guard MUST be implemented as (or delegate to) a single shared primitive also usable by the
  pre-existing scoped primitives (`set_index_status`, `git_commit_living_docs`) once they are hardened
  upstream, so PRD 046 does not maintain a second, divergent copy of the same branch check.
- **R97** — A documented dependency is recorded: this amendment's guard is necessary-but-not-sufficient until
  the upstream primitives (Non-Goals) are also hardened; the PRD 046 phase-1 exit gate (R80/R83/R87/R88, D22)
  notes this open dependency rather than implying the class of defect is fully closed repo-wide.

## Technical Requirements

- **TR-A1-1** (R95) Add a `branch == defaultBaseBranch` check at the point R80's committed-`inFlight`/INDEX
  projection is about to be committed; on a match, fail closed with the same actionable remediation message
  pattern as `reconcile_lib.py:reconcile_prd_index` (R31).
- **TR-A1-2** (R96) Factor the check into a shared helper importable by both the R80 write path and the
  legacy `wave_living_docs.py` / `reconcile_lib.py` primitives, so a single upstream fix closes both.
- **TR-A1-3** (R97) Record the dependency on the upstream fix in the PRD 046 phase-1 rollout doc exit-gate
  notes (`.sw/layout.md` region-disposition section already touched by phase 1).

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `r80-inflight-projection-refuse-default-branch` | Committing the R80 `inFlight`/INDEX projection while the resolved worktree is checked out on `defaultBaseBranch` fails closed, no commit, for both file- and issue-derived sources |
| `r80-inflight-projection-shared-guard` | The R95 guard and the (eventually hardened) legacy primitives resolve to the same shared check, not independent copies |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A1-1 | R80's new committed-write path gets its own explicit default-branch guard rather than inheriting safety by assumption | Prevents PRD 046 from shipping the GAP-002/GAP-053-class defect into a brand-new write path on day one |
| DL-A1-2 | The upstream primitive fix stays a Non-Goal / documented dependency, not delivered in this amendment | Matches the parent PRD's own Non-Goal boundary (no file-store-behavior changes when issue-store is inactive); the shared-tooling fix is independent, cross-cutting work outside the 043 program |

## Open Questions

None blocking. The exact location of the shared guard helper (new module vs. extending
`reconcile_lib.py`) is resolved during `/sw-tasks` for whichever unit ships the upstream fix first.
