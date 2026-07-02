---
date: 2026-07-02
topic: sub-task-execute-orchestration
prd: docs/prds/053-sub-task-execute-orchestration/053-prd-sub-task-execute-orchestration.md
visibility: public
frozen: true
frozen_at: 2026-07-02
---

# Tasks — PRD 053 Sub-task execute orchestration

Single-pass task list from the frozen PRD 053 spec union (R1–R35; amendment A1 closes OQ1–OQ4). Phases mirror
the PRD rollout plan: schema/git foundation → execute-plan builder → integrate primitive → dispatch/failure →
autonomy/ship-chain gate → documentation and dogfood closure. Execute tier is **default-on** (R32); runtime
expansion ships in MVP (R34).

## Tasks

### 1. Execute-plan schema, kernel registry, and shared git helper (M)

Foundation artifacts with no deliver runtime behavior change until later phases wire them.

- [ ] 1.1 Add `execute-step-plan.schema.json` (R3, R4)
  - **File:** `core/sw-reference/execute-step-plan.schema.json`
  - **Expected:** JSON Schema for `{ version, tier: "execute", phaseId, phaseSlug, refs[], edges[], batches[], planPolicy, kernelVersion, guidelineVersion, validatedAt }`; registered in `build-chain-sot.json`
  - **R-IDs:** R3, R4
- [ ] 1.2 Register execute tier in kernel classification (R4)
  - **File:** `core/sw-reference/kernel-classification.json`, `scripts/kernel_classification_lint.py`
  - **Expected:** `planPolicySteps` entry `phaseType: execute`; lint green; `python3 scripts/build-chain-sync.py` after edits
  - **R-IDs:** R4
- [ ] 1.3 Implement shared `git_integrate.py` (R16)
  - **File:** `scripts/_sw/git_integrate.py`
  - **Expected:** `merge_branch_into(target_wt, source_ref) -> { verdict, conflicts[] }`; stdlib-only; conflict path enumeration; abort leaves target worktree clean on failure
  - **R-IDs:** R16, R31
- [ ] 1.4 Refactor `wave_merge.cmd_merge_exec` to use git helper (R16, SC7)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** phase→target merge delegates to `_sw/git_integrate.py` with no semantic change; existing wave-merge fixtures remain the regression oracle
  - **R-IDs:** R16, R31
- [ ] 1.5 Add `execute.*` config block default-on (R32, R35)
  - **File:** `core/sw-reference/config.schema.json`, `.sw/config.schema.json`, `workflow.config.example.json`
  - **Expected:** top-level `execute` object with `enabled: true` default, `subBranchCeiling: null` (resolves to `intraPhase.parallelBudget`), `maxExpansionDepth`, `sizing.thresholds`; no global `parallelCeiling` default change
  - **R-IDs:** R32, R35
- [ ] 1.6 Fixture `wave-merge-no-regression` (SC7)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `wave-merge-no-regression` registered and green after git helper extraction
  - **R-IDs:** R16

### 2. Execute plan builder, validator, and dependency rules (L)

Closed-world DAG construction, validation, runtime expansion, and dry-run entry from phase ship.

- [ ] 2.1 Author `execute-dependency-rules.json` v1 pack (R7, R33)
  - **File:** `core/sw-reference/execute-dependency-rules.json`
  - **Expected:** versioned rules `wire-after-implement`, `fixtures-after-prior-work`, `traceability-row-order`; linted; no open-ended NLP hooks
  - **R-IDs:** R7, R33
- [ ] 2.2 Implement `execute_plan.py` builder core (R1, R5, R6, R8, R25)
  - **File:** `scripts/execute_plan.py`
  - **Expected:** parses frozen task-list sub-tasks for active phase; injects contention edges via shared `wave_deliver.py` primitives; proposes parallel batches respecting `intraPhase.parallelBudget` + global cap; records `dispatch-decisions.json`; `planPolicy: canonical` emits linear batches width 1 except contention-forced serial
  - **R-IDs:** R1, R5, R6, R8, R25, R31
