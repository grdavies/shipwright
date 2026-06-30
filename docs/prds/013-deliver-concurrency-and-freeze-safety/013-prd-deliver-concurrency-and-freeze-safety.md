---
date: 2026-06-25
topic: deliver-concurrency-and-freeze-safety
brainstorm: docs/brainstorms/2026-06-25-deliver-concurrency-and-freeze-safety-requirements.md
frozen: true
frozen_at: 2026-06-25
---

# PRD 013 — Deliver concurrency and freeze safety

## Overview

Three open `GAP-BACKLOG.md` items harden the deliver/freeze infrastructure that PRDs 004 and 007 built:

1. **Freeze data-loss window.** `/sw-freeze` stamps `frozen: true` but commits nothing; frozen artifacts
   exist only as working-tree edits until `spec-seed` runs at `deliver-loop` entry — possibly sessions
   later. A stray `git checkout -f` / `git clean -fd` / stash-drop destroys expensive PRD Q&A.
2. **Single-concurrent deliver.** `wave_deliver_loop.py` uses one repo-wide `.cursor/sw-deliver-state.json`
   and one repo-wide `.cursor/sw-deliver.lock`; `assert_run_identity` rejects a differing `--task-list`
   (exit 20) and the exclusive lock fails regardless of target branch. Orthogonal product areas cannot
   deliver in parallel.
3. **`/sw-deliver` v1 deferrals.** Cross-feature waves, file-set edge inference, a live per-phase dashboard,
   and durable contention feedback into `/sw-tasks` re-runs all remain open.

This PRD closes the data-loss window **without** violating PRD 005 frozen amendment A2 (it commits frozen
docs onto `<type>/<slug>`, never `main`), scopes deliver state and locks per feature branch for safe
parallelism, and lands the remaining v1 deferrals. It derives from the frozen brainstorm
`docs/brainstorms/2026-06-25-deliver-concurrency-and-freeze-safety-requirements.md` (R1–R19).

## Goals

1. A frozen artifact survives a destructive working-tree operation because it is committed onto
   `<type>/<slug>` immediately at freeze — and never lands on `main`.
2. Orthogonal PRDs deliver concurrently with independent per-branch state files and locks; neither blocks
   nor corrupts the other, and shared living docs stay consistent.
3. `/sw-status` and `/sw-cleanup` enumerate every in-flight deliver run.
4. A plan with no explicit `## Phase Dependencies` parallelizes via inferred file-set edges; a cross-feature
   plan runs phase-mode and multi-feature units together; contention serialization produces durable,
   actionable feedback.

## Non-Goals

- Auto-merging to `main`, force-push, or changing the terminal human merge gate (PRD 004/007 invariants).
- Committing frozen docs to `main` (would violate PRD 005 A2 R80–R82; see DL-1).
- Changing the secret-scan / range-scoped-redaction guardrails (PRD 007 R41/R42/R50–R52).
- A full graphical dashboard beyond a terminal / `/sw-status` view.
- Automatic re-tasking: contention feedback is a suggestion, not an automatic `/sw-tasks` rewrite.
- Cross-repository parallelism.

## Requirements

R-IDs are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### Freeze data-loss safety

- **R1** `/sw-freeze`, on stamping a tracked artifact under `docs/prds/<n>-<slug>/` (PRD, task list, or
  amendment), MUST commit that frozen artifact onto the resolved feature branch `<type>/<slug>` immediately
  after stamping, closing the working-tree-only data-loss window.
- **R2** The freeze commit MUST be docs-only (no implementation files), MUST exclude `docs/brainstorms/**`
  and any untracked or ignored path, and MUST be idempotent — a no-op when the artifact is already committed
  on the branch.
- **R3** The freeze commit MUST target `<type>/<slug>` (creating it from the default branch when absent) and
  MUST NOT commit to `main`, preserving PRD 005 A2 R80–R82 so the spec lands in the `<type>/<slug>` →
  `main` PR diff. Branch derivation MUST reuse the shared `/sw-deliver` resolver, never a divergent copy.
- **R4** The freeze commit MUST NOT block or alter the freeze verdict: a branch or commit failure surfaces
  as a warning while the frontmatter stamp and INDEX entry still complete. An artifact is never left
  unstamped because the commit failed.
- **R5** The freeze-time commit and the `/sw-doc` afterTasks spec-seed MUST be the same single-sourced
  idempotent helper, so a later seed is a no-op against an already-committed freeze and the two paths cannot
  diverge.

