---
brainstorm: docs/brainstorms/2026-06-26-guidelined-autonomous-orchestration-requirements.md
date: 2026-06-26
topic: deliver-plan-policy-pilot
frozen: true
frozen_at: 2026-06-26
---
# PRD 023 — Deliver plan-policy pilot, intra-phase parallelism, and benefit metric

## Overview

This is **PRD-3 of the four-PRD guidelined-autonomous-orchestration program** (021 → 022 → 023 → 024). It is
the **pilot**: `/sw-deliver` becomes the first orchestrator to actually run `orchestration.planPolicy:
proposed` end-to-end, consuming PRD-021's capability manifest and PRD-022's guidelines + plan-validation gate.
It also widens intra-phase parallelism latitude within the existing rails and adds the **benefit metric**
that gates any future change of the default from `canonical` to `proposed`. Because 021 and 022 are **frozen**,
this PRD also discharges contracts they deferred to "the deliver pilot": the deliver-scoped surfacing of
chosen plans and plan rejections (021 R21 / 022 Non-Goals) and the live re-assertion of every 022 kernel
chokepoint under `proposed` (022 TR7).

`/sw-deliver` is chosen as the pilot because it already adopts the conductor contract (PRD-009) and exercises
**both** proposal tiers (conductor wave-batching + phase-executor step plans) — and because the phase
executors run `/sw-ship --phase-mode`, the deliver pilot exercises **per-phase step-plan adaptivity** (the
program's headline pain: an atypical phase forced through verify/simplify) as well as wave batching. A
lower-stakes single-phase pilot could not exercise both tiers, so deliver-first is a deliberate
coverage-over-isolation choice; the blast radius is bounded by staged opt-in (Rollout) and the unchanged
no-`main`-merge kernel.

**Hard dependency gate.** This pilot's safety rests on PRD-022's *deterministic step driver* (R26/TR4) and
plan-validation gate — not on validating plan documents alone. It therefore **must not enable `proposed` in
any repo until PRD-022's execution-fidelity (`exec-fidelity-out-of-order-halt`) and two-tier resume fixtures
pass in CI** (Rollout step 0). Shipping the pilot before the driver is real would prove proposal+logging while
agents still freestyle execution — a false safety proof.

**Program exit (consumed from 022 / brainstorm SC9).** This is the slice that *proves or disproves* the
program's payoff. If R31 shows no net benefit at equal safety, the default stays `canonical` indefinitely,
PRD-024 fan-out is gated, and the proposed-path machinery is retired or iterated — 021's manifest and 022's
kernel classification retain standalone value, but the 023/024 investment is what the metric gates.

Source brainstorm R-IDs carried forward verbatim. This PRD owns R15–R17, R22, R31, and the **deliver-scoped
slice of R21**; it consumes (does not re-own) the PRD-021/022 requirements it exercises end-to-end.

## Goals

1. `/sw-deliver` runs `orchestration.planPolicy: proposed` end-to-end on a representative frozen task list —
   **including at least one atypical phase** (e.g. docs-only) whose proposed step plan omits non-kernel steps
   (verify/simplify) that canonical would run: conductor proposes wave batching, phase executors propose step
   plans, the gate validates, and the run reaches the terminal-PR human gate with every safety invariant intact.
2. A phase executor may decide intra-phase fan-out from a declared, guideline-bounded heuristic/budget within
   the existing ceiling rails, with a validated disjoint-file partition and without nested dispatch.
3. Plan-driven runs stay bounded by the existing autonomy budgets — **mechanically enforced by the driver**,
   not agent prose; adaptivity cannot extend a run past those ceilings, and a budget-halt-rate increase versus
   canonical is itself an anti-benefit signal.
4. A **guarded, falsifiable** benefit metric with a pre-registered decision rule demonstrates whether
   `proposed` beats `canonical` at identical kernel verdict and net of rework, attributing benefit by category
   (step-plan adaptivity vs wave-schedule vs intra-phase); absent net benefit, the default stays `canonical`.
5. Chosen wave/phase plans, plan rejections, and the resolved capability set are surfaced in the deliver run
   log and consolidated halt/terminal report (deliver-scoped R21).

## Non-Goals

- Turning `proposed` on by default — the metric (R31) gates that decision; this PRD leaves the default
  `canonical`.
- Adoption for `/sw-debug`, `/sw-doc`, `/sw-feedback` — PRD-024.
- The manifest/selector (PRD-021) or the kernel/gate/guidelines/flag (PRD-022) — consumed, not rebuilt. In
  particular, TR1 is **wire-only**: it invokes 022's gate/driver/persistence at deliver call sites and makes
  **no** change to the kernel classification, the gate, the step driver, or the guideline schema.
- Rebuilding the durable driver / crash-safe state core (PRD-007) or the conductor loop (PRD-009) — consumed
  and wired, not rebuilt.
- Nested sub-agent dispatch as a relied-upon capability.
- Auto-merge to `main`.
- Changing the `orchestration.planPolicy` flag *definition* (schema/default/seeding/in-flight semantics) —
  owned by PRD-022 R29; this PRD only *reads* it at deliver proposal sites.

## Success Criteria

Measurable, PRD-local outcomes (not just mechanisms):

1. **SC1 — E2E pilot to terminal gate:** a representative multi-phase frozen task list delivers under
   `proposed` to the terminal-PR human gate with all 022 kernel parity fixtures (TR7) green (R5–R8, R22, R23,
   R26, R32, R34).
2. **SC2 — Headline adaptivity exercised:** at least one atypical phase (docs-only) runs a gate-accepted
   proposed step plan that omits non-kernel steps canonical would run, and R31 credits the delta **only** when
   no later stabilize re-entry / escaped defect is attributed (R31, TR5).
3. **SC3 — Intra-phase safety:** parallel intra-phase workers operate on a validated disjoint-file partition;
   a background-phase context refuses nested dispatch *before any spawn* and degrades to inline (R15, R16).
4. **SC4 — Bounded autonomy:** a runaway/looping fixture trips the driver-enforced run ceiling / no-progress
   breaker into a clean consolidated halt with merge-queue + lock integrity preserved (R22).
5. **SC5 — Falsifiable metric:** the R31 decision rule (pre-registered thresholds, min N per kernel-verdict
   stratum, paired A/B with wave shape held constant) is computable from the run record and fail-closes to
   `canonical` when N is insufficient or benefit is non-positive (R31).
6. **SC6 — Auditability:** chosen wave/phase plans, plan rejections (with reasons), and the resolved
   capability set appear in the deliver run log and consolidated halt/terminal report (R21 deliver slice).

## Requirements

### Owned — intra-phase parallelism, budgets, benefit metric, deliver-scoped surfacing

- **R15** A phase executor may decide intra-phase fan-out (independent edits, parallel reviewers) from a
  declared, **guideline-bounded** heuristic/budget rather than a fixed list. Ceiling accounting is **split**:
  wave phase worktrees count toward `worktree.parallelCeiling`; intra-phase fan-out is bounded by a separate
  `intraPhase.parallelBudget` and **never consumes wave ceiling slots**, but a **global cap**
  `waveSlots + activeIntraPhase ≤ min(worktree.parallelCeiling, harness limit)` holds so combined concurrency
  cannot exceed the real process/harness ceiling. Every fan-out proposal must declare a **disjoint file/task
  partition** validated before any dispatch; overlapping partitions are rejected or serialized.
- **R16** Intra-phase parallelism never relies on nested sub-agent dispatch. Enforcement is **mechanical and
  pre-dispatch**: when a phase runs as a backgrounded parallel sub-agent (`conductor_mode: background_phase`,
  stamped to the per-phase run dir at phase entry), intra-phase Task dispatch is **refused before any spawn**
  (no TOCTOU window) and degrades to inline two-stage review; a fixture asserts zero nested Task invocations.
- **R17** Each intra-phase parallelization decision is recorded in the per-phase run record with a defined
  shape (timestamp, signals, declared partition, chosen parallelism, degrade reason).
- **R21** (deliver slice) The chosen wave-batching plan, each phase's chosen step plan, plan **rejections with
  reasons**, and the resolved capability set are surfaced in the deliver run log and the consolidated
  halt/terminal report — discharging the surfacing 021 R21 and 022 deferred to the deliver pilot. (PRD-024
  extends the same pattern to the other orchestrators.)
- **R22** Plan-driven runs remain bounded by the existing autonomy budgets (per-phase remediation, run-level
  wall-clock/iteration ceiling, no-progress circuit breaker), **enforced by the deterministic driver** (durable
  iteration count, run-start timestamp, no-progress streak — not agent prose). Adaptivity cannot extend a run
  past these ceilings; the proposed path's proposal/validation overhead is accounted separately from execution
  so a runaway converts to a **clean consolidated halt** that preserves merge-queue journal replayability and
  releases the orchestrator `O_EXCL` lock (no half-merged state). Persistent plan rejection (PRD-022 R6) feeds
  the same no-progress signal; 023 **subscribes to** 022's `planRejectionLog` schema (does not re-author it).
- **R31** The run record captures a benefit signal per phase/run measured **only among runs with an identical
  kernel verdict** (a defined equivalence class — tuple of terminal phase statuses + gate outcomes +
  merge-ready count, compared within the same frozen task-list fixture before cross-task generalization) and
  **net of rework**, with an explicit **escaped-defect window/attribution** (terminal-PR CI + an N-day
  post-merge stabilize/revert window attributed to pilot phases). Benefit is **decomposed by category** —
  step-plan adaptivity (steps skipped with no attributed rework), wave-schedule (wall-clock from batching), and
  intra-phase (wall-clock from fan-out) — and **steps-skipped-net-of-rework is the primary, necessary signal**
  for any default-flip recommendation; wall-clock is a secondary guard that must not regress beyond ε at equal
  verdict (and is reported with wave shape held constant). The metric **fails closed** (no benefit credited)
  when N per stratum is insufficient. This guarded metric is the sole gate for any future change of the default
  from `canonical` to `proposed`. Benefit fields are numeric/enumerated only — no free text, file contents, or
  transcript excerpts.

### Consumed (validated end-to-end here; primary home elsewhere)

- Capability selection (R9–R14, R27 — PRD-021) drives persona/provider selection within each proposed phase
  plan, from the persisted static `signal_context` (021 R10).
- Plan proposal/validation/persistence, the **deterministic step driver + full-trace kernel envelope**, the
  two-tier lifecycle, guidelines, and the tamper-resistant floor (R5–R8, R26, R28, R30, R32–R34 — PRD-022) are
  exercised **live** on `/sw-deliver` via `wave.sh plan validate`.
- The `orchestration.planPolicy` flag (R29 — PRD-022) is **read at deliver proposal sites** to enable the
  pilot when set to `proposed`; its definition/default/resume semantics remain PRD-022. Safety invariants
  (R23 — PRD-022) and the full kernel envelope (R2/R28) are re-asserted under the live pilot via 022's named
  TR7 parity fixtures.

## Technical Requirements

- **TR0 — Dependency gate (precondition).** The pilot is strictly downstream of 021+022. `proposed` MUST NOT
  be enabled in any repo (fixture or opt-in) until PRD-022's `exec-fidelity-out-of-order-halt`,
  `resume-two-tier-deterministic`, and `resume-corrupt-plan-fail-closed` fixtures pass in CI. A
  failing-before dependency fixture pins this ordering (021 → 022 dark → 023 pilot).
- **TR1 — Deliver pilot wiring (wire-only).** A call-site integration map (mirroring 022 TR9 deliver rows)
  wires `/sw-deliver` (and `skills/deliver`, `skills/conductor`) to **invoke** 022's machinery without
  changing it: read `orchestration.planPolicy` at each proposal site; at wave entry the conductor proposes
  batching → `wave.sh plan validate` → the **conductor deliver-loop `nextAction`** reads the persisted
  wave-batching plan from shared run-state; at phase entry the executor proposes the step plan → validate →
  persist to the per-phase run dir, after which the **per-phase step driver `nextStep`** reads that plan as
  sole authority and re-checks kernel ordering at each `advance` (022 R26/R34 lifecycle states +
  between-tier resume consumed). No gate/driver/kernel/guideline-schema changes here.
- **TR2 — Intra-phase fan-out from declared budget.** Replace the fixed intra-phase dispatch list with a
  declared, **guideline-bounded** heuristic/budget (extending `rules/sw-subagent-dispatch.mdc` and consuming
  021's `signal_context`); the proposal declares a **disjoint file/task partition** validated before dispatch
  (reject/serialize on overlap), is bounded by `intraPhase.parallelBudget` + the global cap (R15), and
  degrades to inline when `conductor_mode: background_phase` (R16). Each decision is written to a per-phase
  `dispatch-decisions.json` record (R17).
- **TR3 — Driver-enforced budget binding.** Mechanize the budgets in the deliver loop: persist
  `runStartedAt`, `driverIterationCount`, and `noProgressStreak`; read `deliver.autonomy.maxRunMinutes` /
  `maxIterations`, per-phase remediation, and the no-progress breaker; emit `halt-blocked` with a typed cause
  on trip; account proposal/validation overhead separately from execution; subscribe persistent plan rejection
  (PRD-022 R6 `planRejectionLog`) into the same no-progress surface. A clean halt preserves merge-queue
  replayability and releases the `O_EXCL` lock (R22).
- **TR4 — Benefit metric capture + schema.** Extend the run record (per-phase + run) with a `benefitMetric`
  object — `planPolicy`, `kernelVerdict` (equivalence tuple), `executedStepSet` vs `canonicalStepSet`,
  `stepsSkippedWithoutRework`, `stabilizeReentries[]`, `escapedDefectSignal` (defined proxy: terminal-PR CI
  red or post-merge stabilize/revert within the attribution window), `phaseWallClockMs`, decomposed by
  category — fields numeric/enumerated only (no transcripts/secrets). A reporting helper (e.g.
  `wave.sh plan benefit-report`) summarizes paired `proposed` vs `canonical` runs and applies the R31 decision
  rule (R31).
- **TR5 — Pilot fixtures (named).** (a) E2E pilot on a representative multi-phase task list to the terminal
  gate; (b) **mandatory atypical-phase fixture** — a docs-only phase whose proposed plan omits verify/simplify
  that canonical runs, gate-accepted, with R31 crediting the delta only absent attributed rework; (c) all 022
  TR7 parity fixtures re-run under `proposed` as **blocking** pilot gates; (d) intra-phase disjoint-partition,
  background-degrade-before-dispatch, and global-cap fixtures; (e) budget-halt merge-queue/lock integrity; (f)
  benefit-metric no-sensitive-fields + refuses-credit-on-later-stabilize. Each ships failing-before /
  passing-after and wires into `verify.test`.
- **TR6 — Emitter propagation + freshness.** Regenerate both dist trees; freshness gate green.

## Documentation deliverables

Pilot-delta documentation only — UPDATE deliver-side prose to reflect `proposed` actually running; do **not**
re-document 021/022 artifacts or re-gate the PRD-009 living-doc indexes (`INDEX.md`, `COMPLETION-LOG.md`,
`GAP-BACKLOG.md`):

- **Deliver/conductor:** `core/skills/deliver/SKILL.md` (proposed-path subsection + run-state `benefitMetric`/
  `intraPhaseFanOut` fields + reporting-helper entry), `core/commands/sw-deliver.md` (pilot opt-in surface),
  `core/skills/conductor/SKILL.md` (live proposed lifecycle + driver-enforced budget binding),
  `core/rules/sw-conductor.mdc` (proposals route through `wave.sh plan validate`), `core/commands/sw-ship.md`
  (phase-entry proposed step plan caveat).
- **Parallelism/dispatch:** `core/skills/parallelism/SKILL.md` (intra-phase fan-out vs wave ceiling),
  `core/rules/sw-subagent-dispatch.mdc` (heuristic/budget fan-out, disjoint partition, background degrade,
  run-record logging).
- **Layout:** `.sw/layout.md` + `core/sw-reference/layout.md` (per-phase `intraPhaseFanOut` + `dispatch-decisions.json`
  + run/phase `benefitMetric` fields).
- **Guides + meta:** `docs/guides/configuration.md` (deliver pilot note), `docs/guides/workflows.md` (pilot
  deep-dive), `docs/guides/commands.md` + `docs/guides/getting-started.md` + `README.md` (default-canonical +
  opt-in disclosure), `CONTRIBUTING.md` (pilot/budget/fan-out/benefit fixtures + regenerate-dist), one-line
  `.sw/models-tiering.md` orthogonality note.

## Security & Compliance

- **Full kernel envelope holds live (R2, R23, R26, R28 consumed).** The pilot does not relax any kernel
  chokepoint, and execution fidelity (driver re-checks ordering at each `advance`) is asserted live — not just
  document validity. All of 022's **named** TR7 parity fixtures run under `proposed` as blocking gates:
  `plan-proposed-memory-preflight-required`, `plan-proposed-memory-redact-fail-closed`,
  `plan-proposed-secret-scan-before-push`, `plan-proposed-no-main-auto-merge`,
  `plan-proposed-merge-single-flight`, `plan-proposed-redaction-guard-range-scope`,
  `plan-proposed-guardrails-hook-non-selectable`.
- **Intra-phase concurrency safety (R15).** New within-phase parallelism requires a validated disjoint-file
  partition before dispatch; parallel intra-phase workers are read-only on shared per-phase durable files
  (`ship-steps.json`, `status.json`) — only the phase executor writes them — preserving 022's single-writer
  intent at the intra-phase layer.
- **No nested dispatch, pre-dispatch enforced (R16).** A background-phase context refuses intra-phase Task
  spawn *before* any dispatch (no TOCTOU) and degrades to inline two-stage review.
- **Bounded autonomy with clean-halt integrity (R22).** Budgets/breaker are driver-enforced; a runaway
  converts to a clean consolidated halt that preserves merge-queue journal replayability and releases the
  `O_EXCL` lock — no half-merged state.
- **Staged opt-in blast radius (Rollout).** First soak is hermetic/fixture repos; real repos require explicit
  per-run pilot acknowledgement and an integration/non-`main` target, with a production-signal guard in
  `/sw-init`/doctor — `proposed` cannot silently reach a shared `main`.
- **Benefit-metric data minimization (R31/TR4).** Run-record benefit fields are numeric/enumerated only; no
  secrets, file contents, or raw transcripts; any operator-visible surfacing flows through the existing
  redaction chokepoint.

## Testing Strategy

A named fixture table (name | asserts | R-IDs), failing-before / passing-after, wired into `verify.test` (some
entries depend on 022 fixtures landing — TR0):

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `pilot-dependency-gate` | `proposed` refused until 022 exec-fidelity + resume fixtures pass | TR0 |
| `pilot-e2e-proposed-terminal-gate` | representative task list delivers under `proposed` to terminal gate | R5–R8, R32, R34 (consumed); R22 owned |
| `pilot-atypical-phase-step-omit` | docs-only phase omits verify/simplify, gate-accepted; R31 credits only absent rework | R26, R31, TR5 |
| `pilot-022-parity-suite-under-proposed` | all 022 TR7 chokepoint fixtures green under `proposed` | R2, R23, R28 |
| `intra-phase-disjoint-partition-required` | fan-out without validated disjoint partition rejected | R15 |
| `intra-phase-no-durable-write-race` | parallel workers read-only on ship-steps/status | R15 |
| `intra-phase-background-degrade-before-dispatch` | background phase → zero nested Task spawns, inline | R16 |
| `intra-phase-global-cap` | waveSlots + intraPhase ≤ min(ceiling, harness) enforced | R15 |
| `intra-phase-decision-logged` | each fan-out decision in `dispatch-decisions.json` | R17 |
| `budget-halt-merge-queue-integrity` | runaway → clean halt; queue replayable; lock released | R22 |
| `budget-proposed-overhead-accounted` | proposal overhead counted separately; no canonical-vs-proposed completion regression hidden | R22 |
| `benefit-metric-no-sensitive-fields` | benefit fields numeric/enumerated only | R31 |
| `benefit-refuses-credit-on-later-stabilize` | skipped step that triggers attributed stabilize → zero credit | R31 |
| `benefit-decision-rule-fail-closed` | insufficient N / non-positive → stays canonical | R31 |
| `deliver-plan-surfacing` | chosen plans + rejections + capability set in run log / terminal report | R21 |

## Rollout Plan

0. **Dependency gate (TR0):** land 021 + 022 (dark); confirm 022 execution-fidelity + two-tier resume fixtures
   green in CI before any `proposed` enablement.
1. Enable `proposed` for the `/sw-deliver` pilot in **hermetic/fixture repos first**; real opt-in repos require
   explicit per-run acknowledgement + integration/non-`main` target; default stays `canonical`.
2. Soak the pilot under a **pre-registered protocol**: defined representative task-list cohort, paired
   `canonical` baseline on identical inputs, minimum N per kernel-verdict stratum, fixed soak window; collect
   the decomposed benefit metric.
3. A default-flip recommendation requires the R31 decision rule to pass (primary steps-skipped-net-of-rework
   positive, wall-clock not regressed) — **out of scope here** and gated; insufficient evidence stays
   `canonical`.
4. PRD-024 fans the proved pattern out to the other orchestrators — gated on a positive R31 outcome.

## Decision Log

- **`/sw-deliver` as pilot, deliver-first** (brainstorm convergence + 009 precedent): it already adopts the
  conductor contract and exercises **both** proposal tiers, and its phase executors run `/sw-ship --phase-mode`
  so the headline per-phase step-plan adaptivity is exercised too. Deliver-first is coverage-over-isolation;
  a narrower single-phase pilot could not exercise both tiers. Blast radius is bounded by staged opt-in and the
  unchanged no-`main`-merge kernel (doc-review product P1 considered; resolved via the mandatory atypical-phase
  fixture rather than re-choosing the pilot, which the frozen 021/022 already commit to).
- **Hard dependency gate** (doc-review feasibility/adversarial P0): the pilot consumes 022's deterministic step
  driver; it cannot enable `proposed` until 022 execution-fidelity + resume fixtures pass, else it would prove
  proposal+logging while agents freestyle execution (TR0).
- **Falsifiable, decomposed benefit metric** (doc-review product P0 + adversarial P1): R31 gets a pre-registered
  decision rule, a defined kernel-verdict equivalence class and escaped-defect window, and benefit decomposed by
  category with steps-skipped-net-of-rework as the *necessary primary* signal — so wave-batching wall-clock
  cannot masquerade as step-chain adaptivity and a tiny/biased sample cannot trigger a default flip.
- **Intra-phase concurrency is a new race surface** (doc-review adversarial/security P0/P1): 022's contention
  edges are between phases; this PRD adds disjoint-partition validation, read-only-on-durable-files, a global
  concurrency cap, and pre-dispatch no-nesting enforcement for *within-phase* parallelism.
- **Deliver-scoped R21 owned here** (frozen 021/022 contract): 021 R21 and 022 Non-Goals defer chosen-plan /
  rejection surfacing to "the deliver pilot in PRD-023"; since those PRDs are frozen, 023 owns the deliver slice.
- **Intra-phase fan-out widened within existing rails** (brainstorm B/R15–R17): guideline-bounded, partitioned,
  no nested dispatch.
- **Program exit if R31 negative** (brainstorm SC9, mirrors 022): default stays `canonical`, PRD-024 gated,
  proposed-path machinery retired/iterated; 021/022 retain standalone value, the 023/024 investment is gated.

## Open Questions

None blocking. Doc-review deferred questions are **decided** in this revision: kernel-verdict equivalence and
the escaped-defect attribution window are defined in R31; intra-phase partition validation lives at dispatch
time (TR2); the global concurrency cap is `min(worktree.parallelCeiling, harness limit)` (R15); opt-in real
repos require an integration/non-`main` target (Rollout). The only deferred decision is the *numeric* R31
thresholds + cohort, which are pre-registered during the soak (Rollout step 2) and are explicitly **not** a
default-flip authorization — any future flip from `canonical` to `proposed` remains out of scope and gated by
R31.