- [ ] 2.3 Wire dependency-rules loader (R7, R33)
  - **File:** `scripts/execute_plan.py`
  - **Expected:** R7 edges sourced exclusively from `execute-dependency-rules.json`; no inline title NLP beyond rule table
  - **R-IDs:** R7, R33
- [ ] 2.4 Runtime recursive expansion in builder (R9, R10, R11, R34)
  - **File:** `scripts/execute_plan.py`
  - **Expected:** single-ref `phase_sizing.py` scorer; synthetic child refs `N.M.K` in execute plan only; never mutates frozen task lists; depth capped by `execute.maxExpansionDepth` (fail-closed)
  - **R-IDs:** R9, R10, R11, R34
- [ ] 2.5 Extend `wave_plan_validate.py` for `--tier execute` (R2, R3, R4)
  - **File:** `scripts/wave_plan_validate.py`, `scripts/wave.py`
  - **Expected:** closed-world ref IDs; cycle detection; batch disjointness vs contention edges; persists validated plan to `.cursor/sw-deliver-runs/<phase-slug>/execute-step-plan.json`; stamps `planPolicy`, `kernelVersion`, `guidelineVersion`
  - **R-IDs:** R2, R3, R4, R31
- [ ] 2.6 Canonical linear fallback on reject (R2)
  - **File:** `scripts/execute_plan.py` or `scripts/wave_plan_validate.py`
  - **Expected:** `execute_fallback_canonical_linear_order(task_list, phase_id)` — authored numeric order + injected contention edges; stamped on validator reject per PRD 022
  - **R-IDs:** R2
- [ ] 2.7 Deep-ref tokenizer support (R29)
  - **File:** `scripts/doc_format.py`, `scripts/phase_sizing.py`
  - **Expected:** authored refs matching `\d+(\.\d+)+` parse and score correctly
  - **R-IDs:** R29
