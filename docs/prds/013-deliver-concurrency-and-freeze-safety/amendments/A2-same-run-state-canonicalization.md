---
date: 2026-06-26
amends: docs/prds/013-deliver-concurrency-and-freeze-safety/013-prd-deliver-concurrency-and-freeze-safety.md
frozen: true
frozen_at: 2026-06-26
---

# Amendment A2: same-run canonical deliver-state write path (orchestrator-worktree vs repo-root)

## Overview

PRD 013 scopes deliver run-state **per target branch** (`.cursor/sw-deliver-state.<slug>.json`) and mandates a
shared resolver for "every deliver state/lock reader and writer" (R6–R12, R9, TR3). That work addresses the
**concurrency axis** — disjoint branches must not collide. GAP-BACKLOG row 35 reports a **second, orthogonal
axis** the parent does not close: within a *single* run, durable deliver state has two physical copies after
the orchestrator worktree is provisioned — the repo-root `.cursor/sw-deliver-state.json` and the orchestrator
worktree's `.cursor/sw-deliver-state.json`.

Because the writers persist via a **cwd-relative** `save_state(root, …)` (`scripts/wave_deliver_loop.py` and
`scripts/wave_compound.py`), a `/sw-compound-ship --pre-merge` → `record-premerge` executed inside the
orchestrator worktree writes `compoundShip` + `completion.completed-pending-merge` **only** to the orchestrator
copy. The **read** path was already partially fixed (`cleanup_lib.resolve_deliver_state` prefers the
orchestrator copy when newer/terminal — PR #75), but the **write** path is not unified: deliver-loop / agents
reading the repo-root state miss `compoundShip`, can re-offer `compound-ship`, or mis-report terminal progress
(stale root `verdict: running` lingering after the terminal PR).

This amendment adds one requirement (R28) unifying the deliver-state **write** path on a single canonical
location, extending PRD 013's read+write resolver (TR3) from the per-branch-naming axis to the
orchestrator-worktree-vs-repo-root **same-run** axis. It is purely additive and contradicts no parent
requirement.

## Context

The relevant surfaces:

- `scripts/wave_deliver_loop.py` `save_state(root, state)` and `scripts/wave_compound.py`
  `state_path(root)` / `save_state(root, state)` write `root/.cursor/sw-deliver-state.json` where `root` is
  derived from the **current working directory**, not a resolved canonical path.
- `scripts/wave_compound.py` `record-premerge` calls `save_state(root, …)` — so the orchestrator-cwd run
  lands `compoundShip.premergeDone` only in the orchestrator copy.
- `scripts/cleanup_lib.py` `resolve_deliver_state(repo_root)` already computes a `canonical_root` by
  preferring the orchestrator copy when it is newer/terminal — the read-side precedent this amendment reuses
  for writes.

PRD 013 R9 already enumerates `wave_compound.py`, `wave_state.py`, `wave_failure.py`, `wave_deliver_loop.py`,
and `cleanup_lib.py` as resolver consumers, and TR3 specifies a "shared resolver (read + write)". R28 makes
that read+write parity explicitly cover the dual-physical-copy axis; it is **distinct** from row 24 /
parent R6–R12 (concurrent per-PRD locking) — this is *same-run* drift, not cross-run collision.

## Goals

1. Within a single run, every deliver-state write — from the repo-root cwd or the provisioned orchestrator
   worktree cwd — converges on one canonical physical state file, so readers never miss `compoundShip` /
   `completion` written from the other cwd.
2. `record-premerge` and any compound/completion write are observable from the repo-root-resolved state, so
   deliver-loop and agents do not re-offer `compound-ship` or mis-report terminal progress.
3. The canonical deliver-state source of truth is documented and fixture-guarded.

## Non-Goals

- Per-branch scoping, locking, identity, or legacy migration (PRD 013 R6–R12) — unchanged; this is the
  same-run dual-copy axis, not the concurrent-run axis.
- Changing the terminal-autonomy chain (PRD 013 A1 R20–R27) — unchanged.
- Changing the freeze-commit / spec-seed machinery (PRD 013 R1–R5) — unchanged.
- Introducing a new config knob — row 35 is explicitly **not** a missing `workflow.config.json` knob; this is
  a resolver/write-path fix.
- Re-architecting the orchestrator-worktree provisioning model — only the state write target is canonicalized.

## Requirements

R-IDs continue PRD 013's namespace (parent + A1 end at R27; this amendment adds R28). Purely additive — no
parent requirement is superseded or retracted.

- **R28** The deliver-state **write** path MUST resolve a single canonical state location with read/write
  parity, so that within one run, writes issued from any cwd — the repo root OR the provisioned orchestrator
  worktree — converge on one physical state file. Concretely:
  - **R28a** `scripts/wave_compound.py` `record-premerge` (and any compound/`completion` write) MUST resolve
    the canonical state path via the shared resolver (the `cleanup_lib.resolve_deliver_state` /
    `wave_state.py` read+write resolver mandated by parent R9/TR3) rather than an unconditional cwd-relative
    `save_state(root, …)`. This extends parent R9/TR3 from the per-branch-naming axis to the
    orchestrator-worktree-vs-repo-root axis.
  - **R28b** When `orchestratorWorktree.path` is set, a canonical write MUST be observable from the
    repo-root-resolved state (by writing the canonical path or mirroring), so a deliver-loop / agent reading
    repo-root state sees `compoundShip.premergeDone` and `completion.completed-pending-merge` and does not
    re-offer `compound-ship` or mis-report terminal progress. A stale root `verdict: running` MUST NOT linger
    after a terminal write resolved through the canonical path.
  - **R28c** The canonical deliver-state source of truth (which physical copy is authoritative, and that
    reads and writes resolve identically) MUST be documented in `.sw/layout.md`.
  - **R28d** Reconciliation of the non-canonical duplicate copy on orchestrator teardown / terminal
    completion is permitted as hygiene but MUST NOT delete or overwrite a copy that a still-`in-flight`
    reader depends on (consistent with parent R10 enumeration and PRD 017 R17 teardown guards).

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `deliver-state-canonical-write-from-orchestrator` | after `record-premerge` run from the orchestrator-worktree cwd, the canonical (repo-root-resolved) state contains `compoundShip.premergeDone` + `completion.completed-pending-merge` | R28, R28a, R28b |
| `deliver-state-no-stale-running-after-terminal` | a terminal write resolved through the canonical path clears repo-root `verdict: running`; deliver-loop does not re-offer `compound-ship` | R28b |
| `deliver-state-canonical-docs-presence` | `.sw/layout.md` documents the canonical deliver-state SoT (read/write parity) | R28c |

These extend `run-deliver-loop-fixtures.sh` / `run-state-fixtures.sh`. Emitter propagation (`dist/`) and the
`.sw/layout.md` doc update fold into **parent R17/R19** on task regeneration — no new doc/dist phase.

## Implementation note (task integration)

This amendment adds R28 (with R28a–R28d) to the PRD 013 spec union. The frozen task list
`tasks-013-deliver-concurrency-and-freeze-safety.md` MUST be regenerated against the union (R1–R28, including
A1 R20–R27) before implementation so R28 carries a task + traceability. R28 attaches to the **scoped
state/lock resolver phase** (parent Phase 2, the TR3 resolver work) since it extends that resolver to the
same-run dual-copy axis; its `.sw/layout.md` + emitter work merges into the parent R17/R19 tasks. No new
feature branch — same `feat/deliver-concurrency-and-freeze-safety`.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-13 (PRD 013) | Amend PRD 013 (not PRD 017, not a standalone PRD) | The fix is the deliver-state read+write resolver TR3 already owns; R9 already enumerates `wave_compound.py`/`wave_state.py`/`cleanup_lib.py`. PRD 017 explicitly Non-Goals "deliver state/lock scoping (PRD 013)". Co-locating with the resolver work avoids two PRs touching the same state path. |
| DL-14 (PRD 013) | Reuse the existing `resolve_deliver_state` canonical-root precedent for the write path | The read path already canonicalizes (PR #75); extending the same resolver to writes gives read/write parity with no new resolution model (feasibility + coherence lenses). |
| DL-15 (PRD 013) | Additive (no supersede); same-run axis is distinct from parent R6–R12 concurrency | Row 35 is same-run dual-copy drift, not cross-run collision; R28 composes with per-branch scoping rather than changing it, so no parent requirement is contradicted (scope-guardian lens). |
| DL-16 (PRD 013) | No new config knob | Row 35 states this is not a missing knob; a resolver/write-path fix is the correct mechanism and avoids config surface creep (scope-guardian lens). |

## Open Questions

None.
