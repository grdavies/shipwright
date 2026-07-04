---
id: gap-025-deliver-advances-on-ship-green-not-phase-checklist
type: gap
status: scheduled
schedule: PRD 055
title: deliver advances phases on ship-green without phase checklist acceptance
visibility: public
tags: [source:feedback, signal:feedback-deliver-checklist-bypass-2026-07-02, prd-054, prd-007, prd-035, deliver, gap-check, tasks-currency]
absorbs: []
---

# deliver advances phases on ship-green without phase checklist acceptance

_Scheduled to **PRD 035 A1** deliver conductor completion or a follow-on PRD closing the 007 R15 / gap-check
contract gap._

_Captured from feedback signal `feedback-deliver-checklist-bypass-2026-07-02` during PRD 054 implementation
review (phases 3–4: shadow ports merged with 3.2/3.3/4.2 still open)._

## Summary

`/sw-deliver` phase-mode treats a phase as **complete** when durable `status.json` reports
`merge-ready-green` (live CI + host evidence) and the phase merges into the feature branch — **not** when the
frozen task list's phase sub-tasks (e.g. PRD 054 `3.2`, `3.3`, `4.2`) are satisfied. During PRD 054, W1/W2
landed as thin pytest wrappers subprocess-ing legacy `run_*_fixtures.py` with partial suite coverage; phases
3–4 still had parity/delete/registry items open, yet the driver merged, tore down, and advanced.

Behavior is **mechanically consistent** with today's wiring (`deliver-advance-from-status-only`, R7) but
**violates PRD 054 phase acceptance** and the operator expectation that `/sw-ship` gap-check blocks partial
phase work before merge.

## Failure chain (PRD 054 phases 3–4)

| Layer | Expected | Observed |
|-------|----------|----------|
| **Deliver phase scope** | Phase = migration wave; all sub-tasks in one ship cycle | Correct structurally — one ship per phase |
| **Phase completion gate** | Frozen checklist + spec union satisfied before merge | `merge-ready-green` alone suffices |
| **tasks-currency (R15/R49)** | Block "all-unchecked for completed work" | Passes when **all** checkboxes open **and** ledger empty — only flags checkbox↔ledger **divergence** |
| **gap-check** | Binding map checklist→diff; halt on `partial`/`missing` before commit | Procedural skill only; no mechanical gate wired to `ship-phase-status` or deliver merge |
| **Execute tier (PRD 053)** | Per-ref terminal before `sw-verify` | May apply at ship entry, but deliver still merges whole phase on one green status — no per-ref merge gate |
| **Shadow parity** | TR14 dual-run until legacy deleted per wave | Partial port (e.g. W2 ~27/40 suites) treated as wave-complete |

## Evidence (code)

**Deliver merge enqueue keys on `status.json`, not task completion:**

`merge_ready_in_flight_phases` accepts a phase when `verdict == merge-ready-green` plus SHA/host evidence;
`tasks_currency_ok` only runs the ledger-alignment check (not "all phase refs done").

**tasks-currency passes with every checkbox open and empty ledger** (PRD 007 R15 "all-unchecked for completed
work" not enforced): `cmd_ledger_check` only diverges when a checked box lacks ledger or ledger `done` disagrees
with checkbox — unchecked refs with no ledger entry are skipped.

**PRD 007 R15 intent** (not fully implemented):

> A gate MUST verify the task file's checkbox state matches **actual phase/task completion** before the
> terminal merge gate; on divergence (e.g. an **all-unchecked task file for completed work**) it MUST
> hard-block …

Fixture `tasks-currency-gate-block` only covers checkbox-without-ledger divergence; fixture
`currency-gate-vs-ledger` explicitly tolerates partial checkbox sets when ledger aligns — not the PRD 054
failure mode (work merged, everything still unchecked).

**gap-check** (`core/skills/gap-check/SKILL.md`) is default-on in `/sw-ship` but **agent-procedural** —
maps checklist→diff, bounded closers — with no mechanical gate that persists a binding verdict consumed by
`ship-phase-status.py` or blocks deliver `merge-enqueue` on `partial`/`missing` mappings.

**Intentional status-only advance** (fixture `deliver-advance-from-status-only`): advancement keyed on
durable status, not chat — by design for R7, but without a complementary **phase acceptance** gate this
allows spec-incomplete phases to merge.

## PRD 054 concrete symptoms

From `tasks-054-unit-testing-strategy.md` (still open at time of feedback):

- **3.1** shadow port landed (thin wrappers + subset of suites).
- **3.2** `run_migration_parity_fixtures.py` W1 parity — **open**.
- **3.3** delete W1 legacy + registry cutover — **open**.
- **4.1** partial W2 port (~27/≈40) — **open** / incomplete vs inventory.
- **4.2** W2 parity + legacy delete — **open**.

Phase 3 set the pattern; phase 4 repeated the same merge-on-green shortcut.

## Relationship to existing coverage

| Item | Overlap |
|------|---------|
| **PRD 007 R15/R49** | Specifies completion vs checkbox gate — **implementation gap** (ledger sync only) |
| **PRD 035 A1** | Deliver conductor completion — natural schedule owner |
| **PRD 053 execute tier** | Per-ref ship gating inside one phase — **necessary but insufficient** without deliver-level acceptance |
| **gap-023** | `/sw-tasks` coarse refs — related authoring issue; does not fix merge-on-partial |
| **gap-011** | Conductor no-progress stalls — different failure class |
| **GAP-052** (resolved) | Hand-edited `status.json` — complementary; this gap is **legitimate** status from incomplete work |

No existing gap covers **deliver phase merge without checklist/spec acceptance** or **gap-check non-binding**
at the deliver boundary.

## Remediation direction

1. **Phase acceptance gate (deliver boundary):** before `merge-enqueue` / phase teardown, require mechanical
   evidence that all executable sub-task refs for the phase slug are `done` in `taskLedger` **and** checkboxes
   toggled (or explicit `declared-partial` with bounded refs — not silent all-open).
2. **Close R15 implementation gap:** extend `tasks-currency-gate` / `ledger check` to fail when phase status
   is `merge-ready-green` (or merge pending) but phase sub-task refs remain unchecked **and** ledger not
   `done` — the PRD 007 "all-unchecked for completed work" case.
3. **Mechanical gap-check gate:** add `scripts/gap-check-gate.py` (or verification-gate tier) emitting
   `gap-check.status.json` with binding `pass|halt`; `ship-phase-status.py` refuses `merge-ready-green` on
   `halt`; deliver `collect-status` surfaces blocked cause.
4. **Wire execute-ref terminal → ledger:** on execute ref `green`, auto `ledger record` + checkbox toggle for
   that ref; phase cannot reach merge-ready until all phase refs terminal **and** gap-check pass.
5. **Fixtures:**
   - `deliver-phase-blocked-open-subtasks` — merge-ready-green with open 3.2/3.3 must not enqueue merge.
   - `tasks-currency-unchecked-completed-work` — R15 negative case (merged phase, all checkboxes open).
   - `gap-check-gate-blocks-merge-ready` — binding verdict halts status write.

## Schedule

**PRD 035 A1** deliver conductor completion (primary), optionally paired with a narrow PRD amending 007 R15
implementation notes so `tasks-currency` and gap-check contracts are single-sourced in kernel classification.

**PRD 054 recovery:** phases 3–4 require **re-open implementation** on the feature branch (cannot amend frozen
054 tasks mid-flight); this gap governs **workflow** fixes so future deliver runs cannot repeat the shortcut.
