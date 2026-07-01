---
date: 2026-06-30
amends: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
absorbs: [gap-007-inflight-signal-run-complete-commits-index-on-ma]
frozen: false
---

# Amendment A2: Current inFlight commit path inherits default-branch refusal

## Overview

`/sw-feedback` validated (2026-06-30) a live reproduction: `/sw-deliver`'s `finalize-completion` step invokes
`inflight_signal.py run-complete`, which calls `git_commit_inflight()` and commits `docs/prds/INDEX.md` against
the shared primary checkout on `defaultBaseBranch` — outside any orchestrator or feature worktree. Durable
evidence: `.cursor/sw-deliver-state.loop-quality-gates.json` → `overrideAudit: { action: clear, why:
deliver-run-complete }` at the same timestamp as the INDEX mutation. Full evidence is in canonical gap unit
`docs/prds/gap/gap-007-inflight-signal-run-complete-commits-index-on-ma/`.

Amendment A1 (R95–R97) guarded the **future** R80 committed projection write path and recorded upstream
primitive hardening (`set_index_status`, `git_commit_living_docs`, **`git_commit_inflight`**) as a documented
dependency (A1 R97). This amendment **closes that dependency for the current deliver terminal path** by
requiring the A1 R96 shared guard on `git_commit_inflight` and naming `finalize-completion` as an explicit
guarded surface. It continues the parent + A1 namespace (**R98–R99**; A1 ends at R97). It does not modify
the parent file.

## Context

PRD 032 introduced committed `inFlight` tuples via `inflight_signal.py` (read-merge-write on INDEX). The
deliver loop's terminal path (`wave_deliver_loop.py:finalize-completion`) clears the lease and commits the
`inFlight` region on run complete. That path is live **today** — before R80's issue-derived projection ships.
Without this amendment, A1's R97 dependency leaves the defect open on every deliver run that reaches
`finalize-completion` from the primary checkout.

This amendment is **backend-agnostic**: it hardens shared tooling (`inflight_signal.py`) that both file-store
and issue-store modes use (parent R83 names `inflight_signal` as a shared `discover_units` consumer). It does
not change issue-derived derivation behavior (parent Non-Goals).

## Goals

1. `git_commit_inflight` (and therefore `inflight_signal.py` write/clear/run-complete) never commits when the
   resolved worktree's current branch is `defaultBaseBranch`.
2. The A1 R96 shared branch-guard primitive is wired into `inflight_signal.py`, not only the future R80 path.
3. A regression fixture proves `run-complete --commit` fails closed on `defaultBaseBranch`.

## Non-Goals

- Changing R80/D22 run-state authority, divergence doctor, or tracking-issue projection — unchanged.
- Replacing A1 R95's R80-specific guard — A2 complements it; both use the same R96 primitive.
- Fixing `wave_living_docs.py` / `set_index_status` — remain gap-002 upstream work; A2 only adds
  `git_commit_inflight` to the shared primitive's call sites.

## Requirements

- **R98** — Before `git_commit_inflight` produces a git commit (invoked by `inflight_signal.py` `write`,
  `clear`, or `run-complete`), the path MUST verify the current git branch of the resolved worktree is not
  `defaultBaseBranch` and fail closed (no commit, actionable error naming the allowed path: docs branch or
  feature/orchestrator worktree) if it is — same contract as A1 R95 / PRD 033 A1 R31. This closes the A1 R97
  documented dependency for the **current** inFlight committed-write path.
- **R99** — The A1 R96 shared branch-guard primitive MUST be imported by `inflight_signal.py:git_commit_inflight`
  (not a second independent check). `wave_deliver_loop.py` `finalize-completion` is a named guarded surface
  (chains to `run-complete`); fixture coverage MUST include this terminal path.

## Technical Requirements

- **TR-A2-1** (R98) Add the R96 shared guard call at the top of `git_commit_inflight` before `git add`/`git
  commit`; on `defaultBaseBranch`, fail closed with the same remediation message pattern as
  `reconcile_lib.py:reconcile_prd_index` (R31).
- **TR-A2-2** (R99) Register `inflight-run-complete-refuse-default-branch` in
  `core/sw-reference/pr-test-plan.manifest.json`; assert `run-complete --commit` on `defaultBaseBranch` exits
  non-zero with no commit.
- **TR-A2-3** (R97 closure) Update PRD 046 phase-1 exit-gate notes (`.sw/layout.md` region-disposition
  section): A1 R97 dependency is **partially closed** — `git_commit_inflight` is guarded; `set_index_status`
  and `git_commit_living_docs` remain gap-002 upstream.

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `inflight-run-complete-refuse-default-branch` | `inflight_signal run-complete --commit` on `defaultBaseBranch` fails closed, no commit |
| `inflight-write-refuse-default-branch` | `inflight_signal write --commit` same refusal |
| `inflight-shared-branch-guard` | `git_commit_inflight` uses the same R96 primitive as the R80 path (A1), not an independent copy |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A2-1 | Amendment on PRD 046, not a new PRD | A1 already owns committed-INDEX default-branch safety; A2 closes the live deliver terminal gap A1 deferred |
| DL-A2-2 | Harden `git_commit_inflight` now, not only R80 | The defect reproduces on every `finalize-completion` today; waiting for R80 would ship years of exposure |
| DL-A2-3 | Absorb gap-007 | Single canonical gap unit; routes feedback signal to this amendment |

## Open Questions

- Whether `finalize-completion` should auto-provision a docs branch for the commit vs. fail-closed on `main`
  — default is fail-closed per R98; docs-branch automation is follow-on if operators request it.
