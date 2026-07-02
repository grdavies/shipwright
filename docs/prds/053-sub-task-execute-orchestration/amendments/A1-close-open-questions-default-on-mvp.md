---
date: 2026-07-02
amends: docs/prds/053-sub-task-execute-orchestration/053-prd-sub-task-execute-orchestration.md
supersedes: [D-053-8]
visibility: public
frozen: true
frozen_at: 2026-07-02
---

# Amendment A1: close Open Questions — default-on execute tier, closed R7 rules, MVP expansion, sub-branch ceiling

## Overview

Parent PRD 053 freezes with four Open Questions on pilot gating, R7 dependency rules, runtime expansion scope,
and sub-branch worktree accounting. This amendment **decides** all four with new requirements **R32–R35** and
decisions **D-053-9** through **D-053-12**. Parent OQ1–OQ4 are closed; no further freeze-time decisions
required on these topics.

## Context

Operator intent (2026-07-02):

1. **No opt-in pilot gate** — execute-tier orchestration becomes **default** phase-mode behavior, not guarded
   behind `execute.enabled: false` or TR0-style prerequisite fixtures.
2. **R7 rule table** — adopt a closed, data-driven rule pack (recommendation accepted).
3. **Runtime expansion** — ship R9–R11 in MVP (not deferred).
4. **Worktree ceiling** — carve out sub-branches from global `parallelCeiling`; do **not** raise global
   defaults (recommendation accepted).

## Goals

1. Make execute-tier fan-out the default `/sw-ship` path for multi-sub-task phases.
2. Replace open-ended R7 NLP with a versioned, fixture-tested rule table.
3. Confirm runtime expansion is in-scope for the initial implementation rollout.
4. Prevent execute sub-branch provisioning from starving wave/phase worktree slots.

## Non-Goals

- Raising global `worktree.parallelCeiling` or `intraPhase.harnessLimit` defaults repo-wide.
- TR0-style `pilot_dependency_gate.py` fixture as a prerequisite to enable execute tier.
- Editing the frozen parent file body (amendment-only).

## Requirements

Continue the parent namespace (parent max R31).

- **R32** (closes parent OQ1). **`execute.enabled` defaults to `true`** in
  `workflow.config.example.json` and `config.schema.json`. Execute-tier orchestration is **default-on** for
  phase-mode `/sw-ship` when the active phase has **two or more** executable sub-tasks. Phases with exactly one
  executable sub-task MAY skip execute-plan provisioning and run the legacy monolithic `sw-execute` step
  (optimization only — behavior equivalent). `execute.enabled: false` remains an **operator escape hatch** for
  emergency rollback; it is not a pilot opt-in gate and requires no prerequisite fixture. Parent D-053-8 is
  superseded.
- **R33** (closes parent OQ2). R7 implement-before-wire edges SHALL be driven exclusively by
  `core/sw-reference/execute-dependency-rules.json` (versioned, linted). The closed v1 rule pack MUST include
  at minimum:
  - **`wire-after-implement`** — a sub-task whose title matches `(?i)^Wire\b` receives a serial edge from the
    nearest prior sibling in the same phase whose title matches `(?i)^(Implement|Add)\b` when they share at
    least one `**File:**` path or the first backtick-quoted identifier in the title.
  - **`fixtures-after-prior-work`** — a sub-task whose title matches `(?i)\bFixtures?\b` receives serial edges
    from every prior executable sub-task in the same phase (fixtures run last).
  - **`traceability-row-order`** — when the frozen task list traceability table lists sub-task refs in column
    order for a requirement row, emit serial edges preserving that order among refs in the active phase.
  - No model judgment, no open-ended prose parsing beyond these rules. `execute_plan.py` loads the JSON;
    `scripts/test/run_execute_orchestration_fixtures.py` includes `execute-dependency-rules-049-phase-2`
    proving the PRD 049 phase 2 DAG (`2.1∥2.3` → `2.2` → `2.4` → `2.5`).
- **R34** (closes parent OQ3). Runtime recursive expansion (**R9–R11**) ships in the **MVP** rollout (parent
  Phases 2–5), not a post-pilot milestone. Fixture `execute-runtime-expansion-depth-cap` is a release gate.
- **R35** (closes parent OQ4). Execute sub-branch worktrees SHALL set **`countsTowardCeiling: false`**
  (parity with orchestrator/docs auxiliary worktrees per `core/skills/deliver/SKILL.md`). A separate cap
  **`execute.subBranchCeiling`** defaults to **`intraPhase.parallelBudget`** (not global `parallelCeiling`).
  The phase executor MUST refuse provision when active execute sub-branches would exceed
  `execute.subBranchCeiling`. Global `worktree.parallelCeiling` defaults are **unchanged** — do not raise them
  to accommodate sub-branches.

## Technical Requirements

### Config (amends parent config block)

```json
"execute": {
  "enabled": true,
  "subBranchCeiling": null,
  "maxExpansionDepth": 2,
  "sizing": {
    "thresholds": { "filesTouched": 3, "distinctDirs": 2, "traceabilityScenarios": 2 }
  }
}
```

- `subBranchCeiling: null` resolves at runtime to `intraPhase.parallelBudget`.
- Document default-on posture and escape hatch in `docs/guides/configuration.md`.

### New artifact

- **`core/sw-reference/execute-dependency-rules.json`** — `{ version, rules: [{ id, kind, ... }] }`; linted
  by `kernel_classification_lint.py` or dedicated fixture; referenced from `execute_plan.py`.

### Parent body alignment (effective via amendment union)

When applying this amendment to task generation, treat these parent passages as amended:

| Parent location | Effective reading |
| --- | --- |
| R1, R26 (`execute.enabled: true` guard) | Execute tier active by default; single-sub-task skip per R32 |
| Config `enabled: false` | `enabled: true` per R32 |
| Rollout "Backward compatible… `enabled: false`" | Escape hatch only; default-on per R32 |
| D-053-8 | Superseded by D-053-9 |
| `## Open Questions` | Closed by this amendment |

## Testing Strategy

Add to parent fixture manifest:

| Scenario | Covers |
|----------|--------|
| `execute-dependency-rules-049-phase-2` | R33 — wire/implement + fixtures-last on PRD 049 excerpt |
| `execute-sub-branch-ceiling-refuse` | R35 — provision refused when subBranchCeiling exceeded |
| `execute-single-subtask-skip-tier` | R32 — monolithic path when phase has one executable sub-task |

## Decision Log

- **D-053-9 (2026-07-02):** Execute tier is **default-on** (`execute.enabled: true`); no TR0 pilot gate;
  single-sub-task phases may skip tier. Supersedes D-053-8.
- **D-053-10 (2026-07-02):** R7 edges are **data-driven** from `execute-dependency-rules.json` with closed v1
  rules `wire-after-implement`, `fixtures-after-prior-work`, `traceability-row-order`.
- **D-053-11 (2026-07-02):** Runtime expansion **R9–R11 ships in MVP** with fixture gate.
- **D-053-12 (2026-07-02):** Sub-branch worktrees use **`countsTowardCeiling: false`** +
  **`execute.subBranchCeiling`** (default = `intraPhase.parallelBudget`); **do not** raise global
  `parallelCeiling` defaults.