- [ ] 2.8 Builder/validator fixtures (R2, R6, R7, R9–R11, R33, R34, R29)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `scripts/test/fixtures/execute-orchestration/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `execute-plan-linear-fallback`, `execute-plan-contention-serializes-shared-file`, `execute-dependency-rules-049-phase-2`, `execute-runtime-expansion-depth-cap`, `execute-tokenizer-deep-refs` registered and green
  - **R-IDs:** R2, R6, R7, R9, R10, R11, R29, R33, R34

### 3. Integration primitive and journal (M)

Option C integrate path — phase-executor scoped, separate from conductor merge queue.

- [ ] 3.1 Implement `execute_integrate.py` (R15, R16, R19)
  - **File:** `scripts/execute_integrate.py`
  - **Expected:** CLI `integrate --task-ref <ref> --phase-slug <slug> [--retry]`; uses `_sw/git_integrate.py`; single-flight serialize per phase worktree; abort dirty tree on failure (mirror `wave_merge`); exit 20 + `cause: integrate:conflict` on conflict
  - **R-IDs:** R15, R16, R19, R31
- [ ] 3.2 Integrate journal writes (R17)
  - **File:** `scripts/execute_integrate.py`
  - **Expected:** appends to `.cursor/sw-deliver-runs/<phase-slug>/integrate-journal.json`; deterministic ordering for resume; separate from phase `mergeQueue` / `mergeJournal`
  - **R-IDs:** R17
- [ ] 3.3 `wave.py execute integrate` dispatch alias (R15)
  - **File:** `scripts/wave.py`
  - **Expected:** `python3 scripts/wave.py execute integrate …` aliases `execute_integrate.py`
  - **R-IDs:** R15, R31
- [ ] 3.4 Integration fixtures (R15, R19, R20)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `execute-integrate-clean-merge`, `execute-integrate-conflict-partial-batch`, `execute-integrate-parallel-batch-serialized` registered and green
  - **R-IDs:** R15, R19, R20

### 4. Sub-branch dispatch, failure handling, and R45 carve-out (L)

Provision isolated sub-branches, per-ref Task dispatch, blast-radius, and background_phase carve-out.

- [ ] 4.1 Sub-branch provision with ceiling carve-out (R12, R35)
  - **File:** `scripts/execute_plan.py`, `scripts/worktree.py`, `scripts/wave_lifecycle.py`
  - **Expected:** branch `feat/<slug>-phase-<pslug>--task-<ref>`; `countsTowardCeiling: false`; refuse when active sub-branches exceed `execute.subBranchCeiling` (default `intraPhase.parallelBudget`); eager teardown after successful integrate
  - **R-IDs:** R12, R35, R31
- [ ] 4.2 `execute_fan_out` conductor mode + stamp-context (R14)
  - **File:** `scripts/intra_phase_dispatch.py`
  - **Expected:** `stamp-context` accepts `execute_fan_out`; nested execute Tasks permitted under this mode
  - **R-IDs:** R14
- [ ] 4.3 Background-phase carve-out + capability index (R14)
  - **File:** `core/rules/sw-dispatch-background-phase.mdc`, `core/sw-reference/capability-index.json`
  - **Expected:** `background_phase` disables nested Tasks except execute tier when `execute-step-plan.json` has parallel batches; execute partition `intraphaseSubagentDispatch: enabled`
  - **R-IDs:** R14
- [ ] 4.4 Per-ref `/sw-execute` Task dispatch (R13)
  - **File:** `scripts/ship_phase_steps.py` (or phase ship driver), `core/commands/sw-execute.md`
  - **Expected:** one bound sub-agent Task per execute-plan ref scoped to that ref only; per-ref `.cursor/sw-execute-runs/<ref>/status.json`
  - **R-IDs:** R13
- [ ] 4.5 Implement `execute_failure.py` (R18, R21)
  - **File:** `scripts/execute_failure.py`, `scripts/wave.py`
  - **Expected:** `blast-radius apply --task-ref <ref> --phase-slug <slug>` blocks transitive dependents in execute DAG only; `remediation route` increments per-ref `remediationAttempts` from `deliver.remediation.maxAttempts`; integrates successful refs before blocking (R20)
  - **R-IDs:** R18, R20, R21, R31
- [ ] 4.6 Dispatch/failure fixtures (R18, R35)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `execute-blast-radius-dependents`, `execute-sub-branch-ceiling-refuse` registered and green
  - **R-IDs:** R18, R35

### 5. Ship-chain gate, autonomy, resume, and default-on wiring (M)

Gate `sw-verify` on execute-plan terminal status; wire autonomy selectors and durable resume.

- [ ] 5.1 Wire execute tier into phase ship driver (R1, R22, R26, R32)
  - **File:** `scripts/ship_phase_steps.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** phase entry validates execute plan before fan-out; per-ref work replaces monolithic `sw-execute` when `execute.enabled` (default true) and phase has ≥2 executable sub-tasks; single-sub-task phases skip to monolithic path; phase chain resumes at `sw-verify` only when all refs terminal (`green` or documented `skipped`)
  - **R-IDs:** R1, R22, R26, R32
