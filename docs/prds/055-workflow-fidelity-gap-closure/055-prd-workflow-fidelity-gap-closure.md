---
frozen: true
frozen_at: 2026-07-02
absorbs:
  - gap-002-living-doc-reconcile-commits-bypass-r31-default-
  - gap-003-gap-doc-feedback-capture-has-two-unreconciled-fi
  - gap-007-finalize-completion-omits-terminal-living-docs-r
  - gap-008-inflight-signal-run-complete-commits-index-on-ma
  - gap-020-planning-index-gen-replace-region-inner-omits-n
  - gap-022-prd-054-unit-tests-must-be-excluded-from-copy-to
  - gap-023-sw-tasks-must-auto-emit-execute-tier-granular-su
  - gap-024-supersede-reconcile-subcommand-missing-after-rec
  - gap-025-deliver-advances-on-ship-green-not-phase-checklist
date: 2026-07-02
topic: workflow-fidelity-gap-closure
visibility: public
depends:
  - 054-unit-testing-strategy
blocks:
  - 044-issue-store-migration
  - 045-issue-native-dev-tracking
  - 046-issue-store-planning-graph
---

# PRD 055 — Workflow fidelity & standing gap closure

## Overview

Nine open canonical gap units share one theme: **file-store deliver and planning integrity** that later
programs assume is sound. They were previously scheduled against PRDs that are now **`complete`** (015, 035,
054) or drafted as **frozen amendments on not-yet-shipped PRDs** (046 A2/A3/A4, 045 A1) — leaving no active
implementation vehicle.

| Gap | Theme | Prior schedule (stale) |
| --- | --- | --- |
| gap-022 | Developer test trees leak into `core/scripts/` and `dist/` | PRD 054 |
| gap-024 | `supersede-reconcile` missing after `reconcile.py` consolidation | PRD 015 R7 |
| gap-020 | INDEX structural marker newline corruption on regenerate | PRD 046 A4 |
| gap-002 | `living-docs reconcile` commits on `defaultBaseBranch` | PRD 046 A1 dependency |
| gap-007 | Terminal `finalize-completion` omits INDEX `complete` flip | PRD 046 A2 |
| gap-008 | `inflight_signal run-complete` commits INDEX on `main` | PRD 046 A3 |
| gap-025 | Deliver merges phases on ship-green without checklist acceptance | PRD 035 A1 |
| gap-023 | `/sw-tasks` emits coarse refs despite PRD 053 execute tier | follow-on |
| gap-003 | Dual gap-storage paths; `planning_gap_capture` bypasses `planning_store` | 045 A1 (issue-store only) |

PRD 054 dogfood exposed gap-025 live: phases 3–4 merged partial migration-wave work (shadow pytest wrappers,
open parity/delete sub-tasks) because `/sw-deliver` advances on `merge-ready-green` alone and `tasks-currency`
only checks checkbox↔ledger alignment — not phase spec completion.

**Position in train:** ship after PRD 054 terminal merge, **before** issue-store program PRDs 044–047.
This PRD **absorbs** the file-store portions of frozen 046 A2/A3/A4 and 045 A1; those amendments are
**superseded** for implementation purposes (046/045 retain issue-store-specific scope only).

## Goals

1. Close all nine absorbed gaps with passing fixtures; flip each unit to `resolved` with schedule
   `PRD 055`.
2. Harden INDEX commit primitives (R31) before PRD 046 R80 projection work — gap-002 explicitly warns
   against baking the defect into issue-derived INDEX writes.
3. Deliver phase merge is blocked unless frozen sub-task acceptance criteria are mechanically satisfied
   (gap-025) — complementing, not replacing, PRD 053 execute-tier per-ref gating inside `/sw-ship`.
4. `/sw-tasks` emits execute-tier-optimal sub-task granularity at generation time (gap-023).
5. Gap capture routes through `planning_store` for **every** backend; legacy `GAP-BACKLOG.md` rows migrate
   to canonical `docs/prds/gap/<unit-id>/` units before retirement; projection replaces hand-append only
   after no unresolved backlog entries remain (gap-003).
6. Developer test harness trees never propagate to `dist/` or `core/scripts/` (gap-022).
7. PRD 015 R7 `supersede-reconcile` is restored on the canonical `reconcile.py` surface (gap-024).

## Non-Goals

