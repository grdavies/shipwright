---
date: 2026-06-29
amends: docs/prds/033-lifecycle-dependencies-and-scheduler/033-prd-lifecycle-dependencies-and-scheduler.md
absorbs: [GAP-056]
frozen: true
frozen_at: 2026-06-29
---

# Amendment A3: Operator worktree contract (repo-root runtime vs worktrees)

## Overview

During PRD 036 deliver, operators observed repo-root activity during a run and assumed tracked files on
`main` were being mutated or copied **from** root **into** worktrees. Investigation (GAP-056) found **no
general root→worktree copy** and **no tracked commits on `main`** from deliver — but legitimate **gitignored**
repo-root `.cursor/` writes (canonical conductor state per PRD 013 R6/R9/R28) look identical to "main is
dirty" in the IDE. Real footguns remain: cwd-relative deliver-state reads, living-doc commits on the primary
checkout (partially addressed by A1 R31), and reconcile/retro from default branch while a run is in-flight.

This amendment extends PRD 033 with an **operator worktree contract**: what each checkout owns, which paths
are intentional repo-root runtime state, and fail-closed cwd guards so implementation commands cannot mutate
from the wrong checkout during an active deliver run. It continues the parent + A1 namespace (**R37–R43**;
parent ends at R28, A1 adds R29–R36). It absorbs **GAP-056**. It does not modify the parent file.

## Context

Parent PRD 033 and amendment A1 address reconciler safety and default-branch reconcile refusal (R31). GAP-056
is the **operator mental-model** gap: worktree isolation is correct at the git-merge layer but opaque at the
filesystem layer. PRD 007 R40/R55 (integration ref advancement, primary off feat branch), PRD 013 A2 R28
(canonical state path), and PRD 027 R4 (status.json mirror worktree→root) are **by design** — this amendment
makes that design visible and adds guards where cwd drift causes harm. Complements GAP-063 (dual-copy state
skew) without re-specifying all of PRD 013.

## Goals

1. Operators can distinguish **repo-root runtime state** (gitignored `.cursor/`) from **tracked implementation**
   on worktrees.
2. Work-performing commands fail closed when run from the primary checkout on `defaultBaseBranch` during an
   in-flight deliver run (unless an explicit documented escape exists).
3. Canonical deliver state is always read/written via `resolve_state_path(git_toplevel)` before terminal steps.
4. Phase ship mirrors terminal `status.json` to repo root with absolute `SW_REPO_ROOT` (GAP-042 alignment).

## Non-Goals

- Moving all `.cursor/` state into worktrees (repo-root canonical state remains per PRD 013).
- Changing orchestrator provision topology (integration branch stays in orchestrator worktree).
- Replacing PRD 036 concurrency/remediation requirements.
- A new standalone PRD — this is amendment A3 on complete PRD 033.

## Requirements

- **R37** `.sw/layout.md` MUST publish an **operator worktree contract** diagram/table covering: primary
  checkout (usually `defaultBaseBranch` after orchestrator provision), orchestrator worktree
  (`.sw-worktrees/<slug>-orchestrator` owns `<type>/<slug>`), phase worktrees (`.sw-worktrees/<slug>-phase-*`),
  and repo-root gitignored `.cursor/` (canonical deliver state, locks, run logs). It MUST state explicitly:
  `.cursor/` at repo root is **conductor runtime**, not feature implementation; copy direction for
  `status.json` is **phase worktree → repo root** (mirror), never a general root→worktree sync.
- **R38** `core/skills/conductor/SKILL.md` and `core/skills/deliver/SKILL.md` MUST echo the contract (R37):
  which checkout agents should run ship/execute in, that repo-root `.cursor/` updates during deliver are
  expected, and that tracked `main` must not accumulate implementation commits during a run.
