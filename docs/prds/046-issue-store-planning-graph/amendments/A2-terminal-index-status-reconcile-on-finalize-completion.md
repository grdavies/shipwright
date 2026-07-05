---
superseded-by: PRD 055
date: 2026-06-30
visibility: public
amends: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
absorbs: [gap-007-finalize-completion-omits-terminal-living-docs-r]
frozen: true
frozen_at: 2026-06-30
---

# Amendment A2: Terminal INDEX status reconcile on finalize-completion

## Overview

`/sw-feedback` validated (2026-06-30) that PRDs **039** and **043** merged to `main` (terminal PRs #272 and
#268) while `docs/prds/INDEX.md` still showed `in-progress`. Root cause: `wave_deliver_loop.py`
`finalize-completion` runs `completion finalize-if-merged` and `inflight_signal run-complete` but **never**
invokes `living-docs reconcile`, which is the only automated path that calls `set-index-status` for the
delivered PRD. Phase-level reconcile (after each merge in `wave_merge.py`) correctly writes `in-progress`
until `target_merge_detected()` is true — but no terminal reconcile runs after merge is detected. Evidence:
canonical gap unit
`docs/prds/gap/gap-007-finalize-completion-omits-terminal-living-docs-r/`.

This closes the implementation gap behind PRD 009 A1 **R47** (INDEX reflects merge state) without amending
completed PRDs 009/033/035. It continues the parent + A1 namespace (**R98–R99**; A1 ends at R97). It does
not modify the parent file.

## Context

- **A1** (R95–R97) guards committed INDEX **write** paths from default-branch commits.
- **This amendment** guards committed INDEX **status currency** at deliver terminal — orthogonal concern.
- `derive_index_status()` already returns `complete` when `merged_to_main` is true; the defect is a missing
  call site, not wrong derivation logic.
- `finalize-completion` MUST pass `--orchestrator-worktree` (or equivalent) to `living-docs reconcile` so
  R31/R95 guards are not bypassed via repo-root cwd (see gap-002 / unmerged PR #273 A2 inflight path).

## Goals

1. After successful `finalize-if-merged`, deliver automatically sets the delivered PRD's INDEX row to
   `complete` without operator manual edits.
2. Terminal reconcile runs on the orchestrator worktree, not the primary checkout on `defaultBaseBranch`.
3. Regression fixtures cover PRDs that reach `merged-complete` via the deliver loop.

## Non-Goals

- Changing `derive_index_status` logic — already correct when `merged_to_main` is true.
- Full-corpus `reconcile.py reconcile` on `main` — remains refused (PRD 033 A1 R31).
- Re-deriving status from COMPLETION-LOG alone — R29 git-primary rule unchanged.

## Requirements

- **R98** — `wave_deliver_loop.py` `finalize-completion` MUST invoke `wave_living_docs reconcile
  --commit` for the delivered PRD immediately after successful `completion finalize-if-merged` and before
  `inflight_signal run-complete`, using the orchestrator worktree path (not bare repo root on
  `defaultBaseBranch`).
- **R99** — When `finalize-if-merged` succeeds and `derive_index_status` resolves to `complete`, the
  reconcile step MUST persist that status via `set-index-status` and commit living docs on the orchestrator
  worktree; failure MUST fail-closed (non-zero exit, deliver halt) rather than leaving INDEX stale while
  run-state shows `merged-complete`.

## Technical Requirements

- **TR-A2-1** (R98) Extend `finalize-completion` in `wave_deliver_loop.py` to call `wave_living_docs.py
  reconcile --commit` with `--orchestrator-worktree` from deliver state; wire into existing
  `living_doc_write_lock` path.
- **TR-A2-2** (R99) Register fixture `terminal-index-status-reconcile-on-finalize`: simulated deliver run
  with `merged_to_main=True` updates only the delivered PRD row to `complete` in INDEX without manual edits.
- **TR-A2-3** Document in `core/skills/deliver/SKILL.md` terminal chain:
  `finalize-if-merged` → `living-docs reconcile --commit` → `inflight_signal run-complete`.

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `terminal-index-status-reconcile-on-finalize` | After `finalize-completion` with merge detected, delivered PRD INDEX row is `complete` |
| `terminal-reconcile-uses-orchestrator-worktree` | Terminal reconcile does not commit from `defaultBaseBranch` primary checkout |
| `terminal-reconcile-fail-closed` | Reconcile failure halts finalize; run-state does not report success with stale INDEX |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A2-1 | Amendment on PRD 046 (not-started) | A1 already owns INDEX commit safety; terminal status currency is the adjacent INDEX contract for the same program |
| DL-A2-2 | Invoke existing `living-docs reconcile` primitive | `derive_index_status` + `set-index-status` already implement R47; missing call site only |
| DL-A2-3 | Fail-closed on reconcile failure | Stale INDEX with `merged-complete` run-state is worse than a halt — matches R50 docs-currency gate intent |

## Open Questions

- Ordering vs `inflight_signal run-complete`: this amendment specifies reconcile **before** inflight clear so
  INDEX `complete` and `inFlight` tuple clear are separate commits; confirm no CAS race with PRD 032 lease
  during `/sw-tasks` implementation.