- Issue-store planning graph, scheduler derivation, or R80 projection (PRD 046 core — remains 046 scope).
- Issue-native gap lifecycle via provider issues (PRD 045 R21/R72 — remains 045 scope when
  `backend == issue-store`).
- Migration of file artifacts to issue store (PRD 044).
- Re-opening or amending `complete` PRDs 015, 035, 040, 042, 050, 054 in place.
- PRD 054 W1/W2 **implementation recovery** on an in-flight feature branch — this PRD fixes **workflow**
  so future delivers cannot repeat merge-on-partial; 054 task completion is separate operator work.
- Replacing `deliver-advance-from-status-only` (R7) — gap-025 adds a **complementary** phase-acceptance gate,
  not status-only advancement removal.
- Retiring `GAP-BACKLOG.md` while **open** or **scheduled** legacy rows remain — migration to canonical
  gap units is a prerequisite (DL-5).

## Requirements

### Thread A — Mechanical primitives (gap-022, gap-024, gap-020)

- **R1** (gap-022) — `core/sw-reference/build-chain-sot.json` `coreScripts.excludes` MUST list `unit_tests/`
  and `tests/`; `scripts/copy-to-core.py` and `sw/emitter_base.py` MUST match the manifest (single source).
  Plugin `dist/{cursor,claude-code}/scripts/` MUST NOT contain developer test trees after
  `build-chain-sync.py`.
- **R2** (gap-022) — A regression fixture (`emitter-excludes-developer-test-trees` or extension of
  `run_emitter_fixtures.py`) MUST fail closed if `unit_tests/`, `tests/`, or `test/` appear under
  `dist/*/scripts/`.
- **R3** (gap-024) — `scripts/reconcile.py` MUST implement `append-superseded` and `supersede-reconcile`
  (ported from the PRD 015 contract); `/sw-memory-sync` step 8 MUST succeed without agent deferral.
- **R4** (gap-024) — Docs/skills/commands referencing `reconcile-status.py` for supersede operations MUST
  point at `reconcile.py`; `script-port-ledger.json` disposition rows refreshed; fixture
  `memory-sot-supersede-reconcile` passes.
- **R5** (gap-020) — `planning_index_gen.replace_region_inner` MUST preserve the newline contract of
  `render_region` (marker on its own line); fixture proves regenerate does not glue structural markers to
  table headers.

### Thread B — INDEX commit safety & terminal currency (gap-002, gap-007, gap-008)

- **R6** (gap-002, PRD 033 A1 R31) — `wave_living_docs.py` (`cmd_reconcile`, `cmd_append_terminal`,
  `git_commit_living_docs`) and `reconcile_lib.py:set_index_status` MUST refuse commits when the resolved
  worktree branch is `defaultBaseBranch`, matching `reconcile_prd_index`'s existing guard.
- **R7** (gap-002) — Fixture: `living-docs reconcile --commit` on `defaultBaseBranch` fails closed, never
  commits.
- **R8** (gap-007, supersedes 046 A2 file-store implementation) — `wave_deliver_loop.py`
  `finalize-completion` MUST invoke `living-docs reconcile --commit` with orchestrator worktree after
  successful `finalize-if-merged` and **before** `inflight_signal run-complete`, so INDEX rows flip to
  `complete` when `target_merge_detected()` is true.
- **R9** (gap-008, supersedes 046 A3 file-store implementation) — `inflight_signal.git_commit_inflight`
  MUST inherit the same `defaultBaseBranch` refusal as R6; `finalize-completion` is an explicit guarded
  call-site surface.
- **R10** (gap-007/008) — Fixture: deliver terminal path on a merged PRD sets INDEX `complete` without
  direct `main` commits outside orchestrator/docs worktree.

### Thread C — Deliver phase acceptance (gap-025)

- **R11** — Before deliver `merge-enqueue` / phase teardown, a mechanical **phase acceptance gate** MUST
  verify all executable sub-task refs for the active phase slug are `done` in `taskLedger` AND checkboxes
  toggled in the frozen task file. **`declared-partial`** is config-driven only: a durable ledger record
  naming skipped refs + operator ack; silent all-open MUST fail closed (resolves OQ-2 default).
- **R12** (PRD 007 R15 implementation gap) — `tasks-currency-gate` / `wave_state ledger check` MUST fail
  when a phase is `merge-ready-green` (or merge pending) but phase sub-task refs remain unchecked with no
  ledger `done` — the "all-unchecked for completed work" case; fixture
  `tasks-currency-unchecked-completed-work`.