- **R39** A fail-closed **in-flight cwd guard** MUST refuse (exit non-zero with remediation) when a
  work-performing surface runs from the primary checkout on `defaultBaseBranch` while a deliver run for the
  repo is `verdict: running` (read from repo-root canonical state index). Surfaces (minimum): `wave_living_docs`
  `--commit`, `reconcile-status.py reconcile`, `/sw-retrospective` write paths, and `wave_deliver_loop` manual
  living-doc reconcile suggestions. Extends A1 R31 (reconciler default-branch refuse) to **operator command
  entry**, not only the reconciler script.
- **R40** Before `retrospective`, `terminal-ship`, or `all-phases-complete`, deliver MUST
  `sync_canonical_state_read()` — load state via `resolve_state_path(git_toplevel)` not cwd-relative paths;
  on `save_state`, mirror to repo-root when `orchestratorWorktree.path` is set; terminal steps refuse when dual-copy
  `updatedAt` skew exceeds a documented threshold (closes GAP-028/063 residual).
- **R41** Phase-mode ship MUST set absolute `SW_REPO_ROOT` and mirror terminal `status.json` to the repo-root
  canonical path on every write (extends PRD 027 R4 / GAP-042); relative `SW_RUN_DIR` alone is insufficient.
- **R42** A fixture `deliver-worktree-contract` proves: after orchestrator provision + one `deliver-loop` tick,
  repo-root scoped state is updated, primary checkout remains on `defaultBaseBranch`, and **no tracked files on
  `main`** are modified.
- **R43** On ship, GAP-056 flips to `resolved — PRD 033 A3` via gap-resolve or manual reconcile.

## Technical Requirements

- **TR-A3-1** (R39) Implement `scripts/deliver_cwd_guard.sh` (or equivalent module) called from guarded entrypoints;
  detects in-flight run via `.cursor/sw-deliver-runs/index.json` + repo-root state; fixture:
  `deliver-cwd-guard-blocks-main-living-doc`.
- **TR-A3-2** (R40) Extend `wave_state.py` / `wave_deliver_loop.py` with `sync_canonical_state_read()` and skew
  threshold check before terminal actions; fixture: `terminal-reads-repo-root-state-from-orchestrator-cwd`.
- **TR-A3-3** (R41) Extend `ship-phase-status.py` / phase dispatch env to require `SW_REPO_ROOT` and perform
  repo-root mirror write; fixture: `phase-status-repo-root-mirror`.
- **TR-A3-4** (R37–R38, R42) Doc-currency fixtures for layout + conductor/deliver skills; register
  `deliver-worktree-contract` in `pr-test-plan.manifest.json`.

## Security & Compliance

- **R44** Guards operate on local paths and git state only; no new network or credential surface.

## Testing Strategy

- `deliver-worktree-contract` (R42) — end-to-end operator contract.
- `deliver-cwd-guard-blocks-main-living-doc` (R39).
- `terminal-reads-repo-root-state-from-orchestrator-cwd` (R40).
- `phase-status-repo-root-mirror` (R41).
- `doc-currency-033-a3-sections` (R37, R38).
- No regression to A1 default-branch reconcile refusal (R31) or finalize chokepoint (R33).

## Documentation deliverables (amendment delta)

- `.sw/layout.md` — worktree contract diagram (R37).
- `core/skills/conductor/SKILL.md`, `core/skills/deliver/SKILL.md` (R38).
- `core/sw-reference/layout.md` mirror if emitted (R37).

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A3-1 | Amendment on complete PRD 033, not a new PRD | Same lifecycle/reconciler workstream; GAP-056 is operator contract for deliver paths 033 already touches. |
| DL-A3-2 | Repo-root `.cursor/` stays canonical | PRD 013 R28; moving state into worktrees breaks cross-worktree resume. Contract is documentation + guards, not relocation. |
| DL-A3-3 | Cwd guard extends A1 R31 to command entrypoints | A1 refuses reconciler commits on `main`; GAP-056 also needs blocking living-doc/retro from primary during in-flight runs. |
| DL-A3-4 | R40/R41 align with GAP-063/GAP-042 without absorbing them wholesale | State sync and status mirror are specified here for operator trust; full parallel dispatch fixes remain elsewhere. |

## Open Questions

- None — GAP-056 investigation completed 2026-06-29. Proceed to implementation.
