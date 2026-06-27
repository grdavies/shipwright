---
date: 2026-06-26
topic: deliver-plan-policy-pilot
prd: docs/prds/023-deliver-plan-policy-pilot/023-prd-deliver-plan-policy-pilot.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 023 Deliver plan-policy pilot, intra-phase parallelism, and benefit metric

Generated from the frozen PRD spec union (R15, R16, R17, R21, R22, R31 — owned; PRD-021/022 requirements are
**consumed**, not re-owned, so they are exercised live but not in the union). Phase 1 wires the `/sw-deliver`
pilot (wire-only) behind the hard dependency gate; the four owned-concern phases (intra-phase parallelism,
driver budgets, benefit metric, plan surfacing) fan out from it; docs/dist close. Default stays `canonical` —
`proposed` is enabled only in hermetic/opt-in repos per the staged Rollout.

## Tasks

### 1. Dependency gate + deliver pilot wiring (wire-only) + E2E — M

- [ ] 1.1 Dependency-gate fixture (021 → 022 dark → 023 pilot) (TR0)
  - **File:** `scripts/test/run-pilot-fixtures.sh`
  - **Expected:** `pilot-dependency-gate` — `proposed` is refused (failing-before) until PRD-022's `exec-fidelity-out-of-order-halt`, `resume-two-tier-deterministic`, and `resume-corrupt-plan-fail-closed` fixtures pass in CI; pins the ordering so the pilot cannot ship before the deterministic step driver is real.
  - **R-IDs:** TR0 (consumes 022 R26/R7/R8)
