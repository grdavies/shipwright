---
id: gap-019-parallel-deliver-verify-mutates-tracked-scripts-
type: gap
status: resolved
schedule: PRD 050 A5
title: parallel deliver verify mutates tracked scripts/test/fixtures in orchestrator worktree
visibility: public
tags: [source:feedback, prd-050-a5, signal:feedback-prd-048-deliver-observations-2026-07-02, prd-048, deliver, verify]
source_pr: 48
resolvedBy: PRD 050 A5 (R51–R54)
absorbs: []
---

# parallel deliver verify mutates tracked scripts/test/fixtures in orchestrator worktree

_Scheduled to PRD 050 A5 (`docs/prds/050-deliver-concurrency-cwd-terminal-robustness/amendments/A5-deliver-verify-fixture-tree-immutability.md`)._

_Captured from feedback signal `feedback-prd-048-deliver-observations-2026-07-02` during PRD 048 deliver._

## Summary

During PRD 048 multi-phase deliver, parallel phase verify runs from the orchestrator worktree (shared git
checkout) repeatedly dirty tracked files under `scripts/test/fixtures/`. Subsequent `merge-run-next` attempts
fail with fixture drift until the operator resets the tree:

```bash
git checkout -- scripts/test/fixtures/
```

(in the orchestrator worktree cwd).

## Evidence

- Recurring deliver ops note from PRD 048 session: parallel verify keeps re-polluting fixture paths.
- Many harnesses resolve `ROOT` / `SW_REPO_ROOT` from the caller worktree and write fixture artifacts in-place
  (e.g. `run_parallel_merge_safety_fixtures.py`, `run_planning_graph_fixtures.py`, capability-lint/select
  trees).
- Orchestrator worktree shares the same tracked `scripts/test/fixtures/` tree as the primary checkout — phase
  worktrees are isolated, but verify invoked from orchestrator cwd is not.

## Operator workaround

Before retrying `merge-run-next` after fixture-drift failure:

```bash
cd .sw-worktrees/<slug>-orchestrator   # orchestrator worktree
git checkout -- scripts/test/fixtures/
```

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **gap-014** | Capability `gateRef` `.sh` regression + optional deliver hygiene doctor — narrower than full fixture-tree mutation |
| **PRD 035 R29** | `parallel-wave-regen-before-verify` — build-chain regen, not fixture isolation |
| **PRD 050 R17** | `capability-gateref-no-shell` — gateRef scan only |
| **GAP-061** (resolved) | Post-merge `verify:environmental` for golden/emitter drift — different class |
| **batch-integration-head-moved** | Documented intentional halt (`sw-deliver` step 6) — separate from fixture pollution |

## Remediation direction

1. Run verify fixture suites against temp/copy trees or `mktemp` roots — never mutate tracked
   `scripts/test/fixtures/` during deliver verify.
2. Pre-merge / pre-`merge-run-next` doctor: fail closed when `git status --porcelain scripts/test/fixtures/`
   is non-empty in orchestrator worktree (extends gap-014 remediation #2).
3. Fixture `deliver-verify-fixture-tree-immutable` proves parallel-wave verify leaves tracked fixtures clean.
