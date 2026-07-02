---
date: 2026-07-02
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
absorbs: [gap-019-parallel-deliver-verify-mutates-tracked-scripts-]
signal: feedback-prd-048-deliver-observations-2026-07-02
frozen: true
frozen_at: 2026-07-02
visibility: public
---

# Amendment A5: deliver verify fixture-tree immutability (gap-019)

## Overview

`gap-019` captures recurring deliver ops friction during PRD 048 deliver: parallel phase verify runs from the
orchestrator worktree dirty tracked files under `scripts/test/fixtures/`, causing `merge-run-next` fixture
drift until the operator runs `git checkout -- scripts/test/fixtures/` in the orchestrator worktree.

Parent PRD 050 Thread D (R17–R19) covers gap-014 capability `gateRef` `.sh` regression (R17) and all-private
visibility (R18–R19) but does not specify **fixture-tree immutability** during parallel-wave deliver verify or a
pre-`merge-run-next` doctor for orchestrator-worktree fixture drift. gap-014 remediation #2 (deliver hygiene
doctor) was never fully specified beyond the narrow gateref scan.

This amendment extends Thread D with **R51–R54** and closes **gap-019** when shipped with green fixtures —
not narrative closure.

## Context

**PRD 048 evidence (2026-07-02):**

- Multi-phase deliver with parallel verify; orchestrator worktree cwd shares tracked `scripts/test/fixtures/`.
- `merge-run-next` fails with fixture drift; operator resets via `git checkout -- scripts/test/fixtures/`.
- Recurring pattern alongside documented `batch-integration-head-moved` halts (separate, intentional safety).

**Root cause:**

Many `run_*_fixtures.py` harnesses resolve `ROOT` / `SW_REPO_ROOT` from the caller worktree and write
artifacts in-place under `scripts/test/fixtures/` (e.g. `run_parallel_merge_safety_fixtures.py`,
`run_planning_graph_fixtures.py`, capability-lint/select trees). Phase worktrees are isolated; orchestrator
worktree verify is not.

**Relationship to gap-014:** R17 closes the capability `gateRef` `.sh` subset; A5 closes the broader
fixture-tree mutation class and implements gap-014 remediation #2 (deliver hygiene doctor) for
`scripts/test/fixtures/` in the orchestrator worktree.

## Goals

1. Deliver verify MUST NOT leave tracked `scripts/test/fixtures/` dirty in the orchestrator worktree after
   parallel-wave runs.
2. Pre-`merge-run-next` doctor fails closed with remediation when fixture-tree drift is detected (orchestrator
   cwd), instead of opaque merge/fixture failures later.
3. `gap-019` flips to `resolved` when R51–R54 ship with green fixtures.

## Non-Goals

- Replacing PRD 052 registry / verify-bundle single-source work (complete).
- Isolating build-chain / golden-manifest drift (PRD 035 R27–R29 environmental verify — separate class).
- Changing `batch-integration-head-moved` intentional halt semantics.

## Requirements

### Thread D extension — deliver verify fixture hygiene

- **R51** (origin: gap-019 remediation #1) — Phase deliver verify harnesses MUST run fixture suites against
  ephemeral roots (`mktemp`, copy-tree, or equivalent) — never mutate tracked `scripts/test/fixtures/` in the
  orchestrator worktree during `/sw-ship` verify. Applies to harnesses invoked from `run_verify_bundle.py` /
  pr-test-plan manifest paths used on the deliver verify surface.
- **R52** (origin: gap-019 remediation #2, extends gap-014 #2) — Before `merge-run-next`, deliver loop MUST
  fail closed when `git status --porcelain scripts/test/fixtures/` is non-empty in the orchestrator worktree
  (resolved via `integration_branch_head` / orchestrator path conventions), emitting remediation to
  `git checkout -- scripts/test/fixtures/` or auto-clean only when safe (no staged implementation changes in
  that path).
- **R53** (origin: gap-019 remediation #3) — Fixture `deliver-verify-fixture-tree-immutable` MUST assert
  parallel-wave verify simulation leaves tracked `scripts/test/fixtures/` clean in an orchestrator-worktree
  fixture tree.
- **R54** (origin: gap-019 closure) — On ship, flip
  `gap-019-parallel-deliver-verify-mutates-tracked-scripts-` unit frontmatter to `resolved` referencing PRD
  050 A5 only after R51–R53 fixtures are green.

## Technical Requirements

- **TR28** (R51) — Audit deliver-verify fixture harness call sites; refactor writers to temp roots or
  read-only fixture inputs; preserve offline CI behavior for direct `run_*_fixtures.py` invocation from repo
  root in CI (non-deliver contexts may still use committed fixture trees read-only).
- **TR29** (R52) — Add `fixture_tree_clean_or_halt()` (or equivalent) in `scripts/wave_deliver_loop.py`
  invoked before `merge-run-next` and optionally before `merge enqueue`; resolve orchestrator worktree path
  from deliver state (`orchestratorWorktree.path`).
- **TR30** (R53–R54) — Add harness under `scripts/test/fixtures/deliver-concurrency/`; register
  `deliver-verify-fixture-tree-immutable` in `core/sw-reference/pr-test-plan.manifest.json` as `required`.

Roll into parent Thread D (tasks 4.x) after R17 gateref work (Decision D-A5-2).

## Testing Strategy

Add to parent Testing Strategy:

- `deliver-verify-fixture-tree-immutable` (R53, TR30)

Preserve `capability-gateref-no-shell` (R17) and parallel-wave environmental verify fixtures (PRD 035).
No regression to A4 `resume-reconcile-unpushed-local-merge-promotes`.

## Rollout Plan

1. Implement TR28 + R51 (harness temp-root isolation) — stops active pollution.
2. Land TR29 + R52 doctor before `merge-run-next` — fail-fast with remediation.
3. Land TR30 + R53 fixture registration.
4. On ship: flip gap-019 to `resolved`; attach `gap_backlog.py check` output to PR.

## Decision Log

- **D-A5-1 (2026-07-02):** Host gap-019 on **PRD 050 A5** (Thread D extension) alongside gap-014 R17 rather than
  PRD 049 — orchestrator fixture mutation is deliver-hygiene, not cwd-guard contract (gap-006 / PRD 049).
- **D-A5-2 (2026-07-02):** Implement R52 doctor after R51 harness isolation — doctor catches residual drift
  from harnesses not yet ported and external parallel sessions.
- **D-A5-3 (2026-07-02):** Do not auto-`git checkout` fixture paths when porcelain includes staged non-fixture
  mixed changes — emit remediation only (fail-closed).

## Security & Compliance

- Local git status checks only; no new network surface.
- Fail-closed when orchestrator worktree path cannot be resolved.

## Open Questions

None — gap-019 remediation direction is fully specified.