- **R13** — A mechanical `gap-check-gate` (or verification-gate tier) MUST emit durable
  `gap-check.status.json` with binding `pass|halt`; `ship-phase-status.py` MUST refuse `merge-ready-green`
  when verdict is `halt`.
- **R14** — On execute ref terminal `green`, deliver/ship MUST auto `ledger record` + checkbox toggle for
  that ref (wire execute tier → task progress).
- **R15** — Fixture `deliver-phase-blocked-open-subtasks`: `merge-ready-green` with open sub-tasks (e.g.
  3.2/3.3) MUST NOT enqueue merge.
- **R25** — Deliver `merge-enqueue` / `merge_ready_in_flight_phases` MUST invoke the mechanical
  `gap-check-gate` on the deliver kernel path; `--fast` skip is prohibited for phase merge decisions
  (ship-only fast path unchanged).

### Thread D — Execute-tier authoring granularity (gap-023)

- **R16** — `/sw-tasks` MUST emit intra-phase sub-task refs sized for PRD 053 execute-tier fan-out: bounded
  file sets per ref; list-shaped PRD prose (suites, modules, registry entries) decomposed into one ref per
  bounded unit when contention rules permit parallelism.
- **R17** — Wire `phase_sizing.py` split preflight into `/sw-tasks` generation output (not advisory-only
  stdout); splits are part of the frozen artifact.
- **R18** — Update `core/skills/tasks/SKILL.md` and `core/commands/sw-tasks.md` — execute-tier granularity
  is a first-class generation requirement alongside Phase Dependencies and Traceability.
- **R19** — Fixture `sw-tasks-execute-granularity`: PRD with "port N suites" yields ≥N bounded refs or
  documented serial edges when contention forbids parallelism.
- **R20** — Runtime expansion in `execute_plan.py` remains the escape hatch for **already frozen** coarse
  lists; no frozen-task mutation.

### Thread E — Gap capture unification (gap-003, supersedes 045 A1 file-store portion)

- **R21** — `planning_gap_capture.py` and `/sw-feedback` trivial-gap path MUST route through
  `planning_store.put()` for **every** configured backend (file-store included), not only `issue-store`.
- **R22** — Reconcile `feedback/SKILL.md` Phase 3 with `living-status/SKILL.md`: new gap capture writes
  canonical `docs/prds/gap/<unit-id>/` via `planning_store`; `GAP-BACKLOG.md` remains until all legacy
  **open** and **scheduled** rows are migrated — then becomes a generated read-only projection (no hand-append).
- **R23** — `gap_backlog.py:flip_schedule` and `flip_resolve` MUST key on canonical unit ids from
  `docs/prds/gap/<unit-id>/` (`id:` frontmatter / `absorbs:` full slug) — **not** legacy `GAP-NNN` table
  rows, which are a disjoint namespace (e.g. legacy `GAP-002` ≠ `gap-002-living-doc-reconcile-…`). Generated
  `GAP-BACKLOG.md` projection MUST use canonical ids or an explicit alias map; no silent collision.
- **R24** — Migrate every legacy `GAP-BACKLOG.md` row still **open** or **scheduled** into canonical
  `docs/prds/gap/<unit-id>/` (or mark **resolved** with evidence) before 044 migration tooling runs or
  `GAP-BACKLOG.md` retirement; fixture `gap-backlog-migration-complete` fails closed if unresolved rows
  remain.
- **R26** — At PRD 055 freeze, frozen amendments **046 A2/A3/A4** and **045 A1** (file-store portions only)
  gain `superseded-by: PRD 055` frontmatter notes; 046/045 parents remain unchanged — implementation lands
  here only (DL-3).
- **R27** (DL-5) — `GAP-BACKLOG.md` MUST NOT be deleted or fully replaced by generated projection while any
  legacy row is **open** or **scheduled**; retirement is permitted only when migration fixture passes (zero
  unresolved legacy rows).

## Technical Requirements

- **TR1** (R1/R2) — Extend build-chain SoT + copy-to-core + emitter; regen `dist/`; extend
  `docs/guides/testing.md`: developer harness is repo-only.