- [ ] 5.2 Wire `deliver.autonomy.mode` execute-tier halts (R23, R24)
  - **File:** `scripts/execute_plan.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** `autonomous` auto-proposes/dispatches/remediates to budget; `supervised` halts once per phase after plan validation for DAG confirm; supervised fail-fast on first sub-task failure without auto-remediation
  - **R-IDs:** R23, R24
- [ ] 5.3 Record `benefitMetric.stepPlanAdaptivity` (R27, SC8)
  - **File:** `scripts/wave_deliver_loop.py` (or phase terminal status writer)
  - **Expected:** phase terminal status records refs parallelized, runtime expansions, skipped refs, parallel batch width
  - **R-IDs:** R27
- [ ] 5.4 Durable resume frontier (R28)
  - **File:** `scripts/execute_plan.py`
  - **Expected:** resume from `execute-step-plan.json` + per-ref status + integrate journal reproduces frontier without chat context; stale sub-branch rebase/reprovision path
  - **R-IDs:** R28
- [ ] 5.5 Memory redaction on execute artifacts (R30)
  - **File:** `scripts/execute_failure.py`, memory routing call sites
  - **Expected:** execute plans, integrate journals, failure reports pass `scripts/memory-redact.py` before memory write; frozen artifacts never auto-mutated
  - **R-IDs:** R30
- [ ] 5.6 Ship-chain, autonomy, and resume fixtures (R22, R24, R28, R32)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `execute-ship-chain-gated`, `execute-autonomy-supervised-plan-halt`, `execute-resume-frontier`, `execute-resume-stale-sub-branch`, `execute-single-subtask-skip-tier` registered and green
  - **R-IDs:** R22, R24, R28, R32

### 6. Documentation, layout, and dogfood closure (M)

Publish operator-facing docs and prove PRD 049 phase 2 replay end-to-end.

- [ ] 6.1 Layout and lifecycle registry rows (R3, R4)
  - **File:** `.sw/layout.md`, `core/sw-reference/layout.md`, `core/sw-reference/call-site-map.md`
  - **Expected:** registry rows for `execute-step-plan.json`, `integrate-journal.json`, sub-branch naming, wave/phase/execute three-tier lifecycle; PRD 022 call-site-map execute-tier row
  - **R-IDs:** R3, R4
- [ ] 6.2 Skills, commands, and rules updates (R13–R15, D-053-7)
  - **File:** `core/skills/deliver/SKILL.md`, `core/commands/sw-ship.md`, `core/commands/sw-execute.md`, `core/skills/execute-discipline/SKILL.md`, `core/skills/conductor/SKILL.md`, `core/skills/parallelism/SKILL.md`, `core/rules/sw-subagent-dispatch.mdc`, `core/rules/sw-conductor.mdc`
  - **Expected:** execute tier entry, ref-scoped `/sw-execute`, `execute_fan_out`, integrate vs merge-queue boundary, PRD 004 sub-task parallelism supersede footnote; `python3 scripts/build-chain-sync.py` after edits
  - **R-IDs:** R13, R14, R15
- [ ] 6.3 Configuration guide (R32, R35)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** documents `execute.*` default-on, escape hatch `execute.enabled: false`, `subBranchCeiling`, autonomy halt matrix, `planPolicy` × autonomy interaction
  - **R-IDs:** R32, R35
- [ ] 6.4 Register execute orchestration fixture harness (SC1–SC8)
  - **File:** `scripts/test/run_execute_orchestration_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** all named scenarios from PRD Testing Strategy registered; harness entrypoint exists and is CI-invokable
  - **R-IDs:** R1–R35
- [ ] 6.5 Dogfood fixture `execute-plan-dag-049-phase-2` green (SC1, SC2, SC8)
  - **File:** `scripts/test/fixtures/execute-orchestration/`, `scripts/test/run_execute_orchestration_fixtures.py`
  - **Expected:** replay proposes batch `{2.1, 2.3}` then serial `2.2`, `2.4`, `2.5` with mandatory `2.2 → 2.4` edge on `scripts/wave_deliver_loop.py`; distinct per-ref status artifacts; `stepPlanAdaptivity` batch width ≥2
  - **R-IDs:** R1, R8, R33
- [ ] 6.6 Definition-of-done verification
  - **File:** `docs/prds/053-sub-task-execute-orchestration/053-prd-sub-task-execute-orchestration.md`
  - **Expected:** every scenario in PRD Testing Strategy + amendment A1 Testing Strategy registered in manifest and green; repo search for `execute_plan.py`, `execute_integrate.py`, `execute_failure.py` returns positive matches; `python3 scripts/check-gate.py` advisory pass on implementation branch
  - **R-IDs:** R1–R35

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 2, 3 |
| 5 | 4 |
| 6 | 5 |