### Per-branch deliver concurrency

- **R6** Deliver run-state MUST be scoped per target feature branch (`.cursor/sw-deliver-state.<slug>.json`)
  rather than one repo-wide state file, so orchestrators for disjoint branches do not collide.
- **R7** The orchestrator lock MUST be scoped per target branch (`.cursor/sw-deliver-<slug>.lock`) so a
  `lock acquire --nonblock` for one branch does not block a concurrent run on a different branch; a
  concurrently live run on the SAME branch MUST still be refused, preserving PRD 007 R44 liveness and
  stale-reclaim semantics within each scope.
- **R8** `assert_run_identity` MUST scope identity to the per-branch state file: a `deliver-loop
  --task-list` for branch A MUST NOT be rejected because branch B has an in-progress run; the stale-state
  halt applies only within the same scope.
- **R9** Every deliver state/lock reader and writer MUST resolve the scoped path from the target branch via
  a shared resolver — no hardcoded repo-wide `.cursor/sw-deliver-state.json` or `.cursor/sw-deliver.lock`
  may remain in `wave_deliver.py`, `wave_deliver_loop.py`, `wave_merge.py`, `wave_lifecycle.py`,
  `wave_bookkeeping.py`, `wave_memory.py`, `wave_failure.py`, `wave_compound.py`, `wave_terminal.py`,
  `wave_living_docs.py`, `wave_state.py`, `tasks-currency-gate.py`, `docs-currency-gate.py`,
  `ship-phase-status.py`, `cleanup_lib.py`, or `reconcile-status.py`.
- **R10** A concurrent-run index MUST enumerate all live scoped runs so `/sw-status` can list and inspect
  every in-flight deliver run and `/sw-cleanup` in-flight protection covers every scoped run that holds a
  lock or open journal — not just one.
- **R11** A pre-existing legacy repo-wide `.cursor/sw-deliver-state.json` MUST be adopted or migrated to its
  scoped path on first scoped read (keyed by its `source_task_list`), so an in-flight legacy run is not
  orphaned by the scoping change.
- **R12** Per-branch lock scoping MUST NOT remove living-doc serialization: concurrent runs MUST still be
  prevented from corrupting shared living docs (`INDEX.md`, `CHANGELOG.md`, `COMPLETION-LOG.md`) via the
  existing contention model.

### `/sw-deliver` v1 deferrals

- **R13** `/sw-deliver` planning MUST support a single plan that mixes phase-mode units and multi-feature
  units (cross-feature waves), with wave planning honoring both edge sources, rather than treating them as
  mutually exclusive modes.
- **R14** When phase metadata omits explicit dependencies, the planner MUST infer wave edges from declared
  file sets (overlapping `**File:**` paths imply an edge) as a fallback above strict sequential; an explicit
  `## Phase Dependencies` table always takes precedence.
- **R15** The minimal `run.log` plus terminal report MUST be extended with a live per-phase status view
  (phase, status, attempt, blocker) consumable by `/sw-status` during an in-flight run.
- **R16** When wave planning serializes phases due to living-doc or file contention, the notice MUST be
  persisted durably and surfaced as actionable feedback for a `/sw-tasks` re-run (for example a suggested
  explicit edge), not only an ephemeral runtime log.

### Cross-cutting