- **TR2** (R3/R4) — Port supersede subcommands to `reconcile.py`; optional thin `reconcile-status.py` shim
  delegating to `reconcile.py` for one-release backward compat.
- **TR3** (R5) — Fix `replace_region_inner`; extend `index-region-guard.py` if present.
- **TR4** (R6/R7) — Shared `default_branch_commit_guard` primitive imported by living-docs, reconcile
  set-index-status, and inflight_signal (single module, Python-first).
- **TR5** (R8) — Wire terminal reconcile in `finalize-completion` with `--orchestrator-worktree`.
- **TR6** (R11–R15) — New `scripts/phase_acceptance_gate.py` (or extend `tasks-currency-gate.py` +
  `gap-check-gate.py`); kernel-classification.json updates for binding gap-check step; deliver
  `merge_ready_in_flight_phases` calls acceptance gate.
- **TR7** (R16–R19) — `/sw-tasks` generation pipeline + `phase_sizing.py` integration; PRD 040 R16/R30
  alignment for intra-phase splits at generation (not post-freeze rewrite).
- **TR8** (R21–R27) — `planning_store` routing; legacy-row → canonical-unit migration; conditional
  `GAP-BACKLOG.md` generated projection; `flip_schedule` namespace fix.
- **TR9** (docs currency) — Update `core/commands/sw-memory-sync.md` (step 8 supersede path),
  `core/skills/gap-check/SKILL.md` (deliver binding vs `--fast`), `core/commands/sw-deliver.md` (phase
  acceptance + terminal reconcile ordering), `core/skills/feedback/SKILL.md` + `living-status/SKILL.md`
  (generated backlog), `core/skills/tasks/SKILL.md` + `core/commands/sw-tasks.md` (R16–R18), and
  `docs/guides/testing.md` (R1/R2).

## Success Criteria

1. All nine canonical gap units under `docs/prds/gap/` absorbed here show `status: resolved` and
   `schedule: PRD 055` (or `— (PRD 055)`) after terminal merge — keyed by canonical unit id, not legacy
   `GAP-NNN` rows.
2. Every fixture in Testing Strategy passes in CI; `scripts/check-gate.py` green on the feature branch.
3. PRD 054-class partial merge cannot recur: open phase sub-task refs block `merge-enqueue` even when
   `merge-ready-green` + host evidence are present.