- [ ] 1.2 Wire `/sw-deliver` proposal sites to invoke 022 machinery (no changes to it) (TR1)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md`, `core/skills/conductor/SKILL.md`, `scripts/wave_deliver_loop.py`, `scripts/ship_phase_steps.py`
  - **Expected:** read `orchestration.planPolicy` at each proposal site; at **wave entry** conductor proposes batching → `wave.sh plan validate` → deliver-loop `nextAction` reads the persisted wave-batching plan from shared run-state; at **phase entry** executor proposes the step plan → validate → persist to per-phase run dir → `nextStep` driver reads it as sole authority and re-checks kernel ordering at each `advance`. **Wire-only:** no kernel/gate/driver/guideline-schema change (consumes 022 R5–R8, R26, R32, R34 lifecycle + between-tier resume).
  - **R-IDs:** TR1 (consumes 022 R5–R8, R26, R32, R34)
- [ ] 1.3 E2E pilot fixture + 022 parity suite under `proposed` (TR5a, TR5c)
  - **File:** `scripts/test/run-pilot-fixtures.sh`
  - **Expected:** `pilot-e2e-proposed-terminal-gate` — a representative multi-phase frozen task list delivers under `proposed` to the terminal-PR human gate; `pilot-022-parity-suite-under-proposed` re-runs **all** 022 TR7 chokepoint fixtures (`plan-proposed-memory-preflight-required`, `…-memory-redact-fail-closed`, `…-secret-scan-before-push`, `…-no-main-auto-merge`, `…-merge-single-flight`, `…-redaction-guard-range-scope`, `…-guardrails-hook-non-selectable`) as **blocking** pilot gates.
  - **R-IDs:** R22 (owned, exercised E2E); consumes 022 R2/R23/R28

### 2. Intra-phase fan-out + no-nesting + decision logging — M

- [ ] 2.1 Guideline-bounded intra-phase fan-out + validated disjoint partition + global cap (R15, TR2)
  - **File:** `core/rules/sw-subagent-dispatch.mdc`, intra-phase dispatch logic, `core/skills/parallelism/SKILL.md`
  - **Expected:** replace the fixed intra-phase dispatch list with a declared, guideline-bounded heuristic/budget consuming 021's `signal_context`; every fan-out proposal declares a **disjoint file/task partition** validated **before dispatch** (reject/serialize on overlap); bounded by `intraPhase.parallelBudget` and the global cap `waveSlots + activeIntraPhase ≤ min(worktree.parallelCeiling, harness limit)`. Fixtures `intra-phase-disjoint-partition-required`, `intra-phase-global-cap`, `intra-phase-no-durable-write-race` (parallel workers read-only on `ship-steps.json`/`status.json`).
  - **R-IDs:** R15
- [ ] 2.2 Pre-dispatch no-nesting enforcement + inline degrade (R16)
  - **File:** intra-phase dispatch guard, `core/skills/parallelism/SKILL.md`
  - **Expected:** when `conductor_mode: background_phase` (stamped to the per-phase run dir at phase entry), intra-phase Task dispatch is **refused before any spawn** (no TOCTOU) and degrades to inline two-stage review; `intra-phase-background-degrade-before-dispatch` asserts zero nested Task invocations.
  - **R-IDs:** R16
- [ ] 2.3 Intra-phase decision record (R17)
  - **File:** per-phase `dispatch-decisions.json` writer
  - **Expected:** each parallelization decision recorded with the defined shape (timestamp, signals, declared partition, chosen parallelism, degrade reason); `intra-phase-decision-logged`.
  - **R-IDs:** R17

### 3. Driver-enforced budgets + clean-halt integrity — M

- [x] 3.1 Persist + enforce budget counters in the deliver loop (R22, TR3)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** persist `runStartedAt`, `driverIterationCount`, `noProgressStreak`; read `deliver.autonomy.maxRunMinutes` / `maxIterations`, per-phase remediation, and the no-progress breaker; budgets are **driver-enforced** (durable counters, not agent prose) so adaptivity cannot extend a run past the ceilings; proposal/validation overhead accounted separately from execution (`budget-proposed-overhead-accounted`).
  - **R-IDs:** R22
- [x] 3.2 Clean consolidated halt with merge-queue + lock integrity (R22)
  - **File:** `scripts/wave_deliver_loop.py`, merge-queue/lock release path
  - **Expected:** a runaway/looping run converts to a **clean consolidated halt** that preserves merge-queue journal replayability and releases the orchestrator `O_EXCL` lock (no half-merged state); `budget-halt-merge-queue-integrity`.
  - **R-IDs:** R22
- [x] 3.3 Subscribe persistent plan rejection into the no-progress surface (R22)
  - **File:** `scripts/wave_deliver_loop.py` (consumes 022 `planRejectionLog`)
  - **Expected:** persistent plan rejection (022 R6 `planRejectionLog`) feeds the same no-progress signal; 023 **subscribes** to the schema, does not re-author it.
  - **R-IDs:** R22

### 4. Benefit metric capture + decision rule — M

- [ ] 4.1 `benefitMetric` run-record schema (numeric/enumerated only) (R31, TR4)
  - **File:** run/phase record schema (deliver run-state), `core/sw-reference/layout.md`
  - **Expected:** `benefitMetric` object — `planPolicy`, `kernelVerdict` (equivalence tuple), `executedStepSet` vs `canonicalStepSet`, `stepsSkippedWithoutRework`, `stabilizeReentries[]`, `escapedDefectSignal` (terminal-PR CI red or post-merge stabilize/revert within the attribution window), `phaseWallClockMs`, decomposed by category — fields numeric/enumerated only; `benefit-metric-no-sensitive-fields`.
  - **R-IDs:** R31
- [ ] 4.2 Benefit-report helper + pre-registered R31 decision rule (R31, TR4)
  - **File:** `scripts/wave.sh plan benefit-report` (+ `wave_plan_benefit.py`)
  - **Expected:** summarizes paired `proposed` vs `canonical` runs at identical kernel verdict; applies the decision rule (steps-skipped-net-of-rework primary/necessary positive; wall-clock not regressed beyond ε at equal verdict; min N per stratum); **fails closed to `canonical`** on insufficient N / non-positive benefit; `benefit-decision-rule-fail-closed`.
  - **R-IDs:** R31
- [ ] 4.3 Mandatory atypical-phase fixture + credit-only-absent-rework (R31, TR5b)
  - **File:** `scripts/test/run-pilot-fixtures.sh`
  - **Expected:** `pilot-atypical-phase-step-omit` — a docs-only phase whose gate-accepted proposed plan omits verify/simplify that canonical runs; `benefit-refuses-credit-on-later-stabilize` — a skipped step that triggers an attributed stabilize re-entry yields **zero** credit.
  - **R-IDs:** R31

### 5. Deliver-scoped plan surfacing — S

- [ ] 5.1 Surface chosen plans + rejections + capability set (R21)
  - **File:** deliver `run.log` writer + consolidated halt/terminal report
  - **Expected:** the chosen wave-batching plan, each phase's chosen step plan, plan **rejections with reasons**, and the resolved capability set appear in the deliver run log and the consolidated halt/terminal report (discharges the 021 R21 / 022-deferred surfacing for the deliver slice); `deliver-plan-surfacing`.
  - **R-IDs:** R21

### 6. Docs + emitter propagation + freshness — M

- [ ] 6.1 Deliver/conductor/parallelism prose + layout (R21, R22, R15, R16, R17)
  - **File:** `core/skills/deliver/SKILL.md`, `core/commands/sw-deliver.md`, `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`, `core/commands/sw-ship.md`, `core/skills/parallelism/SKILL.md`, `core/rules/sw-subagent-dispatch.mdc`, `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** proposed-path subsection + run-state `benefitMetric`/`intraPhaseFanOut`/`dispatch-decisions.json` fields + reporting-helper entry; proposals route through `wave.sh plan validate`; driver-enforced budget binding; intra-phase fan-out vs wave ceiling; phase-entry proposed step-plan caveat (canonical default unchanged).
  - **R-IDs:** R15, R16, R17, R21, R22