## Traceability

| R-ID | Task ref | Named test scenario | ZOMBIES checklist |
|------|----------|---------------------|-------------------|
| R1 | 2.2, 5.1, 6.5 | execute-plan-dag-049-phase-2 | O, M, I, S |
| R2 | 2.5, 2.6, 2.8 | execute-plan-linear-fallback | Z, O, E, I |
| R3 | 1.1, 2.5, 6.1 | execute-plan-dag-049-phase-2 | O, I, S |
| R4 | 1.1, 1.2, 2.5, 6.1 | execute-plan-dag-049-phase-2 | O, I, S |
| R5 | 2.2, 2.8 | execute-plan-dag-049-phase-2 | O, M, I |
| R6 | 2.2, 2.8 | execute-plan-contention-serializes-shared-file | O, M, B, I |
| R7 | 2.1, 2.3, 2.8 | execute-dependency-rules-049-phase-2 | O, M, I, E |
| R8 | 2.2, 6.5 | execute-plan-dag-049-phase-2 | O, M, I, S |
| R9 | 2.4, 2.8 | execute-runtime-expansion-depth-cap | O, B, I, E |
| R10 | 2.4 | execute-runtime-expansion-depth-cap | O, I, E |
| R11 | 2.4, 2.8 | execute-runtime-expansion-depth-cap | O, B, E, I |
| R12 | 4.1 | execute-sub-branch-ceiling-refuse | O, I, S |
| R13 | 4.4, 6.2 | execute-plan-dag-049-phase-2 | O, M, I, S |
| R14 | 4.2, 4.3, 6.2 | execute-plan-dag-049-phase-2 | O, I, E |
| R15 | 3.1, 3.4 | execute-integrate-parallel-batch-serialized | O, M, I, S |
| R16 | 1.3, 1.4, 3.1 | wave-merge-no-regression | O, I, E, S |
| R17 | 3.2 | execute-integrate-clean-merge | O, I, S |
| R18 | 4.5, 4.6 | execute-blast-radius-dependents | O, M, I, E |
| R19 | 3.1, 3.4 | execute-integrate-conflict-partial-batch | O, M, E, S |
| R20 | 3.4, 4.5 | execute-integrate-conflict-partial-batch | O, M, I, S |
| R21 | 4.5 | execute-blast-radius-dependents | O, B, I, E |
| R22 | 5.1, 5.6 | execute-ship-chain-gated | O, I, E, S |
| R23 | 5.2 | execute-plan-dag-049-phase-2 | O, I, S |
| R24 | 5.2, 5.6 | execute-autonomy-supervised-plan-halt | O, I, E |
| R25 | 2.2 | execute-plan-linear-fallback | O, I, E |
| R26 | 5.1 | execute-ship-chain-gated | O, I, S |
| R27 | 5.3, 6.5 | execute-plan-dag-049-phase-2 | O, M, I |
| R28 | 5.4, 5.6 | execute-resume-frontier | Z, O, I, S |
| R29 | 2.7, 2.8 | execute-tokenizer-deep-refs | O, B, M, I |
| R30 | 5.5 | execute-blast-radius-dependents | O, I, E |
| R31 | 1.3, 2.2, 3.1, 4.5 | wave-merge-no-regression | O, I, E |
| R32 | 1.5, 5.1, 5.6 | execute-single-subtask-skip-tier | O, B, I, E |
| R33 | 2.1, 2.3, 2.8, 6.5 | execute-dependency-rules-049-phase-2 | O, M, I, E |
| R34 | 2.4, 2.8 | execute-runtime-expansion-depth-cap | O, B, I, E |
| R35 | 1.5, 4.1, 4.6 | execute-sub-branch-ceiling-refuse | O, B, I, E |
