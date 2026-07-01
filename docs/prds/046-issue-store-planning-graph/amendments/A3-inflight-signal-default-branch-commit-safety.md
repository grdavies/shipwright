---
date: 2026-06-30
amends: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
absorbs: [gap-008-inflight-signal-run-complete-commits-index-on-ma]
frozen: false
---

# Amendment A3: Current inFlight commit path inherits default-branch refusal

## Overview

`/sw-feedback` validated (2026-06-30) a live reproduction: `/sw-deliver`'s `finalize-completion` step invokes
`inflight_signal.py run-complete`, which calls `git_commit_inflight()` and commits `docs/prds/INDEX.md` against
the shared primary checkout on `defaultBaseBranch` — outside any orchestrator or feature worktree. Durable
evidence: `.cursor/sw-deliver-state.loop-quality-gates.json` → `overrideAudit: { action: clear, why:
deliver-run-complete }` at the same timestamp as the INDEX mutation. Full evidence is in canonical gap unit
`docs/prds/gap/gap-008-inflight-signal-run-complete-commits-index-on-ma/`.

Amendment A1 (R95–R97) guarded the **future** R80 committed projection write path and recorded upstream
primitive hardening (`set_index_status`, `git_commit_living_docs`, **`git_commit_inflight`**) as a documented
dependency (A1 R97). Amendment **A2** (merged, PR #274) owns terminal INDEX **status** currency via
`living-docs reconcile` on `finalize-completion` (R98–R99). **This amendment (A3)** closes the A1 R97
dependency for the **`git_commit_inflight`** committed-write path and names `finalize-completion` as an
explicit guarded surface for branch refusal. It continues the parent + A1 + A2 namespace (**R100–R101**; A2
ends at R99). It does not modify the parent file.

## Context

PRD 032 introduced committed `inFlight` tuples via `inflight_signal.py` (read-merge-write on INDEX). The
deliver loop's terminal path (`wave_deliver_loop.py:finalize-completion`) clears the lease and commits the
`inFlight` region on run complete — **after** A2's terminal `living-docs reconcile` (R98 ordering). That
`git_commit_inflight` path is live **today**, before R80's issue-derived projection ships.

This amendment is **backend-agnostic**: it hardens shared tooling (`inflight_signal.py`) that both file-store
and issue-store modes use (parent R83). It complements A2 (status currency) without re-deriving it.

## Goals

1. `git_commit_inflight` (and therefore `inflight_signal.py` write/clear/run-complete) never commits when the
   resolved worktree's current branch is `defaultBaseBranch`.
2. The A1 R96 shared branch-guard primitive is wired into `inflight_signal.py`, not only the future R80 path.
3. A regression fixture proves `run-complete --commit` fails closed on `defaultBaseBranch`.

## Non-Goals

- Changing R80/D22 run-state authority, divergence doctor, or tracking-issue projection — unchanged.
- Replacing A1 R95 or A2 R98–R99 — A3 complements both; all use the same R96 primitive where applicable.
- Fixing `wave_living_docs.py` / `set_index_status` — remain gap-002 upstream work.

## Requirements

- **R100** — Before `git_commit_inflight` produces a git commit (invoked by `inflight_signal.py` `write`,
  `clear`, or `run-complete`), the path MUST verify the current git branch of the resolved worktree is not
  `defaultBaseBranch` and fail closed (no commit, actionable error naming the allowed path: docs branch or
  feature/orchestrator worktree) if it is — same contract as A1 R95 / PRD 033 A1 R31. This closes the A1 R97
  documented dependency for the **current** inFlight committed-write path.
- **R101** — The A1 R96 shared branch-guard primitive MUST be imported by `inflight_signal.py:git_commit_inflight`
  (not a second independent check). `wave_deliver_loop.py` `finalize-completion` is a named guarded surface
  (chains to `run-complete` after A2 R98); fixture coverage MUST include this terminal path.

## Technical Requirements

- **TR-A3-1** (R100) Add the R96 shared guard call at the top of `git_commit_inflight` before `git add`/`git
  commit`; on `defaultBaseBranch`, fail closed with the same remediation message pattern as
  `reconcile_lib.py:reconcile_prd_index` (R31).
- **TR-A3-2** (R101) Register `inflight-run-complete-refuse-default-branch` in
  `core/sw-reference/pr-test-plan.manifest.json`; assert `run-complete --commit` on `defaultBaseBranch` exits
  non-zero with no commit.
- **TR-A3-3** (R97 closure) Update PRD 046 phase-1 exit-gate notes (`.sw/layout.md` region-disposition
  section): A1 R97 dependency is **partially closed** — `git_commit_inflight` is guarded (A3); `set_index_status`
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
| DL-A3-1 | Amendment A3 after merged A2 | A2 (terminal INDEX status) merged first (PR #274); renumbered from draft A2 to avoid id collision |
| DL-A3-2 | Harden `git_commit_inflight` now, not only R80 | The defect reproduces on every `finalize-completion` today |
| DL-A3-3 | Absorb gap-008 | Renumbered from gap-007 to avoid collision with A2's gap-007 (terminal reconcile) |

## Open Questions

- Whether `finalize-completion` should auto-provision a docs branch for the inFlight commit vs. fail-closed on
  `main` — default is fail-closed per R100; docs-branch automation is follow-on if operators request it.