- **R17** All behavior authored in `core/` MUST be propagated to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all`, with the emitter freshness gate (`scripts/test/run-emitter-fixtures.sh`)
  passing.
- **R18** New behaviors MUST be covered by fixtures (see Testing Strategy).
- **R19** Documentation MUST be updated — `skills/deliver/SKILL.md`, `skills/conductor/SKILL.md`,
  `rules/sw-workflow-sequencing.mdc`, `.sw/layout.md` (scoped state/lock paths), and relevant guides — to
  describe freeze-time commit, per-branch scoping, the concurrent-run index, and the landed v1 deferrals.

## Technical Requirements

- **TR1 — Freeze commit hook.** Extend `core/commands/sw-freeze.md` and add the mechanical step that, after
  stamping, invokes the shared spec-seed helper scoped to the single artifact path. The helper commits onto
  `<type>/<slug>` using non-switching git plumbing (it MUST NOT change the operator's current checkout or
  branch); idempotent; docs-only; brainstorm-excluded; never `main` (R1–R3, R5). The step is wrapped so a
  failure logs a warning and returns success to the freeze verdict (R4).
- **TR2 — Shared seed helper reuse.** Reuse `scripts/wave_spec_seed.py` / `bash scripts/wave.sh spec-seed`
  (PRD 007 R57 single idempotent owner). If it currently seeds the whole `docs/prds/<n>-<slug>/` set,
  generalize it to accept a single artifact (or accept that freezing any artifact seeds the whole frozen set
  idempotently). `/sw-doc` afterTasks calls the same helper (R5).
- **TR3 — Scoped state/lock resolver.** Add a shared resolver (e.g. `wave_state.py` `scoped_paths(target)`)
  that maps a target branch/slug → `.cursor/sw-deliver-state.<slug>.json` + `.cursor/sw-deliver-<slug>.lock`.
  Replace every hardcoded repo-wide path (R9 enumeration) with a call through the resolver, deriving the
  slug from `--task-list`/target branch (R6, R7, R9).
- **TR4 — Scoped identity + lock semantics.** `assert_run_identity` keys on the scoped state file (R8);
  `lock acquire`/`reclaim` operate on the scoped lock and retain PRD 007 R44 liveness/stale-reclaim, refusing
  a live same-scope run (R7).
- **TR5 — Concurrent-run index.** Add `.cursor/sw-deliver-runs/index.json` (or enumerate
  `.cursor/sw-deliver-state.*.json`) listing each live scoped run (slug, task list, verdict, lock holder);
  `/sw-status` reads it to list runs; `cleanup_lib.py` protects every scoped run with a lock/open journal
  (R10).
- **TR6 — Legacy migration.** On first scoped read, if a repo-wide `.cursor/sw-deliver-state.json` exists,
  adopt it to its scoped path keyed by `source_task_list` (move + leave a breadcrumb), so an in-flight
  legacy run resumes under the scoped path (R11).
- **TR7 — Living-doc serialization preserved.** The existing contention/serialization model (living-doc
  writes) MUST remain in force across concurrent scoped runs; add a fixture proving two parallel runs cannot
  corrupt `INDEX.md`/`CHANGELOG.md` (R12).
- **TR8 — Cross-feature wave planning.** `scripts/wave_deliver.py` plan MUST accept a plan unit set mixing
  phase-mode and multi-feature units and compute waves over the combined edge set (R13).
- **TR9 — File-set edge inference.** When `## Phase Dependencies` is absent, the planner infers edges from
  overlapping `**File:**` declarations between phases (fallback above sequential); explicit edges win (R14).
- **TR10 — Live per-phase status.** Extend `wave_living_docs.py` / the run report with a live per-phase view
  (status, attempt, blocker) that `/sw-status` renders mid-run (R15).
- **TR11 — Durable contention feedback.** Persist contention-serialization notices to a durable path and
  surface them as a `/sw-tasks` re-run suggestion (suggested explicit edge), not just a runtime log (R16).
- **TR12 — Emitter propagation.** Regenerate `dist/` via `python3 -m sw generate --all`; freshness gate must
  pass (R17).

## Security & Compliance

- **No new secret surface.** State/lock files and the run index are non-secret workflow artifacts; the
  freeze commit is docs-only and brainstorm-excluded (R2).
- **History integrity.** The freeze commit targets `<type>/<slug>` via non-switching plumbing and never
  `main` (R3); it does not rewrite history and does not touch the PRD 007 range-scoped-redaction guardrail.
- **Merge gate unchanged.** No change to the terminal human merge gate, secret-scan, or push protections;
  parallelism is in planning/state only (Non-Goals).
