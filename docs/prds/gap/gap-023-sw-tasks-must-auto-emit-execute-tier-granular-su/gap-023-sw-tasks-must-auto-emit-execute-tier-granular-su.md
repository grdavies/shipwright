---
id: gap-023-sw-tasks-must-auto-emit-execute-tier-granular-su
type: gap
status: scheduled
schedule: PRD 055
title: sw-tasks must auto-emit execute-tier granular sub-task refs at generation
visibility: public
tags: [source:feedback, signal:feedback-sw-tasks-execute-granularity-2026-07-02, prd-053, prd-040, prd-054, sw-tasks, execute-tier]
absorbs: []
---

# sw-tasks must auto-emit execute-tier granular sub-task refs at generation

_Scheduled to a follow-on PRD amending the `/sw-tasks` authoring contract (PRD 040 + PRD 053 integration)._

_Captured from feedback signal `feedback-sw-tasks-execute-granularity-2026-07-02` during PRD 054
implementation._

## Summary

PRD 053 made execute-tier fan-out **default-on** at `/sw-ship` phase entry, but left **authoring granularity**
to human judgment and optional runtime expansion. `/sw-tasks` still emits coarse sub-tasks (e.g. PRD 054 phase
3: `3.1 Port W1 suite list` as a single ref covering ~30 suites) even though PRD 053's value proposition is
per-ref parallel dispatch. Operators should not need to manually prompt for splits — `/sw-tasks` should emit
execute-tier-optimal ref granularity in its single-pass output.

**In-flight PRDs (e.g. 054):** frozen task lists cannot be amended mid-deliver. Runtime expansion
(`execute_plan.py` + `phase_sizing.score_execute_ref`) is the sanctioned fallback for coarse refs until this
gap closes.

## Root cause (design split, not accidental omission)

| PRD | Policy | Effect on `/sw-tasks` |
|-----|--------|----------------------|
| **040** R16/R30 | Split suggestions are **advisory only**; stripped at freeze; no auto-rewrite | `phase_sizing.py advisory` block is draft-only; model may ignore |
| **053** D-053-3 | `execute.*` thresholds are **runtime deliver policy, not authoring policy** | No sw-tasks SKILL update in PRD 053 task 6.2 |
| **053** non-goal | No auto-rewrite of frozen task lists | Blocks deliver-time mutation; does not require authoring-time granularity |
| **tasks/SKILL.md** | "Prefer many small phases" + executable shape | No requirement for ≥N sub-tasks per phase or per-suite refs |

PRD 053 task 6.2 updated deliver/ship/execute skills but **not** `core/skills/tasks/SKILL.md` or
`core/commands/sw-tasks.md`.

## Evidence

- PRD 054 `tasks-054-unit-testing-strategy.md` phase 3: three refs (`3.1`–`3.3`) where `3.1` bundles an entire
  migration wave — execute tier activates (≥2 refs) but parallelism is **3-wide**, not suite-wide.
- `phase_sizing.py` already has `propose_phase_split`, `evaluate_split_preflight`, and `score_execute_ref` —
  machinery exists but is not wired into `/sw-tasks` single-pass output.
- Operator expectation: PRD 053 default-on execute tier implies task lists are born granular; actual behavior
  requires manual re-run or relies on runtime synthetic children (`N.M.K`) in `execute-step-plan.json` only.

## Relationship to existing coverage

| Item | Overlap |
|------|---------|
| **PRD 040** | Phase-level split advisory — sub-task granularity within a phase not auto-applied |
| **PRD 053 R9–R11** | Runtime expansion for oversized single refs — complementary, not substitute for authoring clarity |
| **PRD 053 task 6.2** | Runtime/operator docs only — sw-tasks untouched |
| **gap-022** | Dist test-tree exclusion — unrelated |

## Remediation direction

1. **Authoring contract (follow-on PRD or PRD 053 amendment):** `/sw-tasks` SHALL decompose phases into
   executable sub-task refs sized for execute-tier fan-out:
   - Target: each ref touches a bounded file set (reuse `execute.sizing.thresholds` or `tasks.sizing.thresholds`).
   - When PRD prose implies a list (suites, modules, registry entries), emit one ref per bounded unit with
     disjoint `**File:**` paths where contention rules permit parallelism.
   - Wire `phase_sizing.py` split preflight into generation (not advisory-only stdout); splits become part of
     the frozen artifact, not a post-hoc suggestion block.
2. **Skill/command updates:** `core/skills/tasks/SKILL.md`, `core/commands/sw-tasks.md` — execute-tier
   granularity as a first-class generation requirement (alongside Phase Dependencies + Traceability).
3. **PRD 040 alignment:** Amend R16/R30 from "suggestion only" to "applied at generation, frozen as authored"
   for **intra-phase sub-task** splits (preserve no auto-rewrite of **already frozen** lists).
4. **Fixture:** `sw-tasks-execute-granularity` — given a PRD with "port N suites", generated task list has
   ≥N bounded refs in the target phase (or documents explicit serial edges when contention forbids parallelism).
5. **In-flight escape hatch (unchanged):** `execute_plan.py` runtime expansion remains for frozen coarse lists
   until re-generation is possible.

## Acceptance

- New `/sw-tasks` runs on PRDs like 054 produce suite/module-scoped refs without operator prompting.
- Frozen in-flight lists (054) continue to work via runtime expansion; no frozen-task mutation required.
- `spec-rigor-check.py` + `traceability-check.py` still pass on generated lists.
- Deliver dogfood: execute plan on a freshly generated medium phase shows batch width ≥2 when file sets are
  disjoint.