4. `/sw-memory-sync` step 8 completes without deferring `supersede-reconcile`.
5. Frozen 046 A2/A3/A4 and 045 A1 file-store amendments carry `superseded-by: PRD 055` at freeze (R26).
6. Zero **open**/**scheduled** legacy `GAP-BACKLOG.md` rows without a canonical unit (or resolved closure)
   before backlog retirement (R24/R27).

## Security & Compliance

- **SC1 (PRD 033 R31; implements R6/R9)** — No unguarded INDEX commits on shared `defaultBaseBranch`; fail
  closed.
- **SC2 (R3/R4)** — Supersede reconcile runs through redaction chokepoint before provider writes (existing
  memory R41 contract unchanged).
- **SC3** — No secrets in gap units or fixtures — test fixtures use synthetic paths only.

## Testing Strategy

| Fixture | Asserts | Gaps |
| --- | --- | --- |
| `emitter-excludes-developer-test-trees` | no test trees in dist | gap-022 |
| `memory-sot-supersede-reconcile` | supersede-reconcile exits 0 | gap-024 |
| `planning-index-marker-newline` | structural marker on own line | gap-020 |
| `living-docs-reconcile-refuses-default-branch` | R31 on living-docs path | gap-002 |
| `finalize-completion-index-complete` | terminal INDEX `complete` | gap-007 |
| `inflight-run-complete-refuses-default-branch` | R31 on inflight commit | gap-008 |
| `tasks-currency-unchecked-completed-work` | R15 negative case | gap-025 |
| `deliver-phase-blocked-open-subtasks` | merge blocked with open refs | gap-025 |
| `gap-check-gate-blocks-merge-ready` | status.json not merge-ready on halt | gap-025 |
| `deliver-gap-check-no-fast-skip` | merge path rejects `--fast` gap-check | gap-025 |
| `sw-tasks-execute-granularity` | bounded refs at generation | gap-023 |
| `gap-capture-planning-store-routing` | put() for file backend | gap-003 |
| `gap-flip-schedule-canonical-id` | no legacy GAP-NNN collision | gap-003 |
| `gap-backlog-migration-complete` | no open/scheduled legacy rows at retirement gate | gap-003 |

Extend `scripts/test/run-deliver-fixtures.sh`, `run_memory_sot_fixtures.py`, `run_emitter_fixtures.py`, and
`run_planning_035_gap_lifecycle_fixtures.py` as appropriate.

## Rollout Plan

1. **Phase 1** — Thread A (build-chain, reconcile supersede, INDEX generator newline). Low blast radius;
   unblocks honest dist/verify.
2. **Phase 2** — Thread B (R31 guards + terminal reconcile ordering). **Hard prerequisite** for PRD 046.
3. **Phase 3** — Thread C (deliver phase acceptance). Highest operator value; prevents repeat of PRD 054
   merge-on-partial.
4. **Phase 4** — Thread D (`/sw-tasks` granularity). Authoring contract; benefits future PRDs.
5. **Phase 5** — Thread E (gap capture unification + legacy backlog migration). `GAP-BACKLOG.md` persists
   until open/scheduled rows are migrated to canonical units; generated projection cutover only after R27 gate.

Each phase ships via `/sw-deliver` on `feat/workflow-fidelity-gap-closure` with terminal PR to `main`.
Update absorbed gap units to `status: resolved` / `schedule: PRD 055` via `gap_backlog.py` on merge.

## Decision Log

```json
{
  "decisions": [
    {
      "id": "DL-1",
      "summary": "Single PRD 055 absorbs nine standing gaps instead of amending complete PRDs or waiting for 046",
      "rationale": "Schedules pointing at 015/035/054 are stale; 046/045 amendments cover file-store fixes only as frozen drafts on not-started PRDs. One train item closes the cluster before 044-047.",
      "alternatives": ["046 A2/A3/A4 as-is", "multiple small PRDs"],
      "status": "accepted"
    },
    {
      "id": "DL-2",
      "summary": "Phase acceptance gate complements merge-ready-green, does not remove R7 status-only advance",
      "rationale": "R7 durable status is correct for CI/host evidence; missing piece is checklist/spec completeness before phase merge.",
      "alternatives": ["Revert to chat-driven completion", "Checkbox-only gate without gap-check binding"],
      "status": "accepted"
    },
    {
      "id": "DL-3",
      "summary": "046 A2/A3/A4 and 045 A1 file-store portions superseded by 055 implementation",
      "rationale": "Avoid duplicate implementation when 046/045 ship; 046 retains issue-store graph scope only.",
      "alternatives": ["Implement twice", "Block 044 until 046 ships"],
      "status": "accepted"
    },
    {
      "id": "DL-4",
      "summary": "gap-022 lands in PRD 055 Phase 1 — no PRD 054 amendment",
      "rationale": "PRD 054 implementation is in-flight and cannot be changed; developer-test-tree excludes ship via 055 Thread A after 054 merges.",
      "alternatives": ["054 tail amendment while branch open"],
      "status": "accepted"
    },
    {
      "id": "DL-5",
      "summary": "GAP-BACKLOG.md persists until legacy open/scheduled rows are migrated",
      "rationale": "Unresolved legacy backlog entries must not be dropped; migrate each to canonical docs/prds/gap/<unit-id>/ (or resolve with evidence) before generated projection replaces hand-maintained rows.",
      "alternatives": ["Immediate generated projection + dual-read shim", "Hard retire in Phase 5 regardless of open rows"],
      "status": "accepted"
    }
  ]
}
```

## Open Questions

- **OQ-1** — ~~054 tail amendment for gap-022~~ **Resolved:** PRD 054 is in-flight and **must not**
  be amended; gap-022 (build-chain exclude for `unit_tests/` / `tests/`) is owned exclusively by **PRD 055
  Phase 1** (Thread A, R1–R2).
- **OQ-2** — ~~`declared-partial` phase acceptance~~ **Resolved (R11):** config-driven durable ledger record
  + explicit skipped-ref list; no silent partial.
- **OQ-3** — ~~Retire `GAP-BACKLOG.md` in Phase 5~~ **Resolved (DL-5/R27):** `GAP-BACKLOG.md` **persists**
  while any legacy row is **open** or **scheduled**; those entries MUST migrate to canonical
  `docs/prds/gap/<unit-id>/` format (or close as **resolved**) before backlog retirement / generated-only
  cutover.