- **Concurrency safety.** Per-scope locks retain liveness/stale-reclaim (R7); living-doc serialization is
  preserved so parallel runs cannot corrupt shared docs (R12).

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably
`run-deliver-fixtures.sh`, `run-deliver-loop-fixtures.sh`, `run-state-fixtures.sh`, `run-cleanup-fixtures.sh`).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `freeze-commit-on-feature-branch` | freeze commits the frozen artifact onto `<type>/<slug>`, never `main` | R1, R3 |
| `freeze-commit-idempotent-docs-only` | second freeze is a no-op; impl files + `docs/brainstorms/**` excluded | R2 |
| `freeze-commit-verdict-independent` | a commit/branch failure warns but the stamp + INDEX entry still complete | R4 |
| `freeze-seed-single-source` | freeze-time commit and afterTasks seed use the same helper; no double commit | R5 |
| `deliver-state-scoped-per-branch` | run-state resolves to `.cursor/sw-deliver-state.<slug>.json` | R6 |
| `deliver-lock-no-cross-block` | lock for branch A does not block branch B; same-branch live run refused | R7 |
| `deliver-identity-scoped` | `assert_run_identity` for branch A not rejected by branch B's run | R8 |
| `deliver-no-repo-wide-path` | no hardcoded repo-wide state/lock path remains in the audited scripts | R9 |
| `deliver-run-index-enumerates` | `/sw-status` + `/sw-cleanup` enumerate/protect every live scoped run | R10 |
| `deliver-legacy-state-migration` | a legacy repo-wide state file is adopted to its scoped path | R11 |
| `deliver-living-doc-serialized` | two parallel scoped runs cannot corrupt `INDEX.md`/`CHANGELOG.md` | R12 |
| `deliver-cross-feature-wave-plan` | one plan mixes phase-mode + multi-feature units; waves honor both | R13 |
| `deliver-file-set-edge-inference` | absent `## Phase Dependencies` → edges inferred from file overlap; explicit wins | R14 |
| `deliver-live-phase-status` | `/sw-status` renders a live per-phase view mid-run | R15 |
| `deliver-contention-durable-feedback` | serialization notice persisted + surfaced as a `/sw-tasks` suggestion | R16 |
| `deliver-concurrency-emitter-freshness` | `dist/` regenerated and fresh | R17 |
| `deliver-concurrency-docs-presence` | deliver/conductor skills, sequencing rule, `.sw/layout.md` describe the changes | R19 |

R18 is satisfied by this fixture set itself. Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/deliver-concurrency-and-freeze-safety`, delivered in dependency-ordered
  phases: (1) freeze-time commit + shared-helper reuse (R1–R5); (2) scoped state/lock resolver + identity +
  legacy migration (R6–R9, R11); (3) concurrent-run index + `/sw-status` / `/sw-cleanup` enumeration +
  living-doc serialization fixture (R10, R12); (4) v1 deferrals — cross-feature waves, file-set edge
  inference, live status, durable contention feedback (R13–R16); (5) docs + dist + fixtures (R17–R19).
- **Backward compatible.** Legacy repo-wide state is migrated on first scoped read (R11); absent scoping
  inputs resolve deterministically from the task list. The freeze commit is additive and verdict-independent
  (R4), so existing freeze flows are unaffected on failure.
- **Bootstrap caution.** Because this PRD repairs deliver state/lock machinery, the first delivery SHOULD be
  supervised (`doc.afterTasks: confirm` or `--after-tasks stop`) until the scoped-state fixtures are green
  (mirrors PRD 007 DL-9).
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Freeze commits frozen docs onto `<type>/<slug>`, never `main` | Closes the data-loss window while preserving PRD 005 frozen amendment A2 (spec in feature → `main` PR diff). The gap row's literal `main` proposal would supersede A2 R80–R82 and require a separate PRD 005 amendment; rejected to avoid silently overriding a frozen doc. (operator declined to pick; recommended path taken) |
| DL-2 | Reuse the single idempotent spec-seed helper for both freeze-time commit and afterTasks seed | Single source prevents divergence; idempotency makes the later seed a no-op (R5; reinforces PRD 007 R57). |
| DL-3 | Freeze commit is verdict-independent (warn-not-block) | A repo/branch hiccup must never leave an artifact unstamped or block the freeze; durability is best-effort-additive (R4; adversarial lens). |
| DL-4 | Scope deliver state + lock per target branch via a shared resolver | Per-file scoping matches the existing one-file machinery and locks granularly; a single multi-run file invites cross-run corruption (R6–R9; feasibility lens). |
| DL-5 | Preserve living-doc serialization across parallel runs | Per-branch locks remove orchestrator collisions but not shared-doc contention; dropping serialization would corrupt `INDEX.md`/`CHANGELOG.md` (R12; adversarial lens). |
| DL-6 | Explicit `## Phase Dependencies` always beats inferred file-set edges | Author intent must win; inference is a fallback above strict sequential only (R14; scope-guardian lens). |
| DL-7 | Contention feedback is a durable suggestion, not an automatic `/sw-tasks` rewrite | Auto-rewriting frozen tasks would breach freeze discipline; a surfaced suggestion keeps the human in the loop (R16; product + scope-guardian lenses). |

## Open Questions

None. The freeze-to-`main`-versus-A2 conflict is resolved in DL-1 (commit onto `<type>/<slug>`); the
operator declined to choose among options, so the recommended A2-preserving path was adopted and the
rejected `main` alternative is recorded with its amendment requirement.