- [ ] 6.2 Guides + CONTRIBUTING + meta (R31)
  - **File:** `docs/guides/configuration.md`, `docs/guides/workflows.md`, `docs/guides/commands.md`, `docs/guides/getting-started.md`, `README.md`, `CONTRIBUTING.md`, `.sw/models-tiering.md`
  - **Expected:** deliver pilot note + pilot deep-dive; default-canonical + opt-in disclosure; pilot/budget/fan-out/benefit fixture suites + regenerate-dist reminder; one-line model-tiering orthogonality note.
  - **R-IDs:** R31
- [ ] 6.3 Regenerate both dist trees; freshness gate green (TR6)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** deliver/parallelism prose, schemas, and layout propagated; emitter freshness gate green; `dist/` parity with `core/`.
  - **R-IDs:** TR6

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 1 |
| 6 | 2, 3, 4, 5 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R15 | 2.1 | `intra-phase-disjoint-partition-required`; `intra-phase-global-cap`; `intra-phase-no-durable-write-race` |
| R16 | 2.2 | `intra-phase-background-degrade-before-dispatch` |
| R17 | 2.3 | `intra-phase-decision-logged` |
| R21 | 5.1 | `deliver-plan-surfacing` |
| R22 | 1.3, 3.1, 3.2, 3.3 | `budget-halt-merge-queue-integrity`; `budget-proposed-overhead-accounted` |
| R31 | 4.1, 4.2, 4.3 | `benefit-metric-no-sensitive-fields`; `benefit-refuses-credit-on-later-stabilize`; `benefit-decision-rule-fail-closed`; `pilot-atypical-phase-step-omit` |

## Relevant Files

- `core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md` — pilot opt-in surface + proposed-path wiring
- `scripts/wave_deliver_loop.py` — deliver-loop `nextAction` (stored wave layer) + driver-enforced budgets + clean halt
- `scripts/ship_phase_steps.py` — per-phase `nextStep` driver (consumed from 022; read sole-authority plan)
- `core/rules/sw-subagent-dispatch.mdc`, `core/skills/parallelism/SKILL.md` — intra-phase fan-out heuristic/budget, disjoint partition, no-nesting
- `scripts/wave_plan_benefit.py` / `wave.sh plan benefit-report` — benefit metric report + R31 decision rule
- per-phase `dispatch-decisions.json`, run/phase `benefitMetric` fields — run records
- `scripts/test/run-pilot-fixtures.sh` — dependency gate, E2E, atypical-phase, 022-parity-under-proposed, intra-phase, budget, benefit fixtures
- `.sw/layout.md`, `core/sw-reference/layout.md` — run-state field layout

## Notes

- **Hard dependency gate (TR0).** Phase 1.1 must be green-gated on 022's execution-fidelity + two-tier resume
  fixtures before any `proposed` enablement — shipping the pilot before the deterministic driver is real would
  prove proposal+logging while agents freestyle execution (a false safety proof).
- **Wire-only.** Phase 1 invokes 022's gate/driver/persistence at deliver call sites and changes none of it;
  the consumed PRD-021/022 requirements are exercised live but owned elsewhere.
- **Falsifiable metric is the program gate.** R31 (Phase 4) is the sole gate for any future default flip;
  steps-skipped-net-of-rework is the necessary primary signal, wall-clock a secondary guard, and the rule
  fails closed to `canonical` on insufficient N. The numeric thresholds/cohort are pre-registered during the
  soak (Rollout step 2), not in this task list.
- **Intra-phase is a new race surface.** Disjoint-partition validation, read-only-on-durable-files, the global
  cap, and pre-dispatch no-nesting (Phase 2) are the safety additions over 022's between-phase contention edges.
- Default stays `canonical`; first soak is hermetic/fixture repos, real opt-in requires per-run ack + an
  integration/non-`main` target (Rollout).
