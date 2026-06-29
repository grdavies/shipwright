---
date: 2026-06-29
amends: docs/prds/033-lifecycle-dependencies-and-scheduler/033-prd-lifecycle-dependencies-and-scheduler.md
absorbs: [GAP-053, GAP-055]
frozen: true
frozen_at: 2026-06-28
---

# Amendment A1: Post-merge INDEX reconcile safety + completion-finalize chokepoint

## Overview

After PRD 036 shipped (terminal squash-merge **PR #195**), post-merge bookkeeping exposed two coupled
defects in the legacy living-doc path that this amendment closes before the PRD 033 reconciler cutover:

1. **INDEX backward regression.** A manual `reconcile-status.sh reconcile` run from repo root on `main`
   committed local-only corruption: **11 PRD rows regressed** from `complete`/`superseded` to
   `not-started`/`in-progress` (local commit `50ce3d4`). Contributing context: stale local feature branches
   skewed active-branch detection; slug-scoped deliver state omitted older completed runs; merge-detection
   returned `not-started` for already-merged slugs. `origin/main` was unaffected; recovery was
   `git reset --hard origin/main` plus scoped `set-index-status` / `append-log-idempotent` on a docs branch
   (**PR #196**).
2. **Completion-state bypass.** Deliver state was mutated to `merged-complete` out of band, so
   `wave.sh completion finalize-if-merged` failed its `completed-pending-merge` guard; the operator fell
   back to manual full-corpus `reconcile` on `main` — the wrong entrypoint.

This amendment extends PRD 033's maintenance reconciler and deliver-writer contracts so derived INDEX status
is **git-ancestry-primary**, **monotonic** at terminal states, **default-branch-safe**, and paired with a
**completion-finalize chokepoint** that blocks the bypass chain. It continues the parent R-ID namespace
(parent ends at **R28**) with **R29–R36**. It absorbs **GAP-053** (derived `complete` forward drift) and
**GAP-055** (completion-state bypass + wrong post-merge entrypoint). It does not modify the parent file.

## Context

Parent PRD 033 already makes the reconciler the sole writer of the `derived` INDEX region (R13/R16) and
defines `complete` as mechanically derived (R2). GAP-053 noted that coverage was implicit and that
`COMPLETION-LOG.md` must not be the authoritative `complete` predicate. The PRD 036 incident adds a worse
class: **terminal rows downgrading** after a full-corpus reconcile in a poisoned local context, plus an
operator playbook gap (bare `reconcile` on `main` instead of scoped tools or the guarded finalizer).

GAP-055 is absorbed here rather than left as a standalone deliver patch because the INDEX monotonicity,
default-branch guard, and relief corpus extensions are reconciler-owned (parent R13/R21/R22). The
completion-state chokepoint is bundled as deliver-writer requirements (R33–R34) that the reconciler and
post-merge operator docs depend on.

## Goals

1. **No terminal downgrade.** `complete` and `superseded` derived rows never regress without an explicit
   override.
2. **Git-primary `complete`.** Merge ancestry on `defaultBaseBranch` (and host merge metadata when
   available) is the authoritative `complete` signal — not the append-only COMPLETION-LOG alone.
3. **No reconcile commits on `main`.** Full-corpus reconcile refuses to commit on the default branch;
   single-unit post-merge bookkeeping uses scoped primitives on a docs branch.
4. **Single completion-finalize writer.** Only `finalize-if-merged` may set `merged-complete`; out-of-band
   state mutation is rejected, preventing the bypass that triggered manual reconcile.

## Non-Goals

- Changing the human merge-to-`main` gate.
- Re-implementing PRD 032 in-flight signal writers — the reconciler remains read-only on `inFlight`.
- Retroactive repair of historical INDEX drift (relief corpus + doctor warnings only).

## Requirements

- **R29** Derived `complete` for non-gap units is determined from **git facts first**: the unit's terminal
  integration/feature branch is an ancestor of `defaultBaseBranch` (or a squash-merge of it is),
  corroborated by host PR merge metadata when available. Slug-scoped deliver state is a **secondary**
  input. The append-only COMPLETION-LOG is audit-only — never the sole `complete` predicate (extends
  GAP-053).
- **R30** Terminal lifecycle states (`complete`, `superseded`) are **monotonic** in the derived INDEX
  region: the reconciler MUST NOT downgrade a row unless an explicit `--override-status` names the unit id,
  prior status, new status, and reason. Default reconcile is a no-op for terminal rows when git/deliver
  evidence still supports the terminal state.
- **R31** The maintenance reconciler and any legacy `reconcile-status.sh reconcile` shim it replaces MUST
  **refuse to commit** when the current git branch is `defaultBaseBranch`. Exit non-zero with an actionable
  message naming the allowed post-merge path: `set-index-status` + `append-log-idempotent` on a docs branch
  for single-unit updates; full-corpus reconcile only through the reconciler entrypoint on a non-default
  branch or via the deliver completion finalizer. A `--allow-default-branch` escape hatch exists for
  fixtures/CI only and MUST log actor + reason.
- **R32** Reconcile inputs MUST degrade safely when local branch inventory is stale: presence of a local
  feature branch MUST NOT imply `in-progress` when git ancestry and host merge metadata show the unit
  terminal. The precedence order is documented in `core/skills/living-status/SKILL.md`.
- **R33** Only `wave_compound.py:cmd_completion_finalize_if_merged` (invoked via
  `bash scripts/wave.sh completion finalize-if-merged`) may transition `completion.status` from
  `completed-pending-merge` to `merged-complete` and set `mergedAt` (GAP-055 chokepoint). Direct hand-edits
  or ad-hoc `wave_state` saves that set `merged-complete` without passing the finalizer are rejected at the
  save guard (exit non-zero, no partial write).
- **R34** The deliver-loop post-merge path invokes `finalize-if-merged` only; on guard failure it emits a
  consolidated halt with `resumeCommand` and MUST NOT suggest bare `reconcile-status.sh reconcile`. Operator
  docs (`sw-retrospective.md`, `sw-status.md`) state the post-merge playbook: single-unit bookkeeping on a
  **docs branch**; never full-corpus `reconcile` on `main`.
- **R35** The relief acceptance corpus (extends parent R22) MUST include, at minimum:
  1. **Forward drift (GAP-053):** unit merged to `main` but INDEX `not-started` → reconciled `complete`.
  2. **Backward regression (PRD 036):** INDEX row `complete` with terminal branch ancestor of `main`, but
     reconcile context with stale local branches and missing slug-scoped deliver state → derived status stays
     `complete`.
  3. **Monotonic guard:** attempted downgrade `complete` → `not-started` without override → reconcile
     refuses / no-op.
  4. **Branch guard:** `reconcile` on `main` → exit non-zero; no INDEX commit.
  5. **Finalize chokepoint:** premature `merged-complete` write rejected; valid `finalize-if-merged`
     succeeds.
- **R36** Documentation updates (as acceptance criteria): extend `core/skills/living-status/SKILL.md` and
  `core/commands/sw-status.md` with the post-merge playbook, monotonic terminal status, default-branch
  reconcile refusal, and finalize-only completion transition.

## Technical Requirements

- **TR-A1-1** (R29–R32) Extend the maintenance reconciler (`scripts/planning-graph.sh reconcile` or
  equivalent) and the legacy shim until cutover: git-ancestry `complete` predicate, monotonic terminal merge,
  default-branch commit refusal, stale-branch precedence.
- **TR-A1-2** (R33) Add a save-time guard in `scripts/wave_state.py` (or `wave_compound.py` sole writer
  wrapper) that rejects `completion.status: merged-complete` unless the call stack originates from
  `cmd_completion_finalize_if_merged` or carries an explicit fixture-only token.
- **TR-A1-3** (R34) Update `wave_deliver_loop.py` post-merge suggestion path and halt payloads; add
  fixtures under `scripts/test/run-compound-completion-fixtures.sh` and `run-living-doc-fixtures.sh`.
- **TR-A1-4** (R35) Register the five-case relief corpus in `core/sw-reference/pr-test-plan.manifest.json`.

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `reconcile-complete-from-git-ancestry` | merged-to-main unit with stale INDEX → `complete` |
| `reconcile-terminal-monotonic` | terminal row cannot downgrade without override |
| `reconcile-refuse-default-branch` | reconcile on `main` exits non-zero, no commit |
| `reconcile-stale-local-branches` | stale locals + missing deliver state do not downgrade `complete` |
| `completion-finalize-chokepoint` | out-of-band `merged-complete` rejected; finalizer succeeds |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A1-1 | Terminal derived status is monotonic and git-ancestry-primary | Closes PRD 036 INDEX regression and makes GAP-053 explicit (R29–R30). |
| DL-A1-2 | Default-branch reconcile commits are forbidden | Post-merge single-unit work stays on docs branches until reconciler owns full corpus (R31). |
| DL-A1-3 | `merged-complete` is finalize-only | Breaks the bypass chain that led to manual reconcile on `main` (R33–R34, GAP-055). |
| DL-A1-4 | GAP-053 and GAP-055 absorbed into PRD 033 A1 | Single reconciler + deliver-writer train; avoids an orphan deliver-only patch diverging from cutover. |

## Open Questions

None.
